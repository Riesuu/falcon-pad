# -*- coding: utf-8 -*-
"""Tests for trtt.py — ACMI/TRTT parsers and public API (no network)."""


class TestParsers:
    def test_parse_color(self):
        from core.trtt import _parse_color
        assert _parse_color("Blue") == 1
        assert _parse_color("Red") == 2
        assert _parse_color("Grey") == 3
        assert _parse_color("") == 3

    def test_parse_type(self):
        from core.trtt import _parse_type
        assert _parse_type("Air+FixedWing") == "air"
        assert _parse_type("Air+Rotorcraft") == "air"
        assert _parse_type("Ground+Static") == "ground"
        assert _parse_type("Weapon+Missile") == "weapon"
        assert _parse_type("Sea+Watercraft") == "sea"
        assert _parse_type("Navaid+Static+Bullseye") == "navaid"
        assert _parse_type("Unknown") == "other"

    def test_parse_props(self):
        from core.trtt import _parse_props
        result = _parse_props("Name=Viper1,Color=Blue,Type=Air+FixedWing")
        assert result == {"Name": "Viper1", "Color": "Blue", "Type": "Air+FixedWing"}

    def test_parse_props_with_position(self):
        from core.trtt import _parse_props
        result = _parse_props("T=0.123|0.456|5000|||180.0")
        assert result == {"T": "0.123|0.456|5000|||180.0"}

    def test_parse_props_empty(self):
        from core.trtt import _parse_props
        assert _parse_props("") == {}


class TestPublicAPI:
    def test_get_contacts_empty(self):
        from core.trtt import get_contacts
        assert get_contacts() == []

    def test_get_diagnostics(self):
        from core.trtt import get_diagnostics
        d = get_diagnostics()
        assert d["connected"] is False
        assert d["nb_contacts_raw"] == 0
        assert "trtt_host" in d
        assert "sample" in d
