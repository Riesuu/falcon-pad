# -*- coding: utf-8 -*-
"""Tests for sharedmem.py — safe memory reading (non-Windows safe)."""

import sys
import pytest


class TestSafeRead:
    def test_null_addr_returns_none(self):
        from sharedmem import safe_read
        assert safe_read(0, 4) is None

    def test_safe_float_null(self):
        from sharedmem import safe_float
        assert safe_float(0) is None

    def test_safe_int32_null(self):
        from sharedmem import safe_int32
        assert safe_int32(0) is None


class TestOffsets:
    def test_fd_offsets_match_sdk(self):
        from sharedmem import FD_KIAS, FD_CURRENT_HDG, FD2_LAT, FD2_LON
        assert FD_KIAS == 0x034
        assert FD_CURRENT_HDG == 0x0BC
        assert FD2_LAT == 0x408
        assert FD2_LON == 0x40C

    def test_fd2_offsets(self):
        from sharedmem import FD2_BULLSEYE_X, FD2_BULLSEYE_Y, FD2_CURRENT_TIME
        assert FD2_BULLSEYE_X == 0x4B0
        assert FD2_BULLSEYE_Y == 0x4B4
        assert FD2_CURRENT_TIME == 0x02C


class TestBMSSharedMemory:
    @pytest.mark.skipif(sys.platform == "win32", reason="Windows has real SHM")
    def test_not_connected_on_linux(self):
        from sharedmem import BMSSharedMemory
        bms = BMSSharedMemory()
        assert bms.connected is False
        assert bms.ptr1 is None
        assert bms.ptr2 is None

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows has real SHM")
    def test_get_position_disconnected(self):
        from sharedmem import BMSSharedMemory
        bms = BMSSharedMemory()
        assert bms.get_position() is None
