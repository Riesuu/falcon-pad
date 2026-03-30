# -*- coding: utf-8 -*-
"""
falcon_pad.mission — BMS mission data: INI parsing, watcher, state management.

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
    ini_watcher_loop()        — async loop (call from lifespan)

Copyright (C) 2024  Riesu — GNU GPL v3
"""

from __future__ import annotations

import asyncio
import configparser
import glob
import logging
import os
import time
from typing import List, Optional, Tuple

import math

from theaters import bms_to_latlon, in_theater_bbox, get_theater_name

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
        base = r"SOFTWARE\WOW6432Node\Benchmark Sims"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(root, i)
                    i += 1
                    if not subkey_name.lower().startswith("falcon bms"):
                        continue
                    with winreg.OpenKey(root, subkey_name) as sk:
                        install_dir, _ = winreg.QueryValueEx(sk, "InstallDir")
                    cfg = os.path.join(install_dir, "User", "Config")
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
                    range_m = int(r_ft * 0.3048)
                    range_nm = max(1, round(r_ft / 6076.12))
                except (ValueError, IndexError):
                    range_m = 27800
                    range_nm = 15
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
        af: dict = {}
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


def match_airfields_to_airports(airfields: dict, airports: list,
                                max_nm: float = 5.0) -> dict:
    """
    Match airfield positions (from INI type codes) to known airports.
    Returns dict with dep/arr/alt keys → airport ICAO or None.
    """
    def _dist_nm(lat1, lon1, lat2, lon2):
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat/2)**2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon/2)**2)
        return 3440.065 * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    def _find_nearest(pos):
        if not pos or not airports:
            return None
        best_icao, best_d = None, max_nm
        for ap in airports:
            d = _dist_nm(pos["lat"], pos["lon"], ap["lat"], ap["lon"])
            if d < best_d:
                best_d = d
                best_icao = ap["icao"]
        return best_icao

    result = {}
    for role in ("dep", "arr", "alt"):
        pos = airfields.get(role)
        result[role] = _find_nearest(pos) if pos else None
    return result


def parse_ini_content(text: str) -> dict:
    """Parse .ini text content and return mission_data dict (does not set global)."""
    cfg = configparser.RawConfigParser()
    cfg.optionxform = str  # type: ignore[assignment]
    cfg.read_string(text)
    return _parse_stpt_section(cfg)


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
    if threats:
        new_data["threats"] = threats
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
        with open(path, encoding="latin-1") as f:
            raw = f.read()
        cfg = configparser.RawConfigParser()
        cfg.optionxform = str  # type: ignore[assignment]
        cfg.read_string(raw)
        result = _parse_stpt_section(cfg)
        mission_data = result
        route = result.get("route", [])
        threats = result.get("threats", [])
        logger.info(f"INI loaded: {os.path.basename(path)} — "
                    f"{len(route)} steerpoints, {len(threats)} PPT")
        return result
    except Exception as e:
        logger.error(f"INI parse error: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════════
#  ASYNC WATCHER LOOP
# ═══════════════════════════════════════════════════════════════════════════

async def ini_watcher_loop(get_extra_patterns=None) -> None:
    """
    Async loop: watches for new/changed .ini files and auto-loads them.

    Args:
        get_extra_patterns: optional callable returning List[str] of extra
                            glob patterns (e.g. from SharedMem BMS user dir).
    """
    global _ini_last_path, _ini_last_mtime
    logger.info("INI watcher started — paths from registry + SHM")
    _first_scan = True

    while True:
        try:
            extra = get_extra_patterns() if get_extra_patterns else None
            path, mtime = find_latest_ini(extra)

            if _first_scan:
                _first_scan = False
                if path:
                    logger.info(f"INI watcher: found {path} "
                                f"(age={time.time() - mtime:.0f}s)")
                else:
                    logger.warning("INI watcher: no .ini found in search paths")

            if path and (path != _ini_last_path or mtime > _ini_last_mtime + 1):
                _ini_last_path = path
                _ini_last_mtime = mtime
                parse_ini_file(path)
        except Exception as e:
            logger.debug(f"INI watcher: {e}")
        await asyncio.sleep(3)
