# -*- coding: utf-8 -*-
"""Tests — radar.py : DrawingData contact reading."""
import math
import struct

import pytest

import radar


def _fake_safe_read(blobs: dict):
    """Return a mock safe_read that serves pre-built memory blobs."""
    def _reader(addr, size):
        for base_addr, data in blobs.items():
            if base_addr <= addr < base_addr + len(data):
                off = addr - base_addr
                chunk = data[off:off + size]
                return chunk if len(chunk) == size else None
        return None
    return _reader


def _build_entity(lat_deg, lon_deg, alt_ft=10000, etype=1, camp=1,
                  heading_deg=90, speed=450.0, callsign=b"VPR1"):
    """Build a 40-byte OSBEntity struct.
    Layout: <fffiiif = lat_r(f), lon_r(f), z(f), etype(i), camp(i), heading_raw(i), speed(f)
    Then 8 bytes callsign label.  Total = 28 + 4 (pad?) ... actually 7 fields * 4 = 28 + 8 label = 36.
    But ENTITY_SIZE=40, so 4 bytes padding.
    """
    lat_r = math.radians(lat_deg)
    lon_r = math.radians(lon_deg)
    hdg_raw = int(math.radians(heading_deg) * 1000)  # stored as int
    data = struct.pack("<fffiiif", lat_r, lon_r, float(alt_ft * 100),
                       int(etype), int(camp), hdg_raw, float(speed))
    # data is 28 bytes; label starts at offset 32 in the 40-byte entity
    pad = b"\x00" * (32 - len(data))
    label = callsign[:8].ljust(8, b"\x00")
    return data + pad + label


class TestReset:
    def test_reset_sets_none(self):
        radar._candidates = (123, 456)
        radar.reset()
        assert radar._candidates is None


class TestGetContacts:
    def test_no_ptr1_returns_empty(self):
        assert radar.get_contacts({}, 0) == []

    def test_no_candidates_found(self, monkeypatch):
        """When scan finds nothing, should return empty and set _candidates to False."""
        radar.reset()
        monkeypatch.setattr("radar.safe_read", _fake_safe_read({}))
        result = radar.get_contacts({"FalconSharedMemoryArea": 0x1000}, 0x1000)
        assert result == []
        assert radar._candidates is False

    def test_candidates_false_returns_empty(self, monkeypatch):
        """Once _candidates is False (scan failed), should return [] without re-scanning."""
        radar._candidates = False
        monkeypatch.setattr("radar.safe_read", _fake_safe_read({}))
        result = radar.get_contacts({"FalconSharedMemoryArea": 0x1000}, 0x1000)
        assert result == []

    def test_decode_valid_entity(self, monkeypatch):
        """Given a valid DrawingData blob, should decode contacts."""
        # Build memory: nb=1 (int32) + 1 entity
        entity = _build_entity(37.0, 127.0, alt_ft=250, camp=2, callsign=b"VIPER1")
        nb_bytes = struct.pack("<i", 1)
        blob = nb_bytes + entity

        base = 0x10000
        offset = 0x2BD0
        radar._candidates = (base, offset)

        monkeypatch.setattr("radar.safe_read", _fake_safe_read({base + offset: blob}))
        result = radar.get_contacts({"FalconSharedMemoryArea": base}, base, ptr2=0)
        assert len(result) == 1
        c = result[0]
        assert abs(c["lat"] - 37.0) < 0.01
        assert abs(c["lon"] - 127.0) < 0.01
        assert c["camp"] == 2
        assert "VIPER" in c["callsign"] or len(c["callsign"]) > 0

    def test_skip_zero_coords(self, monkeypatch):
        """Entities with lat=0, lon=0 should be skipped."""
        entity = _build_entity(0.0, 0.0)
        nb_bytes = struct.pack("<i", 1)
        blob = nb_bytes + entity

        base = 0x10000
        offset = 0x100
        radar._candidates = (base, offset)
        monkeypatch.setattr("radar.safe_read", _fake_safe_read({base + offset: blob}))
        assert radar.get_contacts({"X": base}, base) == []

    def test_skip_invalid_camp(self, monkeypatch):
        """Entities with camp not in 1-4 should be skipped."""
        entity = _build_entity(37.0, 127.0, camp=0)
        nb_bytes = struct.pack("<i", 1)
        blob = nb_bytes + entity

        base = 0x10000
        offset = 0x100
        radar._candidates = (base, offset)
        monkeypatch.setattr("radar.safe_read", _fake_safe_read({base + offset: blob}))
        assert radar.get_contacts({"X": base}, base) == []

    def test_skip_ownship_proximity(self, monkeypatch):
        """Entities very close to ownship should be excluded."""
        entity = _build_entity(37.0, 127.0, camp=1)
        nb_bytes = struct.pack("<i", 1)
        blob = nb_bytes + entity

        base = 0x10000
        offset = 0x100
        radar._candidates = (base, offset)
        monkeypatch.setattr("radar.safe_read", _fake_safe_read({base + offset: blob}))
        result = radar.get_contacts({"X": base}, base,
                                    own_lat=37.0, own_lon=127.0)
        assert result == []

    def test_nb_out_of_range(self, monkeypatch):
        """nb > ENTITY_MAX should return empty."""
        blob = struct.pack("<i", 999)
        base = 0x10000
        offset = 0x100
        radar._candidates = (base, offset)
        monkeypatch.setattr("radar.safe_read", _fake_safe_read({base + offset: blob}))
        assert radar.get_contacts({"X": base}, base) == []

    def test_ent_names_lookup(self):
        assert radar._ENT_NAMES[1] == "F-16"
        assert radar._ENT_NAMES.get(999) is None
