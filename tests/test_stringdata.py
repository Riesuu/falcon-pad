# -*- coding: utf-8 -*-
"""Tests for stringdata.py — StringData reader, NavPoint parsing, theater detection."""

import pytest
from conftest import make_string_blob, fake_reader


class TestStringIDs:
    def test_strid_navpoint_is_33(self):
        from stringdata import STRID_NAVPOINT
        assert STRID_NAVPOINT == 33

    def test_strid_thr_name_is_13(self):
        from stringdata import STRID_THR_NAME
        assert STRID_THR_NAME == 13


class TestReadAllStrings:
    def test_empty_returns_empty(self):
        from stringdata import read_all_strings
        assert read_all_strings(None, lambda a, s: None) == {}

    def test_valid_blob(self):
        from stringdata import read_all_strings, STRID_THR_NAME
        blob = make_string_blob([(13, "Korea"), (29, "F-16C")])
        result = read_all_strings(0, fake_reader(blob))
        assert STRID_THR_NAME in result
        assert result[13] == ["Korea"]
        assert result[29] == ["F-16C"]

    def test_corrupt_header(self):
        from stringdata import read_all_strings
        result = read_all_strings(0, lambda a, s: b'\xff' * 4)
        assert result == {}

    def test_multiple_navpoints(self):
        """Multiple entries with same strId should accumulate in a list."""
        from stringdata import read_all_strings
        blob = make_string_blob([
            (33, "NP:1,WP,100,200,300,400;"),
            (33, "NP:2,WP,101,201,301,401;"),
        ])
        result = read_all_strings(0, fake_reader(blob))
        assert len(result.get(33, [])) == 2


class TestTheaterDetection:
    def test_detect_theater(self, reset_stringdata_cache):
        from stringdata import detect_theater
        from theaters import get_theater_name
        changed = detect_theater({13: ["Balkans"]})
        assert changed is True
        assert get_theater_name() == "Balkans"

    def test_detect_theater_no_thr_name(self):
        from stringdata import detect_theater
        assert detect_theater({29: ["F-16C"]}) is False

    def test_detect_same_theater_no_change(self, reset_stringdata_cache):
        from stringdata import detect_theater
        detect_theater({13: ["Korea"]})
        changed = detect_theater({13: ["Korea"]})
        assert changed is False


class TestNavPointParsing:
    def test_parse_wp(self):
        from stringdata import get_steerpoints
        strings = {33: ["NP:3,WP,1168000.0,1544000.0,-150.0,50.0;"]}
        stpts = get_steerpoints(strings)
        assert len(stpts) == 1
        assert stpts[0]["index"] == 0
        assert stpts[0]["alt"] == 1500
        assert 37.0 < stpts[0]["lat"] < 37.2

    def test_parse_dl(self):
        from stringdata import get_dl_markpoints
        strings = {33: ["NP:55,DL,1170000.0,1550000.0,-200.0,50.0;"]}
        marks = get_dl_markpoints(strings)
        assert len(marks) == 1
        assert marks[0]["label"] == "DL 55"
        assert "camp" not in marks[0]  # markpoints have no camp

    def test_dl_excludes_ownship(self):
        from stringdata import get_dl_markpoints
        from theaters import bms_to_latlon
        lat, lon = bms_to_latlon(1170000.0, 1550000.0)
        strings = {33: ["NP:55,DL,1170000.0,1550000.0,-200.0,50.0;"]}
        assert get_dl_markpoints(strings, own_lat=lat, own_lon=lon) == []

    def test_parse_ppt(self):
        from stringdata import get_ppt_threats
        strings = {33: ['NP:57,PT,1168000.0,1544000.0,-100.0,50.0;PT:"SA-2",50000.0,0;']}
        ppts = get_ppt_threats(strings)
        assert len(ppts) == 1
        assert ppts[0]["name"] == "SA-2"
        assert ppts[0]["range_nm"] == 8

    def test_invalid_type_ignored(self):
        from stringdata import get_steerpoints, get_dl_markpoints
        strings = {33: ["NP:10,CB,1168000.0,1544000.0,-100.0,50.0;"]}
        assert get_steerpoints(strings) == []
        assert get_dl_markpoints(strings) == []

    def test_steerpoints_sorted_by_index(self):
        from stringdata import get_steerpoints
        strings = {33: [
            "NP:3,WP,1168000.0,1544000.0,-150.0,50.0;",
            "NP:1,WP,1150000.0,1530000.0,-200.0,40.0;",
            "NP:2,WP,1160000.0,1540000.0,-180.0,45.0;",
        ]}
        stpts = get_steerpoints(strings)
        assert len(stpts) == 3
        assert [s["index"] for s in stpts] == [0, 1, 2]

    def test_out_of_bbox_dropped(self):
        from stringdata import get_steerpoints
        strings = {33: ["NP:1,WP,99999999.0,99999999.0,-100.0,50.0;"]}
        assert get_steerpoints(strings) == []

    def test_malformed_ignored(self):
        from stringdata import get_steerpoints
        assert get_steerpoints({33: ["GARBAGE_NOT_A_NAVPOINT"]}) == []


class TestUtilityReaders:
    def test_get_bms_basedir(self):
        from stringdata import get_bms_basedir
        assert get_bms_basedir({2: [r"D:\Falcon BMS 4.38"]}) == r"D:\Falcon BMS 4.38"

    def test_get_bms_basedir_missing(self):
        from stringdata import get_bms_basedir
        assert get_bms_basedir({}) is None

    def test_get_aircraft_name(self):
        from stringdata import get_aircraft_name
        assert get_aircraft_name({29: ["F-16C"]}) == "F-16C"
