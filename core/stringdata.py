# -*- coding: utf-8 -*-
"""
falcon_pad.stringdata — Read FalconSharedMemoryAreaString for BMS 4.38.

This module provides:
  • Generic StringData blob reader  (read_all_strings)
  • Auto theater detection          (detect_theater)
  • NavPoint parser                 (get_steerpoints, get_dl_markpoints, get_ppt_threats)

NavPoint is StringIdentifier 33 (not 30!).  The format is documented in
FlightData.h SDK — each entry has mandatory NP: block and optional O1:/O2:/PT: blocks.

NavPoint types (two-char codes):
  WP = waypoint (steerpoints 1–25)     DL = datalink markpoint (IDM)
  MK = markpoint                        CB = campaign bullseye
  PT = preplanned threat                GM = ground marker
  PO = position marker                  L1–L4 = lines
  
Usage from falcon_pad.py:
    from falcon_pad.stringdata import read_all_strings, detect_theater, ...
    strings = read_all_strings(ptr_str, safe_read)
    detect_theater(strings)
    stpts = get_steerpoints(strings)
    dl_marks = get_dl_markpoints(strings, own_lat, own_lon)

Copyright (C) 2024  Riesu — GNU GPL v3
"""

from __future__ import annotations

import logging
import re
import struct
from typing import Callable, Dict, List, Optional, Tuple

import app_info
from core.theaters import (
    bms_to_latlon,
    in_theater_bbox,
    set_active_theater,
)

logger = logging.getLogger(__name__)

# Type alias for the safe memory reader function: (addr, size) → bytes | None
MemReader = Callable[[int, int], Optional[bytes]]


# ═══════════════════════════════════════════════════════════════════════════
#  STRING IDENTIFIERS (from FlightData.h → StringIdentifier enum)
# ═══════════════════════════════════════════════════════════════════════════
# Count carefully from the enum in FlightData.h:
#   BmsExe=0, KeyFile=1, BmsBasedir=2, BmsBinDirectory=3, BmsDataDirectory=4,
#   BmsUIArtDirectory=5, BmsUserDirectory=6, BmsAcmiDirectory=7,
#   BmsBriefingsDirectory=8, BmsConfigDirectory=9, BmsLogsDirectory=10,
#   BmsPatchDirectory=11, BmsPictureDirectory=12,
#   ThrName=13, ThrCampaigndir=14, ThrTerraindir=15, ThrArtdir=16,
#   ThrMoviedir=17, ThrUisounddir=18, ThrObjectdir=19, Thr3ddatadir=20,
#   ThrMisctexdir=21, ThrSounddir=22, ThrTacrefdir=23, ThrSplashdir=24,
#   ThrCockpitdir=25, ThrSimdatadir=26, ThrSubtitlesdir=27,
#   ThrTacrefpicsdir=28,
#   AcName=29, AcNCTR=30,                          ← VERSION 1 ends
#   ButtonsFile=31, CockpitFile=32,                 ← VERSION 2
#   NavPoint=33,                                    ← VERSION 3 ★
#   ThrTerrdatadir=34,                              ← VERSION 4
#   VoiceHelpers=35,                                ← VERSION 5

STRID_BMS_EXE          = 0
STRID_BMS_BASEDIR      = 2
STRID_BMS_USER_DIR     = 6
STRID_BMS_BRIEFINGS    = 8
STRID_BMS_CONFIG_DIR   = 9
STRID_THR_NAME       = 13
STRID_THR_CAMPAIGN   = 14
STRID_THR_TERRAIN    = 15
STRID_AC_NAME        = 29
STRID_NAVPOINT       = 33   # ★ Was incorrectly set to 30 (AcNCTR) in old code
STRID_VOICE_HELPERS  = 35


# ═══════════════════════════════════════════════════════════════════════════
#  LOW-LEVEL BLOB READER
# ═══════════════════════════════════════════════════════════════════════════

