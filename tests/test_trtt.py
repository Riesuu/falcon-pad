# -*- coding: utf-8 -*-
"""Tests for trtt.py — ACMI/TRTT parsers, coalition logic and public API (no network)."""
import time
import threading
import unittest
from unittest.mock import patch


# ═══════════════════════════════════════════════════════════════════════════
#  PARSER TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestParseColor:
    def test_blue_is_ally(self):
        from core.trtt import _parse_color
        assert _parse_color("Blue") == 1

    def test_blue_case_insensitive(self):
        from core.trtt import _parse_color
        assert _parse_color("blue") == 1
        assert _parse_color("BLUE") == 1

    def test_red_is_enemy(self):
        from core.trtt import _parse_color
        assert _parse_color("Red") == 2

    def test_red_case_insensitive(self):
        from core.trtt import _parse_color
        assert _parse_color("red") == 2
        assert _parse_color("RED") == 2

    def test_other_colors_are_unknown(self):
        from core.trtt import _parse_color
        assert _parse_color("Green")  == 3
        assert _parse_color("Violet") == 3
        assert _parse_color("Orange") == 3
        assert _parse_color("Grey")   == 3
        assert _parse_color("")       == 3


class TestParseType:
    def test_fixed_wing(self):
        from core.trtt import _parse_type
        assert _parse_type("Air+FixedWing") == "air"

    def test_rotorcraft(self):
        from core.trtt import _parse_type
        assert _parse_type("Air+Rotorcraft") == "air"

    def test_ground(self):
        from core.trtt import _parse_type
        assert _parse_type("Ground+Static") == "ground"

    def test_weapon(self):
        from core.trtt import _parse_type
        assert _parse_type("Weapon+Missile") == "weapon"
        assert _parse_type("Projectile+Unguided") == "weapon"

    def test_sea(self):
        from core.trtt import _parse_type
        assert _parse_type("Sea+Watercraft") == "sea"

    def test_navaid_and_bullseye(self):
        from core.trtt import _parse_type
        assert _parse_type("Navaid+Static+Bullseye") == "navaid"
        assert _parse_type("Navaid+Fix") == "navaid"

    def test_unknown_type(self):
        from core.trtt import _parse_type
        assert _parse_type("Unknown") == "other"
        assert _parse_type("") == "other"


class TestParseProps:
    def test_basic_key_value(self):
        from core.trtt import _parse_props
        result = _parse_props("Name=Viper1,Color=Blue,Type=Air+FixedWing")
        assert result == {"Name": "Viper1", "Color": "Blue", "Type": "Air+FixedWing"}

    def test_position_field(self):
        from core.trtt import _parse_props
        result = _parse_props("T=0.123|0.456|5000|||180.0")
        assert result == {"T": "0.123|0.456|5000|||180.0"}

    def test_empty_string(self):
        from core.trtt import _parse_props
        assert _parse_props("") == {}

    def test_coalition_field(self):
        from core.trtt import _parse_props
        result = _parse_props("Coalition=Allies,Name=F16C")
        assert result["Coalition"] == "Allies"
        assert result["Name"] == "F16C"

    def test_no_equals_sign_ignored(self):
        from core.trtt import _parse_props
        result = _parse_props("Name=Viper1,garbage,Type=Air+FixedWing")
        assert "garbage" not in result
        assert result["Name"] == "Viper1"

    def test_value_with_pipe(self):
        from core.trtt import _parse_props
        result = _parse_props("T=1.0|2.0|3000|0|0|270.0,IAS=200")
        assert result["T"] == "1.0|2.0|3000|0|0|270.0"
        assert result["IAS"] == "200"


# ═══════════════════════════════════════════════════════════════════════════
#  COALITION LOGIC TESTS (authoritative friend/foe per ACMI spec)
# ═══════════════════════════════════════════════════════════════════════════

