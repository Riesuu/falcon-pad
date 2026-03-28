# -*- coding: utf-8 -*-
"""
falcon_pad.radar — BMS DrawingData (OSBEntity) radar/datalink contact reader.

Scans FalconSharedMemory areas for the DrawingData array (auto-discovers offset)
and decodes OSBEntity structs into contact dicts.

Public API:
    get_contacts(shm_ptrs, ptr1, own_lat, own_lon, ptr2) → list
    reset()   — force re-scan of DrawingData offset (call after BMS reconnect)

Copyright (C) 2024  Riesu — GNU GPL v3
"""

from __future__ import annotations

import logging
import math
import struct
from typing import Dict, Optional

from sharedmem import safe_read

logger = logging.getLogger(__name__)

ENTITY_SIZE: int = 40
ENTITY_MAX:  int = 150

_ENT_NAMES: Dict[int, str] = {
    1: "F-16",  2: "F-15",  3: "F/A-18", 4: "A-10",  5: "F-117",
    6: "MiG-29",7: "Su-27", 8: "MiG-21", 9: "MiG-23",10: "Su-25",
    20:"SA-2",  21:"SA-3",  22:"SA-6",   23:"SA-8",  24:"SA-10", 25:"SA-11",
    30:"Helo",  40:"Transport",
}

_candidates = None   # (base, offset) | False | None (= not yet scanned)


def reset() -> None:
    """Force a new DrawingData scan on the next call to get_contacts()."""
    global _candidates
    _candidates = None


def _scan(shm_ptrs: dict, ptr1: int, ptr2: int) -> tuple:
    """Return (base, offset) of the DrawingData array, or (None, None)."""
    candidates = []
    offsets = [0x000, 0x100, 0x200, 0x300, 0x400, 0x500,
               0x600, 0x700, 0x800, 0x900, 0xA00, 0xB00,
               0xC00, 0xD00, 0xE00, 0xF00,
               0x1000, 0x1200, 0x1500, 0x1800, 0x1E00,
               0x2000, 0x2400, 0x2800, 0x2BD0]
    for name, ptr in shm_ptrs.items():
        if ptr:
            candidates += [(ptr, off, f"{name}+0x{off:X}") for off in offsets]
    for ptr, off, lbl in [(ptr1, 0x2BD0, "ptr1+0x2BD0"),
                          (ptr2, 0x000,  "ptr2+0x000"),
                          (ptr2, 0x100,  "ptr2+0x100"),
                          (ptr2, 0x200,  "ptr2+0x200")]:
        if ptr and (ptr, off, lbl) not in candidates:
            candidates.append((ptr, off, lbl))

    for base, off, label in candidates:
        if not base:
            continue
        b = safe_read(base + off, 4)
        if b is None:
            continue
        nb = struct.unpack("<i", b)[0]
        if not (1 <= nb <= 50):
            continue
        blob = safe_read(base + off + 4, 8)
        if blob:
            lr, lo = struct.unpack("<ff", blob)
            if 0.4 < abs(lr) < 1.0 and 2.0 < abs(lo) < 2.5:
                logger.info(
                    f"DrawingData found: {label} nb={nb} "
                    f"lat={math.degrees(lr):.2f} lon={math.degrees(lo):.2f}"
                )
                return base, off
    return None, None


def get_contacts(shm_ptrs: dict, ptr1: int,
                 own_lat: Optional[float] = None,
                 own_lon: Optional[float] = None,
                 ptr2: int = 0) -> list:
    """Read DrawingData and return a list of contact dicts."""
    global _candidates
    if not ptr1:
        return []

    if _candidates is None:
        logger.info("Scanning DrawingData...")
        base, off = _scan(shm_ptrs, ptr1, ptr2)
        _candidates = (base, off) if base else False
        if not base:
            logger.warning("DrawingData: offset not found — datalink disabled")

    if not _candidates:
        return []

    dd_base, dd_off = _candidates
    b = safe_read(dd_base + dd_off, 4)
    if b is None:
        logger.warning(f"DrawingData nb unreadable @ 0x{dd_base+dd_off:X} — resetting")
        _candidates = None
        return []

    nb_raw = struct.unpack("<i", b)[0]
    if nb_raw <= 0 or nb_raw > ENTITY_MAX:
        return []

    blob = safe_read(dd_base + dd_off + 4, nb_raw * ENTITY_SIZE)
    if blob is None:
        return []

    res = []
    for i in range(nb_raw):
        try:
            off = i * ENTITY_SIZE
            lat_r, lon_r, z, et, ca, hr, sp = struct.unpack_from("<fffiiif", blob, off)
            lb = blob[off+32:off+40].split(b"\x00")[0].decode("ascii", errors="replace").strip()
            if lat_r == 0.0 and lon_r == 0.0:
                continue
            if not 1 <= ca <= 4:
                continue
            lat = math.degrees(lat_r)
            lon = math.degrees(lon_r)
            if not (25 <= lat <= 50 and 110 <= lon <= 145):
                continue
            if own_lat and own_lon and abs(lat - own_lat) < 0.002 and abs(lon - own_lon) < 0.002:
                continue
            res.append({
                "lat":       round(lat, 5),
                "lon":       round(lon, 5),
                "alt":       round(abs(z) / 100) * 100,
                "camp":      int(ca),
                "type_name": _ENT_NAMES.get(int(et), f"T{et}"),
                "callsign":  lb,
                "heading":   round(math.degrees(hr) % 360, 1),
                "speed":     round(sp),
            })
        except Exception as ex:
            logger.debug(f"DrawingData[{i}]: {ex}")

    logger.debug(f"DrawingData: {len(res)}/{nb_raw} valid contacts")
    return res