def read_all_strings(ptr_str: int, reader: MemReader) -> Dict[int, List[str]]:
    """
    Read FalconSharedMemoryAreaString and return all strings grouped by ID.

    Returns {strId: [str, str, ...], ...}.
    NavPoint (ID 33) will typically have one entry per navpoint.
    Most other IDs have a single entry.

    Returns {} if shared memory is inaccessible.

    Binary layout (from FlightData.h):
        uint32 VersionNum
        uint32 NoOfStrings
        uint32 dataSize
        for each string:
            uint32 strId
            uint32 strLength   (without \\0)
            char   strData[strLength + 1]   (with \\0 terminator)
    """
    if ptr_str is None:
        return {}

    # Read header: 3 × uint32 = 12 bytes
    hdr = reader(ptr_str, 12)
    if not hdr or len(hdr) < 12:
        return {}
    try:
        _ver, no_strings, data_size = struct.unpack_from('<III', hdr, 0)
    except (struct.error, ValueError):
        return {}
    if no_strings == 0 or no_strings > 500 or data_size > 4 * 1024 * 1024:
        return {}

    # Read entire data blob
    blob = reader(ptr_str + 12, data_size)
    if not blob or len(blob) < data_size:
        return {}

    result: Dict[int, List[str]] = {}
    off = 0
    for _ in range(no_strings):
        if off + 8 > len(blob):
            break
        try:
            str_id, str_len = struct.unpack_from('<II', blob, off)
            off += 8
            if off + str_len + 1 > len(blob):
                break
            text = blob[off:off + str_len].decode('utf-8', errors='replace')
            off += str_len + 1   # +1 for the \0 terminator
            result.setdefault(str_id, []).append(text)
        except (struct.error, UnicodeDecodeError):
            break

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  THEATER DETECTION
# ═══════════════════════════════════════════════════════════════════════════

_last_thr_name: str = ""

def detect_theater(strings: Dict[int, List[str]]) -> bool:
    """
    Detect and set the active theater from StringData ThrName (ID 13).
    Returns True if theater changed (callers may want to reload airports etc.).
    """
    global _last_thr_name
    entries = strings.get(STRID_THR_NAME, [])
    if not entries:
        return False
    thr_name = entries[0].strip()
    if not thr_name or thr_name == _last_thr_name:
        return False
    _last_thr_name = thr_name
    return set_active_theater(thr_name)


def get_bms_basedir(strings: Dict[int, List[str]]) -> Optional[str]:
    """Extract BMS base directory from StringData (ID 2)."""
    entries = strings.get(STRID_BMS_BASEDIR, [])
    return entries[0].strip() if entries else None


def get_bms_user_dir(strings: Dict[int, List[str]]) -> Optional[str]:
    """Extract BMS User directory from StringData (ID 6)."""
    entries = strings.get(STRID_BMS_USER_DIR, [])
    return entries[0].strip() if entries else None


def get_campaign_dir(strings: Dict[int, List[str]]) -> Optional[str]:
    """Extract active theater campaign directory from StringData (ID 14)."""
    entries = strings.get(STRID_THR_CAMPAIGN, [])
    return entries[0].strip() if entries else None


def get_bms_briefings_dir(strings: Dict[int, List[str]]) -> Optional[str]:
    """Extract BMS Briefings directory from StringData (ID 8)."""
    entries = strings.get(STRID_BMS_BRIEFINGS, [])
    return entries[0].strip() if entries else None


def get_aircraft_name(strings: Dict[int, List[str]]) -> Optional[str]:
    """Extract current aircraft name from StringData (ID 29)."""
    entries = strings.get(STRID_AC_NAME, [])
    return entries[0].strip() if entries else None


# ═══════════════════════════════════════════════════════════════════════════
#  NAVPOINT PARSER
# ═══════════════════════════════════════════════════════════════════════════

# Regex for the mandatory NP: block
_RE_NP = re.compile(
    r'NP:(\d+),([A-Z][A-Z0-9]),([^,]+),([^,]+),([^,]+),([^,;]+)'
)
# Regex for the optional PT: block (PPT threat info)
_RE_PT = re.compile(
    r'PT:"?([^"]*)"?,([^,]+),(\d+);'
)


