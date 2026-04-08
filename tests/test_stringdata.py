# -*- coding: utf-8 -*-
"""Tests — stringdata.py : parsing NavPoints, extracteurs."""
import struct
import pytest

from core.stringdata import (
    read_all_strings,
    get_steerpoints, get_ppt_threats,
    get_dl_markpoints, get_mk_markpoints, get_hsd_lines,
    detect_theater, STRID_NAVPOINT, STRID_THR_NAME,
)
from tests.conftest import _encode_navpoint, _encode_strings_blob, make_reader


# ── Helpers ──────────────────────────────────────────────────────────────────

def _blob_with_navpoints(*navpoints: tuple) -> tuple:
    """
    navpoints = [(idx, typ, x, y, z, ge, pt_name, pt_range), ...]
    Retourne (blob, reader).
    """
    raw_strings = []
    for np in navpoints:
        raw_strings.append((STRID_NAVPOINT, _encode_navpoint(*np)))
    blob, _ = _encode_strings_blob(raw_strings)
    return blob, make_reader(blob)


def _read(blob, reader):
    return read_all_strings(0, reader)


# Coordonnées BMS valides en Corée
KOR_X = 1_145_000.0
KOR_Y = 1_550_000.0


# ── read_all_strings ─────────────────────────────────────────────────────────

class TestReadAllStrings:

    def test_empty_blob_returns_empty(self):
        result = read_all_strings(0, lambda a, s: None)
        assert result == {}

    def test_single_entry(self):
        blob, reader = _blob_with_navpoints((1, "WP", KOR_X, KOR_Y, 100.0, 0.0))
        strings = _read(blob, reader)
        assert STRID_NAVPOINT in strings
        assert len(strings[STRID_NAVPOINT]) == 1

    def test_multiple_entries_same_id(self):
        blob, reader = _blob_with_navpoints(
            (1, "WP", KOR_X, KOR_Y, 100.0, 0.0),
            (2, "WP", KOR_X + 1000, KOR_Y + 1000, 100.0, 0.0),
            (3, "MK", KOR_X + 2000, KOR_Y + 2000, 100.0, 0.0),
        )
        strings = _read(blob, reader)
        assert len(strings[STRID_NAVPOINT]) == 3

    def test_invalid_ptr_returns_empty(self):
        result = read_all_strings(None, lambda a, s: b"\x00" * s)
        assert result == {}


# ── get_steerpoints ──────────────────────────────────────────────────────────

class TestGetSteerpoints:

    def test_extracts_wp_only(self):
        blob, reader = _blob_with_navpoints(
            (1, "WP", KOR_X, KOR_Y, 100.0, 0.0),
            (2, "MK", KOR_X + 1000, KOR_Y, 100.0, 0.0),  # doit être ignoré
            (3, "WP", KOR_X + 2000, KOR_Y, 150.0, 0.0),
        )
        strings = _read(blob, reader)
        stpts = get_steerpoints(strings)
        assert len(stpts) == 2
        assert all(isinstance(s["lat"], float) for s in stpts)
        assert all(isinstance(s["lon"], float) for s in stpts)

    def test_sorted_by_index(self):
        blob, reader = _blob_with_navpoints(
            (3, "WP", KOR_X + 2000, KOR_Y, 100.0, 0.0),
            (1, "WP", KOR_X,        KOR_Y, 100.0, 0.0),
            (2, "WP", KOR_X + 1000, KOR_Y, 100.0, 0.0),
        )
        strings = _read(blob, reader)
        stpts = get_steerpoints(strings)
        assert [s["index"] for s in stpts] == [0, 1, 2]

    def test_zero_coords_rejected(self):
        blob, reader = _blob_with_navpoints(
            (1, "WP", 0.0, 0.0, 0.0, 0.0),   # invalide
            (2, "WP", KOR_X, KOR_Y, 0.0, 0.0),
        )
        strings = _read(blob, reader)
        stpts = get_steerpoints(strings)
        assert len(stpts) == 1

    def test_empty_returns_empty_list(self):
        stpts = get_steerpoints({})
        assert stpts == []


