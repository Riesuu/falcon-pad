# -*- coding: utf-8 -*-
"""
falcon_pad.sharedmem — BMS Shared Memory access for Windows.

Provides safe memory reading via ReadProcessMemory (no segfault risk)
and the BMSSharedMemory class that maps all known BMS shared memory areas.

Public API:
    safe_read(addr, size) → bytes | None
    safe_float(addr) → float | None
    safe_int32(addr) → int | None
    BMSSharedMemory  — .connected, .ptr1, .ptr2, .shm_ptrs, .get_position()

Copyright (C) 2024  Riesu — GNU GPL v3
"""

from __future__ import annotations

import ctypes
import logging
import struct
from typing import Dict, Optional

from theaters import bms_to_latlon, in_theater_bbox

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
#  FD OFFSETS (FlightData.h SDK BMS 4.38)
# ═══════════════════════════════════════════════════════════════════════════

# FlightData ("FalconSharedMemoryArea")
FD_X             = 0x000   # float, North ft
FD_Y             = 0x004   # float, East ft
FD_Z             = 0x008   # float, Down ft (negative = up)
FD_KIAS          = 0x034   # float, knots
FD_CURRENT_TIME  = 0x0A4   # int32, seconds since midnight (0–86400)
FD_CURRENT_HDG   = 0x0BC   # float, true heading degrees 0–360

# FlightData2 ("FalconSharedMemoryArea2")
FD2_AAUZ          = 0x014   # float, baro altitude ft
FD2_PILOTS_ONLINE = 0x260   # uint8, pilot count in MP
FD2_LAT           = 0x408   # float, latitude WGS-84 degrees
FD2_LON           = 0x40C   # float, longitude WGS-84 degrees
FD2_BULLSEYE_X    = 0x4B0   # float, bullseye North ft (BMS coords)
FD2_BULLSEYE_Y    = 0x4B4   # float, bullseye East ft  (BMS coords)
FD2_STRING_AREA_TIME = 0x4CC  # uint32, last StringData change timestamp


# ═══════════════════════════════════════════════════════════════════════════
#  SAFE MEMORY READER (ReadProcessMemory — never segfaults)
# ═══════════════════════════════════════════════════════════════════════════

_k32  = None
_rpm  = None
_hproc = None


def _init_safe_mem() -> None:
    """Initialize the ReadProcessMemory function pointers."""
    global _k32, _rpm, _hproc
    try:
        _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _rpm = _k32.ReadProcessMemory
        _rpm.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_size_t,
                         ctypes.POINTER(ctypes.c_size_t)]
        _rpm.restype = ctypes.c_bool
        _hproc = _k32.GetCurrentProcess()
        logger.info(f"SafeMemReader OK — hproc={_hproc}")
    except Exception as e:
        logger.error(f"SafeMemReader init FAILED: {e}")


