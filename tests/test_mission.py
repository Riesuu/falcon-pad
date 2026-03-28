# -*- coding: utf-8 -*-
"""Tests — mission.py : parsing fichiers .ini BMS."""
import pytest
from mission import parse_ini_content


# ── Fixtures INI ─────────────────────────────────────────────────────────────

INI_MINIMAL = """
[STPT]
Steerpoint_1 = 390000,1040000,10000
Steerpoint_2 = 395000,1045000,12000
"""

INI_WITH_PPT = """
[STPT]
Steerpoint_1 = 390000,1040000,10000
PPT_1        = 385000,1035000,0,30476,SA-6
PPT_2        = 400000,1050000,0,60952,SA-10
"""

INI_WITH_FPLAN = """
[STPT]
Line_1 = 380000,1020000,8000
Line_2 = 390000,1040000,8000
Steerpoint_1 = 390000,1040000,10000
"""

INI_INVALID_COORDS = """
[STPT]
Steerpoint_1 = 5,5,100
Steerpoint_2 = 390000,1040000,10000
"""

INI_EMPTY = """
[STPT]
"""

INI_NO_SECTION = """
[OTHER]
key = value
"""


# ── Tests ────────────────────────────────────────────────────────────────────

class TestParseIniContent:

    def test_parses_route(self):
        result = parse_ini_content(INI_MINIMAL)
        assert len(result["route"]) == 2

    def test_route_has_lat_lon(self):
        result = parse_ini_content(INI_MINIMAL)
        for pt in result["route"]:
            assert "lat" in pt
            assert "lon" in pt
            assert "alt" in pt
            assert isinstance(pt["lat"], float)
            assert isinstance(pt["lon"], float)

    def test_route_coords_in_korea(self):
        result = parse_ini_content(INI_MINIMAL)
        for pt in result["route"]:
            assert 30.0 < pt["lat"] < 45.0
            assert 118.0 < pt["lon"] < 135.0

    def test_parses_ppt(self):
        result = parse_ini_content(INI_WITH_PPT)
        assert len(result["threats"]) == 2

    def test_ppt_has_name_and_range(self):
        result = parse_ini_content(INI_WITH_PPT)
        names = [t["name"] for t in result["threats"]]
        assert "SA-6" in names
        assert "SA-10" in names
        for t in result["threats"]:
            assert t["range_nm"] >= 1

    def test_parses_flightplan(self):
        result = parse_ini_content(INI_WITH_FPLAN)
        assert len(result["flightplan"]) >= 2

    def test_invalid_coords_ignored(self):
        """Coordonnées trop petites (abs < 10) doivent être ignorées."""
        result = parse_ini_content(INI_INVALID_COORDS)
        assert len(result["route"]) == 1

    def test_empty_stpt_section(self):
        result = parse_ini_content(INI_EMPTY)
        assert result["route"] == []
        assert result["threats"] == []

    def test_no_stpt_section(self):
        result = parse_ini_content(INI_NO_SECTION)
        assert result["route"] == []

    def test_returns_all_keys(self):
        result = parse_ini_content(INI_MINIMAL)
        assert "route" in result
        assert "threats" in result
        assert "flightplan" in result

    def test_route_indexed(self):
        result = parse_ini_content(INI_MINIMAL)
        indices = [p["index"] for p in result["route"]]
        assert indices == list(range(len(result["route"])))
