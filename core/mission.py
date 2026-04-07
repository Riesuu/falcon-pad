# -*- coding: utf-8 -*-
"""
falcon_pad.mission — BMS mission data: INI parsing, state management.

Manages the `mission_data` global which contains steerpoints, PPT threats,
and flight plan lines. Data can come from:
  1. SharedMem NavPoints (primary when BMS is in 3D) — called from broadcast loop
  2. Auto-loaded .ini files (DTC/callsign.ini) — background watcher
  3. Manual upload via /api/upload

Public API:
    mission_data              — the current dict {"route":[], "threats":[], "flightplan":[]}
    ini_status()              — dict with last loaded file info
    parse_ini_content(text)   — parse .ini text, return mission_data dict
    update_from_shm(route, threats) — update from SharedMem steerpoints
    find_latest_ini(extra_patterns)  — find most recent .ini with [STPT]
    parse_ini_file(path)      — parse and set mission_data from file

Copyright (C) 2026  Riesu — GNU GPL v3
"""

from __future__ import annotations

import configparser
import glob
import logging
import math
import os
import time
from typing import List, Optional, Tuple

import app_info
from core.theaters import bms_to_latlon, in_theater_bbox, get_theater_name

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════════════════

mission_data: dict = {"route": [], "threats": [], "flightplan": []}
_ini_last_path: str = ""
_ini_last_mtime: float = 0.0
_shm_mission_hash: str = ""

def _registry_ini_patterns() -> List[str]:
    """Discover BMS install dirs from registry (all versions) and return glob patterns."""
    patterns: List[str] = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, app_info.BMS_REGISTRY_BASE) as root:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(root, i)
                    i += 1
                    if not subkey_name.lower().startswith(app_info.BMS_REGISTRY_PREFIX):
                        continue
                    with winreg.OpenKey(root, subkey_name) as sk:
                        install_dir, _ = winreg.QueryValueEx(sk, app_info.BMS_REGISTRY_KEY)
                    cfg = os.path.join(install_dir, *app_info.BMS_USER_CONFIG_SUB)
                    patterns.append(os.path.join(cfg, "*.ini"))
                    patterns.append(os.path.join(cfg, "**", "*.ini"))
                except OSError:
                    break
    except (OSError, ImportError):
        pass
    return patterns


# ═══════════════════════════════════════════════════════════════════════════
#  STATUS
# ═══════════════════════════════════════════════════════════════════════════

