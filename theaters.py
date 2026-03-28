# -*- coding: utf-8 -*-
"""
falcon_pad.theaters — Theater projection parameters, airports, and coordinate conversion.

Every BMS theater uses a custom Transverse Mercator projection.
This module stores the per-theater parameters and provides conversion functions
from BMS coordinates (North ft, East ft) to WGS-84 (lat, lon).

To add a new theater:
    1. Add a _reg_theater() call with the correct TMERC parameters.
    2. Add an entry in THEATER_AIRPORTS if you have airport data.
    3. The theater name must match (case-insensitive) what BMS exposes
       in StringData ThrName (StringIdentifier 13).

Copyright (C) 2024  Riesu — GNU GPL v3
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
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
_reg("Korea",     lon0=127.5,  k0=0.9996, FE=512000.0, FN=-3749290.0,
     bbox=(30.0, 45.0, 118.0, 135.0))
_reg("Korea KTO", lon0=127.5,  k0=0.9996, FE=512000.0, FN=-3749290.0,
     bbox=(30.0, 45.0, 118.0, 135.0))
_reg("Balkans",   lon0=20.0,   k0=0.9996, FE=500000.0, FN=0.0,
     bbox=(35.0, 50.0, 12.0,  32.0))
_reg("Israel",    lon0=35.0,   k0=0.9996, FE=500000.0, FN=-3113000.0,
     bbox=(27.0, 37.0, 29.0,  42.0))
_reg("Aegean",    lon0=24.0,   k0=0.9996, FE=500000.0, FN=0.0,
     bbox=(33.0, 43.0, 18.0,  32.0))
_reg("Iberia",    lon0=-4.0,   k0=0.9996, FE=500000.0, FN=0.0,
     bbox=(34.0, 45.0, -12.0,  5.0))
_reg("Nordic",    lon0=18.0,   k0=0.9996, FE=500000.0, FN=0.0,
     bbox=(54.0, 72.0, 4.0,   36.0))


# ═══════════════════════════════════════════════════════════════════════════
#  ACTIVE THEATER STATE
# ═══════════════════════════════════════════════════════════════════════════

_active_theater: TheaterParams = THEATER_DB["korea"]
_active_theater_name: str = "Korea"


def get_theater() -> TheaterParams:
    """Return the currently active theater (never None; defaults to Korea)."""
    return _active_theater


def get_theater_name() -> str:
    """Return display name of the active theater."""
    return _active_theater_name


def set_active_theater(name: str) -> bool:
    """
    Update active theater from a theater name string.
    Returns True if the theater actually *changed* (triggers re-init).
    """
    global _active_theater, _active_theater_name
    raw = name.strip()
    key = raw.lower()

    # 1) Direct match
    if key in THEATER_DB:
        if _active_theater_name.lower() != key:
            _active_theater = THEATER_DB[key]
            _active_theater_name = raw
            logger.info(f"THEATER set: {_active_theater_name}  "
                        f"(lon0={_active_theater.lon0}° bbox={_active_theater.bbox})")
            return True
        return False

    # 2) Fuzzy substring match (e.g. "Korea 1.1" → "korea")
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

    if best_key:
        return set_active_theater(THEATER_DB[best_key].name)
    logger.warning("detect_theater_from_coords_multi: no theater matched")
    return False


def in_theater_bbox(lat: float, lon: float) -> bool:
    """True if (lat, lon) falls within the active theater's bounding box."""
    bb = _active_theater.bbox
    return bb[0] <= lat <= bb[1] and bb[2] <= lon <= bb[3]


# ═══════════════════════════════════════════════════════════════════════════
#  AIRPORT DATABASE (per-theater)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(slots=True)
class Airport:
    """Single airfield entry."""
    icao: str
    lat:  float
    lon:  float
    name: str
    tacan: str = ""
    freq:  str = ""
    ils:  List[dict] = field(default_factory=list)