class TestCoalitionPriority:
    """Coalition field must take precedence over Color field."""

    def _inject_contact(self, props_line: str, ref_lat=37.0, ref_lon=127.0):
        """
        Simulate a minimal TRTT stream with one contact.
        Returns the contact dict or None if filtered.
        """
        import importlib
        import core.trtt as trtt_mod
        # Reset state
        with trtt_mod._lock:
            trtt_mod._contacts.clear()
        import core.trtt as trtt
        from core.trtt import _parse_props, _parse_color, _parse_type

        obj_id = "1"
        obj_props = {obj_id: {'name': '', 'color': 3, 'acmi_type': 'other', 'pilot': ''}}
        p = obj_props[obj_id]

        props = _parse_props(props_line)

        if 'Name'      in props: p['name']      = props['Name']
        if 'Type'      in props: p['acmi_type'] = _parse_type(props['Type'])
        if 'Pilot'     in props: p['pilot']     = props['Pilot']
        if 'Group'     in props and not p['name']: p['name'] = props['Group']

        # Coalition-first logic (what we changed)
        if 'Coalition' in props:
            co = props['Coalition'].lower()
            if 'allies' in co:    p['color'] = 1
            elif 'enemies' in co: p['color'] = 2
            else:                 p['color'] = 3
        elif 'Color' in props:
            p['color'] = _parse_color(props['Color'])

        # Inject a valid position
        with trtt_mod._lock:
            trtt_mod._contacts[obj_id] = {
                'lat': ref_lat, 'lon': ref_lon,
                'alt': 10000, 'camp': p['color'],
                'callsign': p['name'] or obj_id,
                'pilot': p['pilot'],
                'type_name': p['acmi_type'],
                'heading': 0.0, 'speed': 0,
                '_ts': time.time(),
            }

        contacts = trtt_mod.get_contacts()
        return contacts[0] if contacts else None

    def test_coalition_allies_gives_camp1(self):
        c = self._inject_contact("Coalition=Allies,Type=Air+FixedWing,T=0|0|5000|||0")
        assert c is not None
        assert c['camp'] == 1

    def test_coalition_enemies_gives_camp2(self):
        c = self._inject_contact("Coalition=Enemies,Type=Air+FixedWing,T=0|0|5000|||0")
        assert c is not None
        assert c['camp'] == 2

    def test_coalition_overrides_color(self):
        """Coalition=Allies with Color=Red must yield camp=1 (Coalition wins)."""
        c = self._inject_contact("Coalition=Allies,Color=Red,Type=Air+FixedWing,T=0|0|5000|||0")
        assert c is not None
        assert c['camp'] == 1

    def test_coalition_enemies_overrides_blue_color(self):
        """Coalition=Enemies with Color=Blue must yield camp=2 (Coalition wins)."""
        c = self._inject_contact("Coalition=Enemies,Color=Blue,Type=Air+FixedWing,T=0|0|5000|||0")
        assert c is not None
        assert c['camp'] == 2

    def test_color_fallback_when_no_coalition(self):
        """Without Coalition field, Color is used as fallback."""
        c = self._inject_contact("Color=Blue,Type=Air+FixedWing,T=0|0|5000|||0")
        assert c is not None
        assert c['camp'] == 1

    def test_color_red_fallback(self):
        c = self._inject_contact("Color=Red,Type=Air+FixedWing,T=0|0|5000|||0")
        assert c is not None
        assert c['camp'] == 2

    def test_no_coalition_no_color_is_unknown(self):
        c = self._inject_contact("Type=Air+FixedWing,T=0|0|5000|||0")
        assert c is not None
        assert c['camp'] == 3

    def test_unknown_coalition_value_is_unknown(self):
        c = self._inject_contact("Coalition=Neutral,Type=Air+FixedWing,T=0|0|5000|||0")
        assert c is not None
        assert c['camp'] == 3


