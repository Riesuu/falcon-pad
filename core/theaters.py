# -*- coding: utf-8 -*-
"""
falcon_pad.theaters — Theater projection parameters and coordinate conversion.

Every BMS theater uses a custom Transverse Mercator projection.
This module stores the per-theater parameters and provides conversion functions
from BMS coordinates (North ft, East ft) to WGS-84 (lat, lon).

To add a new theater:
    1. Add a _reg() call with the correct TMERC parameters.
    2. Add a JSON file in data/airports/<theater_name_lowercase>.json.
    3. The theater name must match (case-insensitive) what BMS exposes
       in StringData ThrName (StringIdentifier 13).

Copyright (C) 2026  Riesu — GNU GPL v3
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
#  THEATER PARAMETERS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class TheaterParams:
    """TMERC projection parameters for a single BMS theater."""
    name: str
    lon0: float          # central meridian (degrees)
    k0:   float          # scale factor on central meridian
    FE:   float          # false easting  (metres)
    FN:   float          # false northing (metres)
    bbox: Tuple[float, float, float, float]   # (lat_min, lat_max, lon_min, lon_max)


# ── Theater registry ─────────────────────────────────────────────────────
THEATER_DB: Dict[str, TheaterParams] = {}


def _reg(name: str, lon0: float, k0: float, FE: float, FN: float,
         bbox: Tuple[float, float, float, float]) -> None:
    THEATER_DB[name.lower()] = TheaterParams(name, lon0, k0, FE, FN, bbox)


# Sources: BMS terrain header files + community documentation
# NOTE: FN values are theater-specific offsets; extracted from terrain .tdf/.hdr
#       If you have a theater not listed, check its terrain header for the
#       correct TMERC parameters and add an entry here.
_reg("Korea KTO", lon0=127.5,  k0=0.9996, FE=512000.0, FN=-3749290.0,
     bbox=(33.76, 42.94, 121.22, 133.78))
_reg("Balkans",   lon0=16.287, k0=0.9996, FE=512000.0, FN=-4118700.0,
     bbox=(35.0, 50.0, 12.0,  32.0))
_reg("Israel",    lon0=34.959, k0=0.9996, FE=512000.0, FN=-3028500.0,
     bbox=(27.0, 37.0, 29.0,  42.0))
_reg("Aegean",    lon0=24.0,   k0=0.9996, FE=512000.0, FN=0.0,
     bbox=(33.0, 43.0, 18.0,  32.0))
_reg("Hellas",    lon0=24.903, k0=0.9996, FE=512000.0, FN=-3694000.0,
     bbox=(30.0, 44.0, 18.0,  33.0))
_reg("Iberia",    lon0=-4.0,   k0=0.9996, FE=512000.0, FN=0.0,
     bbox=(34.0, 45.0, -12.0,  5.0))
_reg("Nordic",    lon0=18.0,   k0=0.9996, FE=512000.0, FN=0.0,
     bbox=(54.0, 72.0, 4.0,   36.0))


# ═══════════════════════════════════════════════════════════════════════════
#  ACTIVE THEATER STATE
# ═══════════════════════════════════════════════════════════════════════════

_active_theater: TheaterParams = THEATER_DB["korea kto"]  # default before BMS loads
_active_theater_name: str = "Korea KTO"
_theater_detected: bool = False   # True once BMS has explicitly set a theater
_theater_lock = threading.Lock()


def get_theater() -> TheaterParams:
    """Return the currently active theater (never None; defaults to Korea KTO)."""
    with _theater_lock:
        return _active_theater


def get_theater_name() -> str:
    """Return display name of the active theater."""
    with _theater_lock:
        return _active_theater_name


def is_theater_detected() -> bool:
    """Return True if BMS has explicitly detected/set a theater via SHM."""
    with _theater_lock:
        return _theater_detected


def set_active_theater(name: str) -> bool:
    """
    Update active theater from a theater name string.
    Returns True if the theater actually *changed* (triggers re-init).
    """
    global _active_theater, _active_theater_name, _theater_detected
    raw = name.strip()
    key = raw.lower()

    with _theater_lock:
        _theater_detected = True

        # 1) Direct match
        if key in THEATER_DB:
            if _active_theater_name.lower() != key:
                _active_theater = THEATER_DB[key]
                _active_theater_name = raw
                logger.info(f"THEATER set: {_active_theater_name}  "
                            f"(lon0={_active_theater.lon0}° bbox={_active_theater.bbox})")
                return True
            return False

        # 2) Fuzzy substring match (e.g. "Korea 1.1" → "korea kto")
        for db_key, params in THEATER_DB.items():
            if db_key in key or key in db_key:
                if _active_theater_name.lower() != db_key:
                    _active_theater = params
                    _active_theater_name = raw
                    logger.info(f"THEATER set (fuzzy): '{raw}' → {db_key}  "
                                f"(lon0={params.lon0}° bbox={params.bbox})")
                    return True
                return False

    logger.warning(f"THEATER unknown: '{raw}' — keeping {_active_theater_name}")
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  TMERC REVERSE PROJECTION
# ═══════════════════════════════════════════════════════════════════════════

# WGS-84 ellipsoid constants
_WGS84_A  = 6378137.0            # semi-major axis (m)
_WGS84_E2 = 0.00669437999014     # first eccentricity squared
_FT_TO_M  = 0.3048


def _tmerc_to_latlon(north_ft: float, east_ft: float,
                     tp: TheaterParams) -> Tuple[float, float]:
    """Convert BMS coordinates (North ft, East ft) → WGS-84 (lat°, lon°)."""
    a = _WGS84_A
    e2 = _WGS84_E2
    lon0 = math.radians(tp.lon0)
    k0 = tp.k0
    FE = tp.FE
    FN = tp.FN

    E_m = east_ft * _FT_TO_M
    N_m = north_ft * _FT_TO_M

    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    M1 = (N_m - FN) / k0
    mu1 = M1 / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))

    phi1 = (mu1
            + (3 * e1 / 2 - 27 * e1**3 / 32)      * math.sin(2 * mu1)
            + (21 * e1**2 / 16 - 55 * e1**4 / 32)  * math.sin(4 * mu1)
            + (151 * e1**3 / 96)                     * math.sin(6 * mu1))

    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    tan_phi1 = math.tan(phi1)

    N1r = a / math.sqrt(1 - e2 * sin_phi1**2)
    T1 = tan_phi1**2
    C1 = e2 * cos_phi1**2 / (1 - e2)
    R1 = a * (1 - e2) / (1 - e2 * sin_phi1**2)**1.5
    D = (E_m - FE) / (N1r * k0)

    lat = phi1 - (N1r * tan_phi1 / R1) * (
        D**2 / 2 - (5 + 3*T1 + 10*C1 - 4*C1**2 - 9*e2) * D**4 / 24
    )
    lon = lon0 + (D - (1 + 2*T1 + C1) * D**3 / 6) / cos_phi1

    return math.degrees(lat), math.degrees(lon)


def bms_to_latlon(north_ft: float, east_ft: float) -> Tuple[float, float]:
    """Convert BMS coords → WGS-84 using the *active* theater projection."""
    return _tmerc_to_latlon(north_ft, east_ft, _active_theater)


def bms_to_latlon_theater(north_ft: float, east_ft: float,
                          tp: TheaterParams) -> Tuple[float, float]:
    """Convert BMS coords → WGS-84 using an *explicit* theater projection."""
    return _tmerc_to_latlon(north_ft, east_ft, tp)


def detect_theater_from_coords(north_ft: float, east_ft: float) -> bool:
    """Single-point wrapper — see detect_theater_from_coords_multi."""
    return detect_theater_from_coords_multi([(north_ft, east_ft)])


def detect_theater_from_coords_multi(points: List[Tuple[float, float]]) -> bool:
    """
    Try every theater against all provided (north_ft, east_ft) points.
    Score = (bbox_hits, -sum_of_distances_from_center).
    Pick the theater with most hits; break ties by choosing the one whose
    projected points cluster closest to the bbox center (tighter fit).
    Returns True if the active theater changed.
    """
    best_key: Optional[str] = None
    best_hits = 0
    best_dist = float("inf")

    for key, tp in THEATER_DB.items():
        hits = 0
        total_dist = 0.0
        c_lat = (tp.bbox[0] + tp.bbox[1]) / 2
        c_lon = (tp.bbox[2] + tp.bbox[3]) / 2
        for north_ft, east_ft in points:
            try:
                lat, lon = _tmerc_to_latlon(north_ft, east_ft, tp)
                bb = tp.bbox
                if bb[0] <= lat <= bb[1] and bb[2] <= lon <= bb[3]:
                    hits += 1
                    total_dist += math.sqrt((lat - c_lat) ** 2 + (lon - c_lon) ** 2)
            except Exception:
                continue
        if hits > best_hits or (hits == best_hits and hits > 0 and total_dist < best_dist):
            best_hits = hits
            best_dist = total_dist
            best_key = key

    if best_key and best_hits >= 2:
        return set_active_theater(THEATER_DB[best_key].name)
    if best_key and best_hits == 1:
        logger.warning(f"detect_theater_from_coords_multi: only 1 hit for '{best_key}', keeping current theater")
    else:
        logger.warning("detect_theater_from_coords_multi: no theater matched")
    return False


def in_theater_bbox(lat: float, lon: float) -> bool:
    """True if (lat, lon) falls within the active theater's bounding box."""
    bb = _active_theater.bbox
    return bb[0] <= lat <= bb[1] and bb[2] <= lon <= bb[3]