# ── get_mk_markpoints ────────────────────────────────────────────────────────

class TestGetMkMarkpoints:

    def test_extracts_mk_only(self):
        blob, reader = _blob_with_navpoints(
            (26, "MK", KOR_X, KOR_Y, 50.0, 0.0),
            (27, "MK", KOR_X + 1000, KOR_Y + 1000, 50.0, 0.0),
            (1,  "WP", KOR_X + 2000, KOR_Y, 100.0, 0.0),  # ignoré
        )
        strings = _read(blob, reader)
        marks = get_mk_markpoints(strings)
        assert len(marks) == 2
        assert marks[0]["label"].startswith("MK ")

    def test_label_format(self):
        blob, reader = _blob_with_navpoints(
            (28, "MK", KOR_X, KOR_Y, 0.0, 0.0),
        )
        strings = _read(blob, reader)
        marks = get_mk_markpoints(strings)
        assert marks[0]["label"] == "MK 28"

    def test_empty_returns_empty_list(self):
        assert get_mk_markpoints({}) == []


# ── get_ppt_threats ──────────────────────────────────────────────────────────

class TestGetPptThreats:

    def test_extracts_pt_with_range(self):
        blob, reader = _blob_with_navpoints(
            (56, "PT", KOR_X, KOR_Y, 0.0, 0.0, "SA-6", 30476.0),  # ~5 NM
        )
        strings = _read(blob, reader)
        ppts = get_ppt_threats(strings)
        assert len(ppts) == 1
        assert ppts[0]["name"] == "SA-6"
        assert ppts[0]["range_nm"] >= 1

    def test_default_range_when_zero(self):
        blob, reader = _blob_with_navpoints(
            (57, "PT", KOR_X, KOR_Y, 0.0, 0.0, "SA-2", 0.0),
        )
        strings = _read(blob, reader)
        ppts = get_ppt_threats(strings)
        assert ppts[0]["range_nm"] == 15  # valeur par défaut

    def test_wp_not_included(self):
        blob, reader = _blob_with_navpoints(
            (1, "WP", KOR_X, KOR_Y, 0.0, 0.0),
        )
        strings = _read(blob, reader)
        assert get_ppt_threats(strings) == []

    def test_agl_ft_ground_unit(self):
        """Un PT au sol (z == grnd_elev) doit avoir agl_ft == 0."""
        blob, reader = _blob_with_navpoints(
            (58, "PT", KOR_X, KOR_Y, 100.0, 100.0, "SA-8", 18288.0),  # z == grnd_elev
        )
        strings = _read(blob, reader)
        ppts = get_ppt_threats(strings)
        assert len(ppts) == 1
        assert ppts[0]["agl_ft"] == 0

    def test_agl_ft_airborne(self):
        """Un PT en altitude (z >> grnd_elev) doit avoir agl_ft > 0."""
        # z=200 en dizaines de pieds → alt=2000ft, grnd_elev=0 → agl=2000ft
        blob, reader = _blob_with_navpoints(
            (59, "PT", KOR_X, KOR_Y, 200.0, 0.0, "F-16", 0.0),
        )
        strings = _read(blob, reader)
        ppts = get_ppt_threats(strings)
        assert len(ppts) == 1
        assert ppts[0]["agl_ft"] == 2000


# ── get_dl_markpoints ────────────────────────────────────────────────────────

class TestGetDlMarkpoints:

    def test_extracts_dl_only(self):
        blob, reader = _blob_with_navpoints(
            (71, "DL", KOR_X, KOR_Y, 0.0, 0.0),
            (1,  "WP", KOR_X + 1000, KOR_Y, 0.0, 0.0),
        )
        strings = _read(blob, reader)
        marks = get_dl_markpoints(strings)
        assert len(marks) == 1
        assert marks[0]["label"].startswith("DL ")

    def test_excludes_ownship(self):
        blob, reader = _blob_with_navpoints(
            (71, "DL", KOR_X, KOR_Y, 0.0, 0.0),
        )
        strings = _read(blob, reader)
        lat, lon = 37.09, 127.03  # proche de KOR_X/KOR_Y
        # Calcul approx de la lat/lon pour KOR_X/KOR_Y
        from core.theaters import bms_to_latlon
        own_lat, own_lon = bms_to_latlon(KOR_X, KOR_Y)
        marks = get_dl_markpoints(strings, own_lat=own_lat, own_lon=own_lon)
        assert len(marks) == 0  # exclu car c'est ownship