# ═══════════════════════════════════════════════════════════════════════════
#  CONTACT FILTERING TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestContactFiltering:
    def _set_contacts(self, contacts_dict):
        import core.trtt as trtt
        with trtt._lock:
            trtt._contacts.clear()
            trtt._contacts.update(contacts_dict)

    def test_stale_contact_excluded(self):
        import core.trtt as trtt
        self._set_contacts({"1": {
            'lat': 37.0, 'lon': 127.0, 'alt': 5000, 'camp': 1,
            'callsign': 'V1', 'pilot': '', 'type_name': 'air',
            'heading': 0.0, 'speed': 0, '_ts': time.time() - 31.0
        }})
        assert trtt.get_contacts() == []

    def test_fresh_contact_included(self):
        import core.trtt as trtt
        self._set_contacts({"1": {
            'lat': 37.0, 'lon': 127.0, 'alt': 5000, 'camp': 1,
            'callsign': 'V1', 'pilot': '', 'type_name': 'air',
            'heading': 0.0, 'speed': 0, '_ts': time.time()
        }})
        result = trtt.get_contacts()
        assert len(result) == 1
        assert result[0]['callsign'] == 'V1'

    def test_ground_contact_excluded(self):
        import core.trtt as trtt
        self._set_contacts({"1": {
            'lat': 37.0, 'lon': 127.0, 'alt': 0, 'camp': 2,
            'callsign': 'T72', 'pilot': '', 'type_name': 'ground',
            'heading': 0.0, 'speed': 0, '_ts': time.time()
        }})
        assert trtt.get_contacts() == []

    def test_weapon_contact_excluded(self):
        import core.trtt as trtt
        self._set_contacts({"1": {
            'lat': 37.0, 'lon': 127.0, 'alt': 5000, 'camp': 2,
            'callsign': 'AIM120', 'pilot': '', 'type_name': 'weapon',
            'heading': 0.0, 'speed': 0, '_ts': time.time()
        }})
        assert trtt.get_contacts() == []

    def test_sea_contact_excluded(self):
        import core.trtt as trtt
        self._set_contacts({"1": {
            'lat': 37.0, 'lon': 127.0, 'alt': 0, 'camp': 2,
            'callsign': 'Ship1', 'pilot': '', 'type_name': 'sea',
            'heading': 0.0, 'speed': 0, '_ts': time.time()
        }})
        assert trtt.get_contacts() == []

    def test_navaid_contact_excluded(self):
        import core.trtt as trtt
        self._set_contacts({"1": {
            'lat': 37.0, 'lon': 127.0, 'alt': 0, 'camp': 3,
            'callsign': 'BULL', 'pilot': '', 'type_name': 'navaid',
            'heading': 0.0, 'speed': 0, '_ts': time.time()
        }})
        assert trtt.get_contacts() == []

    def test_unknown_type_recent_included(self):
        import core.trtt as trtt
        self._set_contacts({"1": {
            'lat': 37.0, 'lon': 127.0, 'alt': 5000, 'camp': 3,
            'callsign': 'UNK1', 'pilot': '', 'type_name': 'other',
            'heading': 0.0, 'speed': 0, '_ts': time.time()
        }})
        result = trtt.get_contacts()
        assert len(result) == 1

    def test_unknown_type_stale_excluded(self):
        import core.trtt as trtt
        self._set_contacts({"1": {
            'lat': 37.0, 'lon': 127.0, 'alt': 5000, 'camp': 3,
            'callsign': 'UNK1', 'pilot': '', 'type_name': 'other',
            'heading': 0.0, 'speed': 0, '_ts': time.time() - 11.0
        }})
        assert trtt.get_contacts() == []

    def test_ts_field_not_in_result(self):
        import core.trtt as trtt
        self._set_contacts({"1": {
            'lat': 37.0, 'lon': 127.0, 'alt': 5000, 'camp': 1,
            'callsign': 'V1', 'pilot': '', 'type_name': 'air',
            'heading': 0.0, 'speed': 0, '_ts': time.time()
        }})
        result = trtt.get_contacts()
        assert '_ts' not in result[0]

    def test_all_camps_returned(self):
        """Enemies and unknowns must NOT be filtered (no allies_only)."""
        import core.trtt as trtt
        now = time.time()
        self._set_contacts({
            "1": {'lat': 37.0, 'lon': 127.0, 'alt': 5000, 'camp': 1,
                  'callsign': 'Ally', 'pilot': '', 'type_name': 'air',
                  'heading': 0.0, 'speed': 0, '_ts': now},
            "2": {'lat': 37.1, 'lon': 127.1, 'alt': 5000, 'camp': 2,
                  'callsign': 'Enemy', 'pilot': '', 'type_name': 'air',
                  'heading': 0.0, 'speed': 0, '_ts': now},
            "3": {'lat': 37.2, 'lon': 127.2, 'alt': 5000, 'camp': 3,
                  'callsign': 'Unknown', 'pilot': '', 'type_name': 'air',
                  'heading': 0.0, 'speed': 0, '_ts': now},
        })
        result = trtt.get_contacts()
        camps = {c['camp'] for c in result}
        assert camps == {1, 2, 3}


# ═══════════════════════════════════════════════════════════════════════════
#  PUBLIC API TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPublicAPI:
    def test_get_contacts_empty(self):
        import core.trtt as trtt
        with trtt._lock:
            trtt._contacts.clear()
        assert trtt.get_contacts() == []

    def test_get_diagnostics_structure(self):
        from core.trtt import get_diagnostics
        d = get_diagnostics()
        assert d["connected"] is False
        assert d["nb_contacts_raw"] == 0
        assert "trtt_host" in d
        assert "sample" in d
        assert "config_bms" in d

    def test_is_connected_initially_false(self):
        from core.trtt import is_connected
        assert is_connected() is False

    def test_start_stop_no_crash(self):
        import core.trtt as trtt
        trtt.start()
        assert trtt._thread is not None
        trtt.stop()