def _parse_navpoint(raw: str) -> Optional[dict]:
    """
    Parse a single NavPoint string into a structured dict.

    Returns dict with keys:
        index, type, x, y, z, grnd_elev, lat, lon, alt_ft,
        ppt_name, ppt_range_ft   (only for PT type)
    or None if unparseable.

    NavPoint format (FlightData.h SDK):
        NP:<idx>,<type>,<x>,<y>,<z>,<grnd_elev>;
        [O1:<bearing>,<range>,<alt>;]
        [O2:<bearing>,<range>,<alt>;]
        [PT:<str_id>,<range>,<declutter>;]
    """
    m = _RE_NP.search(raw)
    if not m:
        return None
    try:
        idx = int(m.group(1))
        typ = m.group(2)
        x   = float(m.group(3))    # North ft (BMS sim coords)
        y   = float(m.group(4))    # East ft  (BMS sim coords)
        z   = float(m.group(5))    # altitude in tens of feet
        ge  = float(m.group(6))    # ground elevation in tens of feet
    except (ValueError, IndexError) as e:
        logger.debug(f"_parse_navpoint: {e} in {raw[:60]!r}")
        return None

    # Convert BMS coords → WGS-84
    if abs(x) < 10 and abs(y) < 10:
        return None   # zero/invalid position
    lat, lon = bms_to_latlon(x, y)
    if not in_theater_bbox(lat, lon):
        return None

    result: dict = {
        "index":     idx,
        "type":      typ,
        "x":         x,
        "y":         y,
        "z":         z,
        "grnd_elev": ge,
        "lat":       round(lat, 5),
        "lon":       round(lon, 5),
        "alt_ft":    round(abs(z) * 10),   # tens of feet → feet
    }

    # Parse optional PT: block (for PPT threats)
    mpt = _RE_PT.search(raw)
    if mpt:
        result["ppt_name"]     = mpt.group(1).strip()
        try:
            result["ppt_range_ft"] = float(mpt.group(2))
        except ValueError:
            result["ppt_range_ft"] = 0.0

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  HIGH-LEVEL EXTRACTORS
# ═══════════════════════════════════════════════════════════════════════════

def get_steerpoints(strings: Dict[int, List[str]]) -> List[dict]:
    """
    Extract steerpoints (WP type) from StringData NavPoints.
    Returns list sorted by index, each entry:
        {"lat": ..., "lon": ..., "alt": ..., "index": 0-based}

    This replaces INI-based STPT reading when BMS is in 3D.
    """
    entries = strings.get(STRID_NAVPOINT, [])
    if not entries:
        return []
    stpts: List[dict] = []
    for raw in entries:
        np = _parse_navpoint(raw)
        if np and np["type"] == "WP":
            stpts.append(np)
    # Sort by NavPoint index (1-based in BMS)
    stpts.sort(key=lambda s: s["index"])
    # Return clean dicts with 0-based index for frontend compat
    return [
        {"lat": s["lat"], "lon": s["lon"], "alt": s["alt_ft"], "index": i}
        for i, s in enumerate(stpts)
    ]


def get_bullseye(strings: Dict[int, List[str]]) -> Optional[dict]:
    """
    Extract campaign bullseye (CB type) from StringData NavPoints.
    Returns {"lat": ..., "lon": ...} or None.
    """
    entries = strings.get(STRID_NAVPOINT, [])
    for raw in entries:
        np = _parse_navpoint(raw)
        if np and np["type"] == "CB":
            return {"lat": np["lat"], "lon": np["lon"]}
    return None


def get_ppt_threats(strings: Dict[int, List[str]]) -> List[dict]:
    """
    Extract PPT (preplanned threats) from StringData NavPoints.
    Returns list sorted by index, each entry:
        {"lat":..., "lon":..., "name":..., "range_nm":..., "range_m":...,
         "num":..., "index": 0-based, "agl_ft": altitude above ground in ft}
    agl_ft > 0 means the unit is airborne (aircraft); ≈0 means ground unit.
    """
    entries = strings.get(STRID_NAVPOINT, [])
    if not entries:
        return []
    ppts: List[dict] = []
    for raw in entries:
        np = _parse_navpoint(raw)
        if not np or np["type"] != "PT":
            continue
        range_ft = np.get("ppt_range_ft", 0.0)
        range_m = int(range_ft * app_info.FT_TO_M) if range_ft > 0 else app_info.PPT_DEFAULT_RANGE_M
        range_nm = max(1, round(range_ft / app_info.FT_TO_NM_DIVISOR)) if range_ft > 0 else app_info.PPT_DEFAULT_RANGE_NM
        # z and grnd_elev are in tens of feet in BMS; AGL = (z - grnd_elev) * 10
        agl_ft = max(0, round((np["z"] - np["grnd_elev"]) * 10))
        ppts.append({
            "lat":      np["lat"],
            "lon":      np["lon"],
            "name":     np.get("ppt_name", ""),
            "range_nm": range_nm,
            "range_m":  range_m,
            "num":      np["index"],
            "index":    len(ppts),
            "agl_ft":   agl_ft,
        })
    ppts.sort(key=lambda p: p["num"])
    for i, p in enumerate(ppts):
        p["index"] = i
    return ppts