# ── get_hsd_lines ────────────────────────────────────────────────────────────

class TestGetHsdLines:

    def test_extracts_l1_l2_lines(self):
        blob, reader = _blob_with_navpoints(
            (31, "L1", KOR_X,        KOR_Y,        0.0, 0.0),
            (32, "L1", KOR_X + 5000, KOR_Y,        0.0, 0.0),
            (33, "L1", KOR_X + 10000,KOR_Y,        0.0, 0.0),
            (34, "L2", KOR_X,        KOR_Y + 5000, 0.0, 0.0),
            (35, "L2", KOR_X + 5000, KOR_Y + 5000, 0.0, 0.0),
        )
        strings = _read(blob, reader)
        lines = get_hsd_lines(strings)
        line_names = [l["line"] for l in lines]
        assert "L1" in line_names
        assert "L2" in line_names

    def test_single_point_not_returned(self):
        """Une ligne avec un seul point ne doit pas être retournée."""
        blob, reader = _blob_with_navpoints(
            (31, "L1", KOR_X, KOR_Y, 0.0, 0.0),  # seul point
        )
        strings = _read(blob, reader)
        lines = get_hsd_lines(strings)
        assert len(lines) == 0

    def test_line_has_color(self):
        blob, reader = _blob_with_navpoints(
            (31, "L1", KOR_X,        KOR_Y, 0.0, 0.0),
            (32, "L1", KOR_X + 5000, KOR_Y, 0.0, 0.0),
        )
        strings = _read(blob, reader)
        lines = get_hsd_lines(strings)
        assert lines[0]["color"].startswith("#")

    def test_line_has_points_list(self):
        blob, reader = _blob_with_navpoints(
            (31, "L3", KOR_X,        KOR_Y, 0.0, 0.0),
            (32, "L3", KOR_X + 5000, KOR_Y, 0.0, 0.0),
            (33, "L3", KOR_X + 10000,KOR_Y, 0.0, 0.0),
        )
        strings = _read(blob, reader)
        lines = get_hsd_lines(strings)
        assert len(lines[0]["points"]) == 3
        assert all("lat" in p and "lon" in p for p in lines[0]["points"])

    def test_all_four_lines(self):
        navpoints = []
        for i, typ in enumerate(["L1","L2","L3","L4"]):
            navpoints.append((31+i*2,   typ, KOR_X + i*5000, KOR_Y, 0.0, 0.0))
            navpoints.append((31+i*2+1, typ, KOR_X + i*5000 + 3000, KOR_Y, 0.0, 0.0))
        blob, reader = _blob_with_navpoints(*navpoints)
        strings = _read(blob, reader)
        lines = get_hsd_lines(strings)
        assert len(lines) == 4

    def test_empty_returns_empty(self):
        assert get_hsd_lines({}) == []


# ── detect_theater ───────────────────────────────────────────────────────────

class TestDetectTheater:

    def test_detects_from_thr_name(self):
        blob, reader = _encode_strings_blob([(STRID_THR_NAME, "Balkans")])
        strings = read_all_strings(0, make_reader(blob))
        from core import stringdata as sd
        sd._last_thr_name = ""  # reset cache
        changed = detect_theater(strings)
        assert changed is True
        from core.theaters import get_theater_name
        assert get_theater_name() == "Balkans"
        # Cleanup
        from core.theaters import set_active_theater
        set_active_theater("Korea KTO")
        sd._last_thr_name = ""

    def test_no_change_if_same_theater(self):
        blob, reader = _encode_strings_blob([(STRID_THR_NAME, "Korea KTO")])
        strings = read_all_strings(0, make_reader(blob))
        from core import stringdata as sd
        sd._last_thr_name = "Korea KTO"
        changed = detect_theater(strings)
        assert changed is False
