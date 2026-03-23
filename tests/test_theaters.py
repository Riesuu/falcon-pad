# -*- coding: utf-8 -*-
"""Tests for theaters.py — projection, bbox, airports, theater switching."""

import pytest


class TestTheaterDB:
    def test_theater_db_not_empty(self):
        from theaters import THEATER_DB
        assert len(THEATER_DB) >= 7

    def test_korea_registered(self):
        from theaters import THEATER_DB
        tp = THEATER_DB["korea"]
        assert tp.lon0 == 127.5
        assert tp.k0 == 0.9996

    def test_all_theaters_have_valid_bbox(self):
        from theaters import THEATER_DB
        for key, tp in THEATER_DB.items():
            lat_min, lat_max, lon_min, lon_max = tp.bbox
            assert lat_min < lat_max, f"{key}: lat_min >= lat_max"
            assert lon_min < lon_max, f"{key}: lon_min >= lon_max"
            assert -90 <= lat_min <= 90, f"{key}: lat_min out of range"
            assert -180 <= lon_min <= 180, f"{key}: lon_min out of range"


class TestProjection:
    def test_bms_to_latlon_korea_osan(self):
        """Known coords: Osan AB ~37.09N 127.03E."""
        from theaters import bms_to_latlon
        lat, lon = bms_to_latlon(1168000.0, 1544000.0)
        assert 37.0 < lat < 37.2, f"Expected ~37.09, got {lat}"
        assert 126.9 < lon < 127.1, f"Expected ~127.03, got {lon}"

    def test_bms_to_latlon_zero_input(self):
        from theaters import bms_to_latlon
        lat, lon = bms_to_latlon(0.0, 0.0)
        assert isinstance(lat, float)
        assert isinstance(lon, float)

    def test_in_theater_bbox(self):
        from theaters import in_theater_bbox
        assert in_theater_bbox(37.0, 127.0) is True
        assert in_theater_bbox(0.0, 0.0) is False
        assert in_theater_bbox(60.0, 127.0) is False

    def test_projection_changes_with_theater(self):
        """Same BMS coords should give different lat/lon for different theaters."""
        from theaters import bms_to_latlon, set_active_theater
        lat_kr, lon_kr = bms_to_latlon(1168000.0, 1544000.0)
        set_active_theater("Balkans")
        lat_bk, lon_bk = bms_to_latlon(1168000.0, 1544000.0)
        assert abs(lat_kr - lat_bk) > 1.0, "Projection didn't change"
        assert abs(lon_kr - lon_bk) > 1.0, "Projection didn't change"


class TestTheaterSwitching:
    def test_set_active_theater_direct(self):
        from theaters import set_active_theater, get_theater_name
        changed = set_active_theater("Balkans")
        assert changed is True
        assert get_theater_name() == "Balkans"
        # Same theater again → no change
        assert set_active_theater("Balkans") is False

    def test_set_active_theater_fuzzy(self):
        from theaters import set_active_theater, get_theater
        set_active_theater("Balkans")  # start from non-Korea
        changed = set_active_theater("Korea KTO 1.0")
        assert changed is True
        assert get_theater().lon0 == 127.5

    def test_set_active_theater_unknown(self):
        from theaters import set_active_theater, get_theater_name
        old_name = get_theater_name()
        changed = set_active_theater("MarsTheater2099")
        assert changed is False
        assert get_theater_name() == old_name


class TestAirports:
    def test_get_airports_korea(self):
        from theaters import get_airports
        airports = get_airports()
        assert len(airports) >= 40
        osan = [a for a in airports if a["icao"] == "RKSO"]
        assert len(osan) == 1
        assert osan[0]["name"] == "Osan AB"
        assert osan[0]["tacan"] == "94X"
        assert isinstance(osan[0]["ils"], list)

    def test_get_airports_empty_theater(self):
        import theaters
        old = theaters._active_theater_name
        theaters._active_theater_name = "UnknownTheater"
        airports = theaters.get_airports()
        theaters._active_theater_name = old
        assert airports == []