def get_dl_markpoints(strings: Dict[int, List[str]],
                      own_lat: Optional[float] = None,
                      own_lon: Optional[float] = None) -> List[dict]:
    """
    Extract IDM datalink markpoints (DL type) from StringData NavPoints.

    NOTE: DL NavPoints are NOT L16 PPLI contacts or FCR tracks.
    They are static position markpoints shared between aircraft via IDM
    (Improved Data Modem). They should be displayed as map markers,
    not as moving aircraft contacts.

    Real-time aircraft contacts come from TRTT (trtt.py), not StringData.

    Returns list of markpoints:
        {"lat":..., "lon":..., "alt":..., "index":..., "label":"DL xx"}
    """
    entries = strings.get(STRID_NAVPOINT, [])
    if not entries:
        return []
    result: List[dict] = []
    for raw in entries:
        np = _parse_navpoint(raw)
        if not np or np["type"] != "DL":
            continue
        # Exclude ownship position
        if own_lat is not None and own_lon is not None:
            if abs(np["lat"] - own_lat) < 0.002 and abs(np["lon"] - own_lon) < 0.002:
                continue
        result.append({
            "lat":   np["lat"],
            "lon":   np["lon"],
            "alt":   np["alt_ft"],
            "index": len(result),
            "label": f"DL {np['index']}",
        })
    return result


def get_mk_markpoints(strings: Dict[int, List[str]]) -> List[dict]:
    """
    Extract pilot-created MARK points (MK type, STPTs 26-30) from StringData NavPoints.
    These are markpoints set by the pilot via TMS-Right-Long on the HSD.

    Returns list of markpoints:
        {"lat":..., "lon":..., "alt":..., "index":..., "label":"MK xx"}
    """
    entries = strings.get(STRID_NAVPOINT, [])
    if not entries:
        return []
    result: List[dict] = []
    for raw in entries:
        np = _parse_navpoint(raw)
        if not np or np["type"] != "MK":
            continue
        result.append({
            "lat":   np["lat"],
            "lon":   np["lon"],
            "alt":   np["alt_ft"],
            "index": len(result),
            "label": f"MK {np['index']}",
        })
    return result


def get_hsd_lines(strings: Dict[int, List[str]]) -> List[dict]:
    """
    Extract HSD lines (L1–L4 types, STPTs 31–54) from StringData NavPoints.

    BMS HSD supports 4 lines (L1, L2, L3, L4), each with up to 6 points.
    Points are grouped by line type and returned as polylines.

    Returns list of lines:
        [
          {"line": "L1", "color": "#4ade80", "points": [{"lat":..., "lon":..., "alt":...}, ...]},
          {"line": "L2", "color": "#60a5fa", "points": [...]},
          ...
        ]
    Only lines with at least 2 points are returned (a single point is not a line).
    """
    # Distinct color per line — matches BMS HSD conventions
    LINE_COLORS = {"L1": "#4ade80", "L2": "#60a5fa", "L3": "#f59e0b", "L4": "#f87171"}
    LINE_TYPES  = set(LINE_COLORS.keys())

    entries = strings.get(STRID_NAVPOINT, [])
    if not entries:
        return []

    # Group points by line type
    buckets: Dict[str, list] = {k: [] for k in LINE_TYPES}
    for raw in entries:
        np = _parse_navpoint(raw)
        if not np or np["type"] not in LINE_TYPES:
            continue
        buckets[np["type"]].append({
            "lat": np["lat"],
            "lon": np["lon"],
            "alt": np["alt_ft"],
        })

    result = []
    for ltype in ["L1", "L2", "L3", "L4"]:
        pts = buckets[ltype]
        if len(pts) >= 2:
            result.append({
                "line":   ltype,
                "color":  LINE_COLORS[ltype],
                "points": pts,
            })

    logger.debug(f"HSD lines: {[r['line']+':'+str(len(r['points']))+'pts' for r in result]}")
    return result


def get_all_navpoints(strings: Dict[int, List[str]]) -> List[dict]:
    """
    Parse ALL navpoints (any type) for debugging or advanced use.
    """
    entries = strings.get(STRID_NAVPOINT, [])
    result = []
    for raw in entries:
        np = _parse_navpoint(raw)
        if np:
            result.append(np)
    return result