def safe_read(addr: int, size: int) -> Optional[bytes]:
    """Read `size` bytes from shared memory at `addr`. Returns None on failure."""
    if _rpm is None or addr is None or addr == 0:
        return None
    try:
        buf = (ctypes.c_char * size)()
        read = ctypes.c_size_t(0)
        ok = _rpm(_hproc, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
        return bytes(buf) if ok and read.value == size else None
    except Exception as e:
        logger.debug(f"safe_read(0x{addr:X}, {size}): {e}")
        return None


def safe_float(addr: int) -> Optional[float]:
    """Read a little-endian float from shared memory."""
    b = safe_read(addr, 4)
    return struct.unpack('<f', b)[0] if b else None


def safe_int32(addr: int) -> Optional[int]:
    """Read a little-endian int32 from shared memory."""
    b = safe_read(addr, 4)
    return struct.unpack('<i', b)[0] if b else None


# ═══════════════════════════════════════════════════════════════════════════
#  BMS SHARED MEMORY CLASS
# ═══════════════════════════════════════════════════════════════════════════

# All known BMS 4.x shared memory area names
_SHM_NAMES = [
    "FalconSharedMemoryArea",
    "FalconSharedMemoryArea2",
    "FalconSharedMemoryArea3",
    "FalconSharedMemoryAreaString",
    "FalconSharedOSBMemoryArea",
    "FalconSharedIntellivibeMemoryArea",
    "FalconSharedDrawingMemoryArea",
    "FalconSharedCallsignMemoryArea",
    "FalconSharedTrafficMemoryArea",
]


class BMSSharedMemory:
    """
    Opens and reads BMS shared memory areas.

    Attributes:
        connected  — True if FalconSharedMemoryArea and Area2 are mapped
        ptr1       — pointer to FalconSharedMemoryArea (FlightData)
        ptr2       — pointer to FalconSharedMemoryArea2 (FlightData2)
        shm_ptrs   — dict {name: pointer} for all mapped areas
    """

    def __init__(self) -> None:
        self.ptr1: Optional[int] = None
        self.ptr2: Optional[int] = None
        self.shm_ptrs: Dict[str, int] = {}
        self.connected: bool = False
        self._connect()

    def _connect(self) -> None:
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            OpenMap = k32.OpenFileMappingW
            OpenMap.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
            OpenMap.restype = ctypes.c_void_p
            MapView = k32.MapViewOfFile
            MapView.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
            MapView.restype = ctypes.c_void_p

            FILE_MAP_READ = 0x0004
            self.shm_ptrs = {}
            for name in _SHM_NAMES:
                h = OpenMap(FILE_MAP_READ, False, name)
                if h:
                    p = MapView(h, FILE_MAP_READ, 0, 0, 0)
                    if p:
                        self.shm_ptrs[name] = p
                        logger.debug(f"  SHM {name} = 0x{p:X}")

            self.ptr1 = self.shm_ptrs.get("FalconSharedMemoryArea")
            self.ptr2 = self.shm_ptrs.get("FalconSharedMemoryArea2")

            if self.ptr1 and self.ptr2:
                self.connected = True
                logger.info(f"SHM connected: {len(self.shm_ptrs)} areas mapped")
                _init_safe_mem()
            else:
                self.shm_ptrs = {}
                self.ptr1 = self.ptr2 = None
                self.connected = False
                logger.debug("BMS not detected — retry in 5s")
        except Exception as e:
            self.shm_ptrs = {}
            self.ptr1 = self.ptr2 = None
            self.connected = False
            logger.error(f"Shared Memory error: {e}", exc_info=True)

    def try_reconnect(self) -> bool:
        if not self.connected:
            self._connect()
        return self.connected

    def get_position(self) -> Optional[Dict]:
        """Read ownship position, heading, altitude, speed, bullseye, etc."""
        if self.ptr1 is None or self.ptr2 is None:
            return None
        hdg = safe_float(self.ptr1 + FD_CURRENT_HDG)
        kias = safe_float(self.ptr1 + FD_KIAS)
        z = safe_float(self.ptr1 + FD_Z)
        lat = safe_float(self.ptr2 + FD2_LAT)
        lon = safe_float(self.ptr2 + FD2_LON)
        if None in (hdg, kias, z, lat, lon):
            logger.warning("get_position: safe_read failed")
            return None

        hdg_f = hdg % 360.0
        kias_f = kias
        z_f = z
        lat_f = lat
        lon_f = lon
        alt = abs(z_f)

        # BMS time (seconds since midnight)
        bms_time: Optional[int] = None
        raw_t = safe_read(self.ptr1 + FD_CURRENT_TIME, 4)
        if raw_t:
            try:
                bms_time = int(struct.unpack('<i', raw_t)[0])
                if bms_time < 0 or bms_time > 86400:
                    bms_time = None
            except (struct.error, ValueError):
                bms_time = None

        # Bullseye (BMS North/East ft → WGS-84)
        bull_lat: Optional[float] = None
        bull_lon: Optional[float] = None
        raw_bx = safe_read(self.ptr2 + FD2_BULLSEYE_X, 4)
        raw_by = safe_read(self.ptr2 + FD2_BULLSEYE_Y, 4)
        if raw_bx and raw_by:
            try:
                bx = struct.unpack('<f', raw_bx)[0]
                by = struct.unpack('<f', raw_by)[0]
                if abs(bx) > 10 and abs(by) > 10:
                    _bl, _bn = bms_to_latlon(bx, by)
                    bull_lat = float(_bl)
                    bull_lon = float(_bn)
                    if not in_theater_bbox(bull_lat, bull_lon):
                        bull_lat = bull_lon = None
            except (struct.error, ValueError, TypeError):
                pass  # bullseye data not yet available

        # Pilot count (solo vs MP)
        pilots_online: int = 1
        raw_po = safe_read(self.ptr2 + FD2_PILOTS_ONLINE, 1)
        if raw_po:
            try:
                pilots_online = max(1, int(struct.unpack('<B', raw_po)[0]))
            except (struct.error, ValueError):
                pilots_online = 1

        logger.debug(f"lat={lat_f:.4f} lon={lon_f:.4f} hdg={hdg_f:.1f} "
                     f"alt={alt:.0f}ft kias={kias_f:.0f}kt bms_t={bms_time} "
                     f"pilots={pilots_online}")

        if (-90 <= lat_f <= 90 and -180 <= lon_f <= 180
                and not (lat_f == 0.0 and lon_f == 0.0)):
            return {
                "lat": lat_f, "lon": lon_f,
                "heading": round(hdg_f, 1),
                "altitude": round(alt),
                "kias": round(kias_f),
                "bms_time": bms_time,
                "pilots_online": pilots_online,
                "bull_lat": round(bull_lat, 5) if bull_lat is not None else None,
                "bull_lon": round(bull_lon, 5) if bull_lon is not None else None,
                "connected": True,
            }
        return None
