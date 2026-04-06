# -*- coding: utf-8 -*-
"""Tests — theaters.py : extended coverage (detection, projection, state)."""
import math

import pytest

from core.theaters import (
    THEATER_DB, TheaterParams,
    bms_to_latlon, bms_to_latlon_theater,
    detect_theater_from_coords, detect_theater_from_coords_multi,
    get_theater, get_theater_name, in_theater_bbox,
    is_theater_detected, set_active_theater,
)


@pytest.fixture(autouse=True)
def _reset_theater():
    """Ensure Korea is active before each test."""
    set_active_theater("Korea")
    yield
    set_active_theater("Korea")


# ── get_theater / is_theater_detected ───────────────────────────────────────

class TestGetTheater:
    def test_returns_theater_params(self):
        tp = get_theater()
        assert isinstance(tp, TheaterParams)
        assert tp.name == "Korea"

    def test_has_required_fields(self):
        tp = get_theater()
        assert hasattr(tp, "lon0")
        assert hasattr(tp, "k0")
        assert hasattr(tp, "FE")
        assert hasattr(tp, "FN")
        assert hasattr(tp, "bbox")

    def test_is_theater_detected(self):
        # set_active_theater sets _theater_detected = True
        assert is_theater_detected() is True


# ── bms_to_latlon_theater ──────────────────────────────────────────────────

class TestBmsToLatlonTheater:
    def test_korea_explicit(self):
        tp = THEATER_DB["korea"]
        lat, lon = bms_to_latlon_theater(1_145_000.0, 1_550_000.0, tp)
        assert 36.5 < lat < 37.5
        assert 126.5 < lon < 127.5

    def test_balkans_explicit(self):
        tp = THEATER_DB["balkans"]
        # Balkans FN=0, so need ~14M ft north for ~42°N
        lat, lon = bms_to_latlon_theater(15_200_000.0, 1_640_000.0, tp)
        assert tp.bbox[0] <= lat <= tp.bbox[1]
        assert tp.bbox[2] <= lon <= tp.bbox[3]

    def test_israel_explicit(self):
        tp = THEATER_DB["israel"]
        lat, lon = bms_to_latlon_theater(500_000.0, 500_000.0, tp)
        assert tp.bbox[0] <= lat <= tp.bbox[1]


# ── detect_theater_from_coords_multi ────────────────────────────────────────

class TestDetectTheater:
    def test_korea_coords_detect_korea(self):
        # Reset to Balkans first so we can detect a change
        set_active_theater("Balkans")
        pts = [(1_145_000.0, 1_550_000.0),
               (1_100_000.0, 1_500_000.0),
               (1_200_000.0, 1_600_000.0)]
        changed = detect_theater_from_coords_multi(pts)
        assert changed is True
        assert "korea" in get_theater_name().lower()

    def test_single_point_not_enough(self):
        """A single point hit should NOT change theater (requires >= 2)."""
        set_active_theater("Korea")
        tp_balkans = THEATER_DB["balkans"]
        # Craft a single point that lands in Balkans bbox
        lat_c = (tp_balkans.bbox[0] + tp_balkans.bbox[1]) / 2
        lon_c = (tp_balkans.bbox[2] + tp_balkans.bbox[3]) / 2
        # We can't easily reverse the projection, so use coords wrapper
        changed = detect_theater_from_coords_multi([(500_000.0, 500_000.0)])
        # With only 1 hit, should keep current theater
        assert get_theater_name() == "Korea"

    def test_no_match_returns_false(self):
        # Use absurd coords that won't project into any theater bbox
        changed = detect_theater_from_coords_multi([(999_999_999, 999_999_999)])
        assert changed is False

    def test_detect_single_point_wrapper(self):
        """detect_theater_from_coords is a wrapper for multi with 1 point."""
        # Should not crash
        result = detect_theater_from_coords(1_145_000.0, 1_550_000.0)
        assert isinstance(result, bool)

    def test_empty_points(self):
        changed = detect_theater_from_coords_multi([])
        assert changed is False


# ── in_theater_bbox per theater ─────────────────────────────────────────────

class TestInTheaterBbox:
    @pytest.mark.parametrize("theater,lat,lon", [
        ("Balkans", 42.0, 20.0),
        ("Israel",  31.0, 35.0),
        ("Aegean",  38.0, 24.0),
        ("Iberia",  40.0, -3.0),
        ("Nordic",  60.0, 18.0),
    ])
    def test_center_in_bbox(self, theater, lat, lon):
        set_active_theater(theater)
        assert in_theater_bbox(lat, lon) is True

    def test_out_of_bbox(self):
        set_active_theater("Korea")
        assert in_theater_bbox(0.0, 0.0) is False

    def test_bbox_edge_inclusive(self):
        set_active_theater("Korea")
        bb = get_theater().bbox
        assert in_theater_bbox(bb[0], bb[2]) is True  # min corner
        assert in_theater_bbox(bb[1], bb[3]) is True  # max corner


# ── All theaters have valid params ──────────────────────────────────────────

class TestTheaterDB:
    @pytest.mark.parametrize("key", list(THEATER_DB.keys()))
    def test_valid_bbox(self, key):
        tp = THEATER_DB[key]
        assert tp.bbox[0] < tp.bbox[1]  # lat_min < lat_max
        assert tp.bbox[2] < tp.bbox[3]  # lon_min < lon_max

    @pytest.mark.parametrize("key", list(THEATER_DB.keys()))
    def test_k0_near_one(self, key):
        tp = THEATER_DB[key]
        assert 0.99 < tp.k0 < 1.01

    @pytest.mark.parametrize("key", list(THEATER_DB.keys()))
    def test_lon0_in_range(self, key):
        tp = THEATER_DB[key]
        assert -180 <= tp.lon0 <= 180

    def test_korea_and_korea_kto_same_params(self):
        k = THEATER_DB["korea"]
        kto = THEATER_DB["korea kto"]
        assert k.lon0 == kto.lon0
        assert k.FN == kto.FN