# Key = theater name (lowercase), Value = list of Airport
THEATER_AIRPORTS: Dict[str, List[Airport]] = {}

def _ap(theater: str, icao: str, lat: float, lon: float, name: str,
        tacan: str = "", freq: str = "", ils: Optional[List[dict]] = None) -> None:
    key = theater.lower()
    if key not in THEATER_AIRPORTS:
        THEATER_AIRPORTS[key] = []
    THEATER_AIRPORTS[key].append(
        Airport(icao=icao, lat=lat, lon=lon, name=name,
                tacan=tacan, freq=freq, ils=ils or [])
    )


# ── Korea / Korea KTO ────────────────────────────────────────────────────
_KR = "korea"
# South Korea
_ap(_KR, "RKJK", 35.906389, 126.615833, "Gunsan AB",    "75X",  "122.1", [{"rwy":"18","freq":"109.1","crs":"183"},{"rwy":"36","freq":"110.1","crs":"003"}])
_ap(_KR, "RKSO", 37.090556, 127.030000, "Osan AB",      "94X",  "126.2", [{"rwy":"36L","freq":"108.7","crs":"355"},{"rwy":"18R","freq":"110.3","crs":"175"}])
_ap(_KR, "RKSG", 36.961111, 127.030556, "Pyeongtaek",   "19X",  "126.2", [{"rwy":"18","freq":"108.3","crs":"182"},{"rwy":"36","freq":"109.9","crs":"002"}])
_ap(_KR, "RKSW", 37.239167, 127.005556, "Suwon AB",     "22X",  "126.2", [{"rwy":"09","freq":"108.1","crs":"092"},{"rwy":"27","freq":"109.3","crs":"272"}])
_ap(_KR, "RKTN", 35.894167, 128.658611, "Daegu AB",     "125X", "126.2", [{"rwy":"32","freq":"108.3","crs":"323"},{"rwy":"14","freq":"109.5","crs":"143"}])
_ap(_KR, "RKTU", 36.716944, 127.499167, "Cheongju AB",  "42X",  "126.2", [{"rwy":"06","freq":"108.7","crs":"059"},{"rwy":"24","freq":"110.7","crs":"239"}])
_ap(_KR, "RKJJ", 35.126389, 126.808889, "Gwangju AB",   "91X",  "123.3", [{"rwy":"24","freq":"108.9","crs":"241"},{"rwy":"06","freq":"109.9","crs":"061"}])
_ap(_KR, "RKTH", 35.987778, 129.419444, "Pohang AB",    "72X",  "123.3", [{"rwy":"09","freq":"108.3","crs":"093"},{"rwy":"27","freq":"109.7","crs":"273"}])
_ap(_KR, "RKSM", 37.444722, 127.113889, "Seoul AB",     "46X",  "126.2", [{"rwy":"09","freq":"110.5","crs":"085"},{"rwy":"27","freq":"108.5","crs":"265"}])
_ap(_KR, "RKTP", 36.703889, 126.485278, "Seosan AB",    "52X",  "126.2", [{"rwy":"03","freq":"108.5","crs":"032"},{"rwy":"21","freq":"109.1","crs":"212"}])
_ap(_KR, "RKSI", 37.469444, 126.450556, "Incheon",      "85X",  "119.1", [{"rwy":"33L","freq":"110.1","crs":"328"},{"rwy":"15R","freq":"109.5","crs":"148"}])
_ap(_KR, "RKSS", 37.558333, 126.790833, "Gimpo",        "83X",  "118.1", [{"rwy":"14L","freq":"108.9","crs":"142"},{"rwy":"32R","freq":"110.3","crs":"322"}])
_ap(_KR, "RKPK", 35.179444, 128.938056, "Gimhae/Busan", "117X", "118.8", [{"rwy":"36L","freq":"108.5","crs":"358"},{"rwy":"18R","freq":"109.9","crs":"178"}])
_ap(_KR, "RKNY", 38.061111, 128.669167, "Yangyang",     "43X",  "126.2", [{"rwy":"33","freq":"108.3","crs":"326"},{"rwy":"15","freq":"109.1","crs":"146"}])
_ap(_KR, "RKNN", 37.753611, 128.943889, "Gangneung",    "056X", "126.2", [{"rwy":"06","freq":"108.7","crs":"063"},{"rwy":"24","freq":"110.5","crs":"243"}])
_ap(_KR, "RKNW", 37.438056, 127.960556, "Wonju",        "60Y",  "126.2", [{"rwy":"03","freq":"108.9","crs":"033"},{"rwy":"21","freq":"109.3","crs":"213"}])
_ap(_KR, "RKND", 38.142778, 128.598611, "Sokcho",       "43X",  "126.2", [{"rwy":"07","freq":"108.5","crs":"073"},{"rwy":"25","freq":"109.3","crs":"253"}])
_ap(_KR, "RKPS", 35.088333, 128.070833, "Sacheon",      "37X",  "126.2", [{"rwy":"04","freq":"108.3","crs":"037"},{"rwy":"22","freq":"109.5","crs":"217"}])
_ap(_KR, "RKJB", 34.991389, 126.382778, "Muan",         "65X",  "118.1", [{"rwy":"01","freq":"108.5","crs":"011"},{"rwy":"19","freq":"110.1","crs":"191"}])
_ap(_KR, "RKTI", 36.635000, 127.498611, "Jungwon",      "05X",  "126.2", [{"rwy":"27","freq":"108.7","crs":"276"},{"rwy":"09","freq":"109.7","crs":"096"}])
_ap(_KR, "RKTY", 36.633333, 128.350000, "Yecheon",      "026X", "126.2", [{"rwy":"18","freq":"108.9","crs":"184"},{"rwy":"36","freq":"110.3","crs":"004"}])
# North Korea
_ap(_KR, "ZKPY",    39.224167, 125.670278, "Pyongyang",  "51X",  "126.2", [{"rwy":"17","freq":"108.3","crs":"173"},{"rwy":"35","freq":"109.5","crs":"353"}])
_ap(_KR, "ZKWS",    39.166667, 127.486111, "Wonsan",     "54X",  "126.2", [{"rwy":"18","freq":"108.7","crs":"183"},{"rwy":"36","freq":"110.1","crs":"003"}])
_ap(_KR, "ZKUJ",    40.050000, 124.533333, "Uiju",       "55X",  "126.2", [{"rwy":"05","freq":"108.9","crs":"049"},{"rwy":"23","freq":"109.7","crs":"229"}])
_ap(_KR, "ZKTS",    39.283333, 127.366667, "Toksan",     "53X",  "126.2", [{"rwy":"05","freq":"108.5","crs":"052"},{"rwy":"23","freq":"109.3","crs":"232"}])
_ap(_KR, "KP-0011", 39.066667, 125.600000, "Mirim",      "59X",  "126.2", [{"rwy":"17","freq":"108.3","crs":"172"},{"rwy":"35","freq":"109.5","crs":"352"}])
_ap(_KR, "KP-0018", 39.800000, 125.900000, "Kaechon",    "",     "126.2", [{"rwy":"18","freq":"108.7","crs":"184"},{"rwy":"36","freq":"110.1","crs":"004"}])
_ap(_KR, "KP-0020", 38.666667, 125.783333, "Hwangju",    "",     "126.2", [{"rwy":"18","freq":"108.9","crs":"181"},{"rwy":"36","freq":"109.7","crs":"001"}])
_ap(_KR, "KP-0021", 39.433333, 125.933333, "Sunchon",    "",     "126.2", [{"rwy":"18","freq":"108.3","crs":"183"},{"rwy":"36","freq":"110.3","crs":"003"}])
_ap(_KR, "KP-0023", 39.816667, 124.916667, "Onchon",     "",     "126.2", [{"rwy":"18","freq":"108.5","crs":"182"},{"rwy":"36","freq":"109.1","crs":"002"}])
_ap(_KR, "KP-0030", 39.900000, 124.933333, "Panghyon",   "",     "126.2", [{"rwy":"17","freq":"108.7","crs":"174"},{"rwy":"35","freq":"109.9","crs":"354"}])
_ap(_KR, "KP-0032", 41.383333, 129.450000, "Orang",      "",     "126.2", [])
_ap(_KR, "KP-0008", 39.745833, 127.473333, "Sondok",     "",     "126.2", [{"rwy":"18","freq":"108.3","crs":"183"},{"rwy":"36","freq":"109.5","crs":"003"}])
_ap(_KR, "KP-0015", 38.816667, 126.400000, "Koksan",     "",     "126.2", [])
_ap(_KR, "KP-0019", 39.150000, 125.883333, "Hyon-Ni",    "",     "126.2", [])
_ap(_KR, "KP-0035", 38.683333, 125.366667, "Hwangsuwon", "",     "126.2", [])
_ap(_KR, "KP-0039", 38.700000, 125.550000, "Kwail",      "",     "126.2", [])
_ap(_KR, "KP-0050", 38.033333, 125.366667, "Ongjin",     "",     "126.2", [])
_ap(_KR, "KP-0053", 41.566667, 126.266667, "Manpo",      "",     "126.2", [])
_ap(_KR, "KP-0059", 40.316667, 128.633333, "Iwon",       "",     "126.2", [])
_ap(_KR, "KP-0006", 39.783333, 124.716667, "Taechon",    "",     "126.2", [])
_ap(_KR, "KP-0005", 38.250000, 126.650000, "Taetan",     "",     "126.2", [{"rwy":"03","freq":"108.5","crs":"032"},{"rwy":"21","freq":"109.1","crs":"212"}])
_ap(_KR, "KP-0029", 42.066667, 128.400000, "Samjiyon",   "",     "126.2", [])
# Japan (on Korea theater map)
_ap(_KR, "RJOI", 34.143889, 132.235556, "Iwakuni",   "126X", "126.2", [{"rwy":"07","freq":"108.3","crs":"072"},{"rwy":"25","freq":"110.7","crs":"252"}])
_ap(_KR, "RJOA", 34.436111, 132.919444, "Hiroshima", "024X", "118.7", [{"rwy":"10","freq":"109.1","crs":"100"},{"rwy":"28","freq":"110.3","crs":"280"}])
_ap(_KR, "RJOW", 34.676111, 131.789722, "Iwami",     "57X",  "122.8", [{"rwy":"17","freq":"108.9","crs":"168"},{"rwy":"35","freq":"109.5","crs":"348"}])
_ap(_KR, "RJDC", 33.930000, 131.278611, "Yamaguchi",  "",     "122.8", [{"rwy":"07","freq":"108.3","crs":"072"},{"rwy":"25","freq":"109.5","crs":"252"}])
# Alias for "korea kto"
THEATER_AIRPORTS["korea kto"] = THEATER_AIRPORTS[_KR]

# TODO: Add airports for Balkans, Israel, Aegean, Iberia, Nordic
# _ap("balkans", "LYBE", 44.8184, 20.3091, "Belgrade", ...)


def get_airports() -> List[dict]:
    """
    Return airport list for the active theater as JSON-serializable dicts.
    Returns [] for theaters with no airport data.
    """
    key = _active_theater_name.lower()
    airports = THEATER_AIRPORTS.get(key, [])
    # Fuzzy fallback
    if not airports:
        for db_key, ap_list in THEATER_AIRPORTS.items():
            if db_key in key or key in db_key:
                airports = ap_list
                break
    return [
        {
            "icao": ap.icao, "name": ap.name,
            "lat": ap.lat, "lon": ap.lon,
            "tacan": ap.tacan, "freq": ap.freq, "ils": ap.ils,
        }
        for ap in airports
    ]