def ini_status() -> dict:
    """Return status of the last loaded .ini file."""
    return {
        "file": os.path.basename(_ini_last_path) if _ini_last_path else None,
        "path": _ini_last_path,
        "loaded": bool(_ini_last_path),
        "mtime": _ini_last_mtime,
        "steerpoints": len(mission_data.get("route", [])),
        "ppt": len(mission_data.get("threats", [])),
        "flightplan": len(mission_data.get("flightplan", [])),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  STPT PARSING (shared between upload and file watcher)
# ═══════════════════════════════════════════════════════════════════════════

def _parse_stpt_section(cfg: configparser.RawConfigParser) -> dict:
    """
    Parse [STPT] section from a ConfigParser.
    Returns {"route": [...], "threats": [...], "flightplan": [],
             "airfields": {"dep": {lat,lon}, "arr": [{lat,lon},...]}}.

    BMS INI target type codes:
        0=waypoint, 1=takeoff, 2=target, 7=landing, 8=IP
    """
    route: List[dict] = []
    threats: List[dict] = []
    fplan: List[dict] = []
    # Collect takeoff (type=1) and landing (type=7) positions
    _dep_pos = None
    _land_positions: List[dict] = []

    if not cfg.has_section("STPT"):
        return {"route": route, "threats": threats, "flightplan": fplan}

    for key, val in cfg["STPT"].items():
        parts = val.split(",")
        if len(parts) < 3:
            continue
        try:
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            if abs(x) <= 10 or abs(y) <= 10:
                continue
            lat, lon = bms_to_latlon(x, y)
            kl = key.lower()

            if "line" in kl:
                fplan.append({"lat": lat, "lon": lon, "alt": z,
                              "index": len(fplan)})
            elif "ppt" in kl:
                try:
                    r_ft = float(parts[3])
                    range_m = int(r_ft * app_info.FT_TO_M)
                    range_nm = max(1, round(r_ft / app_info.FT_TO_NM_DIVISOR))
                except (ValueError, IndexError):
                    range_m = app_info.PPT_DEFAULT_RANGE_M
                    range_nm = app_info.PPT_DEFAULT_RANGE_NM
                name_ppt = parts[4].strip() if len(parts) > 4 else ""
                try:
                    ppt_num = 56 + int(kl.replace("ppt_", "").strip())
                except (ValueError, IndexError):
                    ppt_num = 56 + len(threats)
                if in_theater_bbox(lat, lon):
                    threats.append({
                        "lat": lat, "lon": lon, "name": name_ppt,
                        "range_nm": range_nm, "range_m": range_m,
                        "num": ppt_num, "index": len(threats),
                    })
            else:
                # Extract type code (4th field) for target_/stpt_ entries
                type_code = -1
                if (kl.startswith("target") or kl.startswith("stpt") or kl.startswith("steerpoint")) and len(parts) >= 4:
                    try:
                        type_code = int(float(parts[3]))
                    except (ValueError, TypeError):
                        pass
                if type_code == 1 and _dep_pos is None:
                    _dep_pos = {"lat": lat, "lon": lon}
                elif type_code == 7:
                    _land_positions.append({"lat": lat, "lon": lon})
                route.append({"lat": lat, "lon": lon, "alt": z,
                              "index": len(route)})
        except (ValueError, TypeError) as e:
            logger.debug(f"STPT parse skip key={key}: {e}")
            continue

    result = {"route": route, "threats": threats, "flightplan": fplan}

    # Build airfields dict from type codes
    if _dep_pos or _land_positions:
        af: dict = {"_typed": True}  # Flag: positions come from INI type codes
        if _dep_pos:
            af["dep"] = _dep_pos
        # First landing point = arrival; additional ones with different coords = alternate
        if _land_positions:
            af["arr"] = _land_positions[0]
            for lp in _land_positions[1:]:
                # Different position from arrival? → alternate
                if (abs(lp["lat"] - af["arr"]["lat"]) > 0.01 or
                        abs(lp["lon"] - af["arr"]["lon"]) > 0.01):
                    af["alt"] = lp
                    break
        result["airfields"] = af

    return result


def _dist_nm(lat1, lon1, lat2, lon2):
    """Haversine distance in nautical miles."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return app_info.GREAT_CIRCLE_NM * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def _find_nearest_airport(lat, lon, airports, max_nm=app_info.AIRPORT_SEARCH_NM):
    """Find nearest airport ICAO within max_nm, or None."""
    best_icao, best_d = None, max_nm
    for ap in airports:
        d = _dist_nm(lat, lon, ap["lat"], ap["lon"])
        if d < best_d:
            best_d = d
            best_icao = ap["icao"]
    return best_icao


def match_airfields_to_airports(airfields: dict, airports: list,
                                max_nm: float = app_info.AIRPORT_SEARCH_NM) -> dict:
    """
    Match airfield positions (from INI type codes) to known airports.
    Returns dict with dep/arr/alt keys → airport ICAO or None.
    """
    result = {}
    for role in ("dep", "arr", "alt"):
        pos = airfields.get(role)
        result[role] = _find_nearest_airport(pos["lat"], pos["lon"], airports, max_nm) if pos else None
    return result


def find_airfields_from_route(route: list, airports: list,
                              max_nm: float = app_info.AIRPORT_SEARCH_NM) -> dict:
    """
    Scan all route steerpoints to find dep/arr/alt by proximity to known airports.
    Used when type codes are not available (SharedMem path).
    - dep = first steerpoint matching an airport (from start)
    - arr = last steerpoint matching a different airport (from end)
    - alt = next distinct airport match (from end, different from dep and arr)
    """
    if not route or not airports:
        return {"dep": None, "arr": None, "alt": None}

    # Match each steerpoint to nearest airport
    matches = [_find_nearest_airport(wp["lat"], wp["lon"], airports, max_nm)
               for wp in route]

    # dep = first match from start
    dep = next((icao for icao in matches if icao), None)

    # arr = last match from end, different from dep
    arr = next((icao for icao in reversed(matches) if icao and icao != dep), None)
    # If no different airport found, last match (round trip to same base)
    if arr is None:
        arr = next((icao for icao in reversed(matches) if icao), None)

    # alt = any other distinct airport (scan from end)
    seen = {dep, arr}
    alt = next((icao for icao in reversed(matches) if icao and icao not in seen), None)

    return {"dep": dep, "arr": arr, "alt": alt}


def _parse_radio_section(cfg: configparser.RawConfigParser) -> dict:
    """
    Parse [Radio] section from a BMS DTC .ini file.
    Returns {"uhf": [...], "vhf": [...], "ils": [...]}.
    Frequencies converted from integer kHz to MHz float.
    """
    result: dict = {"uhf": [], "vhf": [], "ils": []}
    if not cfg.has_section("Radio"):
        return result
    radio = cfg["Radio"]
    for band, count, divisor in [("UHF", 20, 1000.0), ("VHF", 20, 1000.0), ("ILS", 4, 100.0)]:
        for i in range(1, count + 1):
            raw = radio.get(f"{band}_{i}", "0")
            comment = radio.get(f"{band}_COMMENT_{i}", "")
            try:
                val = int(raw)
                if val <= 0:
                    continue
                freq = round(val / divisor, 3)
                result[band.lower()].append({"num": i, "freq": freq, "comment": comment})
            except (ValueError, TypeError):
                continue
    return result


def _parse_comms_section(cfg: configparser.RawConfigParser) -> dict:
    """Parse [COMMS] section from a BMS DTC .ini file (TACAN, ILS)."""
    if not cfg.has_section("COMMS"):
        return {}
    comms = cfg["COMMS"]
    result: dict = {}
    try:
        ch = int(comms.get("TACAN Channel", "0"))
        band = "Y" if comms.get("TACAN Band", "0") == "1" else "X"
        if ch > 0:
            result["tacan"] = f"{ch}{band}"
    except (ValueError, TypeError):
        pass
    try:
        ils = int(comms.get("ILS Frequency", "0"))
        if ils > 0:
            result["ils_freq"] = round(ils / 100.0, 2)
    except (ValueError, TypeError):
        pass
    try:
        result["ils_crs"] = int(comms.get("ILS CRS", "0"))
    except (ValueError, TypeError):
        pass
    return result


def match_comms_to_airport(comms: dict, airports: list) -> str | None:
    """
    Identify departure airport from COMMS TACAN channel.
    The DTC COMMS TACAN is always set to the home/recovery base.
    Returns ICAO or None.
    """
    if not comms or not airports:
        return None

    tacan = comms.get("tacan", "")
    if not tacan:
        return None

    for ap in airports:
        if ap.get("tacan", "").upper() == tacan.upper():
            return ap["icao"]
    return None


def load_radio_from_dir(config_dir: str) -> bool:
    """
    Find and load [Radio]+[COMMS] from the most recent .ini in a BMS config dir.
    Used to get radio presets from the pilot profile when SharedMem is active.
    Returns True if radio data was loaded.
    """
    global mission_data
    if not config_dir or not os.path.isdir(config_dir):
        return False
    try:
        candidates = glob.glob(os.path.join(config_dir, "*.ini"))
        if not candidates:
            return False
        best = max(candidates, key=os.path.getmtime)
        with open(best, encoding=app_info.INI_ENCODING) as f:
            raw = f.read()
        cfg = configparser.RawConfigParser()
        cfg.optionxform = str  # type: ignore[assignment]
        cfg.read_string(raw)
        radio = _parse_radio_section(cfg)
        comms = _parse_comms_section(cfg)
        if radio.get("uhf") or radio.get("vhf"):
            mission_data = dict(mission_data)
            mission_data["radio"] = radio
            mission_data["comms"] = comms
            logger.info(f"Radio presets loaded from {os.path.basename(best)} "
                        f"({len(radio.get('uhf',[]))} UHF, {len(radio.get('vhf',[]))} VHF)")
            return True
    except Exception as e:
        logger.debug(f"load_radio_from_dir: {e}")
    return False


def parse_ini_content(text: str) -> dict:
    """Parse .ini text content and return mission_data dict (does not set global)."""
    cfg = configparser.RawConfigParser()
    cfg.optionxform = str  # type: ignore[assignment]
    cfg.read_string(text)
    result = _parse_stpt_section(cfg)
    result["radio"] = _parse_radio_section(cfg)
    result["comms"] = _parse_comms_section(cfg)
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  UPDATE FROM SHARED MEMORY
# ═══════════════════════════════════════════════════════════════════════════

def update_from_shm(route: list, threats: list) -> None:
    """
    Update mission_data from SharedMem NavPoints (primary source).
    Only updates if data actually changed (avoids UI flicker).
    """
    global mission_data, _shm_mission_hash
    h = f"{len(route)}:{len(threats)}"
    if route:
        h += f":{route[0]['lat']:.4f},{route[-1]['lat']:.4f}"
    if h == _shm_mission_hash:
        return
    _shm_mission_hash = h
    new_data = dict(mission_data)
    new_data["route"] = route
    new_data["threats"] = threats
    # Preserve INI type-code airfields if available (more precise than SHM guess)
    existing_af = mission_data.get("airfields", {})
    if route and len(route) >= 2 and not existing_af.get("_typed"):
        new_data["airfields"] = {
            "dep": {"lat": route[0]["lat"], "lon": route[0]["lon"]},
            "arr": {"lat": route[-1]["lat"], "lon": route[-1]["lon"]},
        }
    # radio/comms keys are preserved by dict copy
    mission_data = new_data
    logger.info(f"SHM steerpoints: {len(route)} WP, {len(threats)} PPT "
                f"(theater: {get_theater_name()})")


# ═══════════════════════════════════════════════════════════════════════════
#  UPLOAD (called from route handler)
# ═══════════════════════════════════════════════════════════════════════════

def set_from_upload(content: str, filename: str) -> dict:
    """Parse uploaded .ini content, set global mission_data. Returns result dict."""
    global mission_data, _ini_last_path, _ini_last_mtime
    result = parse_ini_content(content)
    mission_data = result
    _ini_last_path = filename
    _ini_last_mtime = time.time()
    route = result.get("route", [])
    threats = result.get("threats", [])
    logger.info(f"INI upload: {filename} — {len(route)} steerpoints, {len(threats)} PPT")
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  INI FILE FINDER + PARSER
# ═══════════════════════════════════════════════════════════════════════════

def find_latest_ini(extra_patterns: Optional[List[str]] = None) -> Tuple[str, float]:
    """
    Find the most recent .ini file containing [STPT].
    `extra_patterns` are prepended (e.g. from SharedMem BMS user dir or registry).
    """
    patterns = list(extra_patterns or []) + _registry_ini_patterns()

    files: List[str] = []
    for pat in patterns:
        try:
            files.extend(glob.glob(pat, recursive=True))
        except OSError as e:
            logger.debug(f"INI glob {pat}: {e}")
    if not files:
        return "", 0.0

    # Filter: only .ini files with [STPT]
    valid: List[str] = []
    for f in files:
        try:
            with open(f, 'r', encoding='latin-1', errors='replace') as fh:
                head = fh.read(8192)
            if '[STPT]' in head or '[Stpt]' in head:
                valid.append(f)
        except OSError as e:
            logger.debug(f"INI read {f}: {e}")
    if not valid:
        return "", 0.0

    # Most recent, deprioritize mission.ini
    def _sort_key(f: str) -> float:
        mtime = os.path.getmtime(f)
        name = os.path.basename(f).lower()
        penalty = -0.5 if name == 'mission.ini' else 0.0
        return mtime + penalty

    best = max(valid, key=_sort_key)
    return best, os.path.getmtime(best)


def parse_ini_file(path: str) -> dict:
    """Parse a .ini file and set global mission_data."""
    global mission_data
    try:
        with open(path, encoding=app_info.INI_ENCODING) as f:
            raw = f.read()
        cfg = configparser.RawConfigParser()
        cfg.optionxform = str  # type: ignore[assignment]
        cfg.read_string(raw)
        result = _parse_stpt_section(cfg)
        result["radio"] = _parse_radio_section(cfg)
        result["comms"] = _parse_comms_section(cfg)
        mission_data = result
        route = result.get("route", [])
        threats = result.get("threats", [])
        radio = result.get("radio", {})
        n_uhf = len(radio.get("uhf", []))
        n_vhf = len(radio.get("vhf", []))
        logger.info(f"INI loaded: {os.path.basename(path)} — "
                    f"{len(route)} steerpoints, {len(threats)} PPT, "
                    f"{n_uhf} UHF, {n_vhf} VHF presets")
        return result
    except Exception as e:
        logger.error(f"INI parse error: {e}")
        return {}


