# -*- coding: utf-8 -*-
"""
Falcon-Pad test suite.
Run: python -m pytest tests.py -v
"""

import json
import math
import os
import struct
import sys
import pytest

# Ensure modules are importable from this directory
sys.path.insert(0, os.path.dirname(__file__))


# ═══════════════════════════════════════════════════════════════════════════
#  theaters.py
# ═══════════════════════════════════════════════════════════════════════════

class TestTheaters:
    """Test theater database, projection, and airport functions."""

    def test_theater_db_not_empty(self):
        from theaters import THEATER_DB
        assert len(THEATER_DB) >= 7

    def test_korea_registered(self):
        from theaters import THEATER_DB
        assert "korea" in THEATER_DB
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

    def test_bms_to_latlon_korea_osan(self):
        """Known coords: Osan AB ~37.09N 127.03E."""
        from theaters import bms_to_latlon, set_active_theater
        set_active_theater("Korea")
        lat, lon = bms_to_latlon(1168000.0, 1544000.0)
        assert 37.0 < lat < 37.2, f"Expected ~37.09, got {lat}"
        assert 126.9 < lon < 127.1, f"Expected ~127.03, got {lon}"

    def test_bms_to_latlon_zero_input(self):
        from theaters import bms_to_latlon, set_active_theater
        set_active_theater("Korea")
        lat, lon = bms_to_latlon(0.0, 0.0)
        # Should return some valid lat/lon (the FN offset makes it non-zero)
        assert isinstance(lat, float)
        assert isinstance(lon, float)

    def test_in_theater_bbox(self):
        from theaters import in_theater_bbox, set_active_theater
        set_active_theater("Korea")
        assert in_theater_bbox(37.0, 127.0) is True
        assert in_theater_bbox(0.0, 0.0) is False
        assert in_theater_bbox(60.0, 127.0) is False

    def test_set_active_theater_direct(self):
        from theaters import set_active_theater, get_theater_name
        changed = set_active_theater("Balkans")
        assert changed is True
        assert get_theater_name() == "Balkans"
        # Same theater again → no change
        changed2 = set_active_theater("Balkans")
        assert changed2 is False
        # Reset to Korea for other tests
        set_active_theater("Korea")

    def test_set_active_theater_fuzzy(self):
        from theaters import set_active_theater, get_theater, get_theater_name
        set_active_theater("Balkans")  # start from non-Korea
        changed = set_active_theater("Korea KTO 1.0")
        assert changed is True
        # Should fuzzy-match "korea kto" or "korea" — either has lon0=127.5
        assert get_theater().lon0 == 127.5
        set_active_theater("Korea")  # reset

    def test_set_active_theater_unknown(self):
        from theaters import set_active_theater, get_theater_name
        set_active_theater("Korea")  # reset
        old_name = get_theater_name()
        changed = set_active_theater("MarsTheater2099")
        assert changed is False
        assert get_theater_name() == old_name

    def test_get_airports_korea(self):
        """Korea airport JSON doit contenir au moins 40 aéroports avec la bonne structure."""
        import json, os
        path = os.path.join(os.path.dirname(__file__), "..", "data", "airports", "korea.json")
        with open(path, encoding="utf-8") as f:
            airports = json.load(f)
        assert len(airports) >= 40
        osan = [a for a in airports if a["icao"] == "RKSO"]
        assert len(osan) == 1
        assert osan[0]["name"] == "Osan AB"
        assert osan[0]["tacan"] == "116X"
        assert isinstance(osan[0]["ils"], list)

    def test_get_airports_all_theaters_have_json(self):
        """Chaque théâtre enregistré doit avoir un fichier JSON d'aéroports."""
        import json, os
        theater_files = {
            "korea": "korea.json", "balkans": "balkans.json",
            "israel": "israel.json", "aegean": "aegean.json",
            "iberia": "iberia.json", "nordic": "nordic.json",
            "hellas": "hto.json",
        }
        base = os.path.join(os.path.dirname(__file__), "..", "data", "airports")
        for theater, filename in theater_files.items():
            path = os.path.join(base, filename)
            assert os.path.exists(path), f"Fichier airports manquant pour {theater}: {filename}"
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert isinstance(data, list), f"{filename} doit être une liste JSON"

    def test_bms_to_latlon_theater_switch(self):
        """Projection should change when theater changes."""
        from theaters import bms_to_latlon, set_active_theater
        set_active_theater("Korea")
        lat_kr, lon_kr = bms_to_latlon(1168000.0, 1544000.0)
        set_active_theater("Balkans")
        lat_bk, lon_bk = bms_to_latlon(1168000.0, 1544000.0)
        # Same input should give wildly different outputs
        assert abs(lat_kr - lat_bk) > 1.0, "Projection didn't change"
        assert abs(lon_kr - lon_bk) > 1.0, "Projection didn't change"
        set_active_theater("Korea")  # reset

    def test_korea_bbox_extended(self):
        """Bbox Korea élargie doit couvrir les steerpoints à l'est (jusqu'à 137°E)."""
        from theaters import in_theater_bbox, set_active_theater
        set_active_theater("Korea")
        # Points légitimes Korea qui étaient hors bbox avec l'ancienne limite 135°E
        assert in_theater_bbox(44.0, 136.0) is True
        assert in_theater_bbox(32.0, 118.0) is True
        # Hors bbox
        assert in_theater_bbox(35.0, 140.0) is False   # trop à l'est (Japon)
        assert in_theater_bbox(35.0, 115.0) is False   # trop à l'ouest

    def test_detect_theater_requires_2_hits(self):
        """detect_theater_from_coords_multi doit exiger au moins 2 hits pour changer."""
        from theaters import detect_theater_from_coords_multi, set_active_theater, get_theater_name
        set_active_theater("Korea")
        # Un seul point ambigu → ne doit pas changer de théâtre
        detect_theater_from_coords_multi([(1_168_000.0, 1_544_000.0)])
        assert get_theater_name() == "Korea"  # reste Korea car 1 seul hit

    def test_detect_theater_multi_points_korea(self):
        """Plusieurs steerpoints Korea → détecte Korea."""
        from theaters import detect_theater_from_coords_multi, set_active_theater, get_theater_name
        set_active_theater("Balkans")  # partir d'un autre théâtre
        pts = [
            (1_168_000.0, 1_544_000.0),
            (1_200_000.0, 1_580_000.0),
            (1_150_000.0, 1_510_000.0),
        ]
        detect_theater_from_coords_multi(pts)
        assert get_theater_name() == "Korea"
        set_active_theater("Korea")


# ═══════════════════════════════════════════════════════════════════════════
#  stringdata.py
# ═══════════════════════════════════════════════════════════════════════════

def _make_string_blob(entries: list) -> bytes:
    """Build a fake StringData blob from [(strId, text), ...]."""
    data_parts = []
    for str_id, text in entries:
        encoded = text.encode('utf-8')
        data_parts.append(struct.pack('<II', str_id, len(encoded)))
        data_parts.append(encoded + b'\x00')  # null terminator
    data_blob = b''.join(data_parts)
    header = struct.pack('<III', 5, len(entries), len(data_blob))
    return header + data_blob


def _fake_reader(blob: bytes):
    """Return a safe_read-compatible function from a blob."""
    def reader(addr: int, size: int):
        return blob[addr:addr + size] if addr + size <= len(blob) else None
    return reader


class TestStringData:
    """Test StringData reader and NavPoint parsers."""

    def setup_method(self):
        from theaters import set_active_theater
        set_active_theater("Korea")

    def test_strid_navpoint_is_33(self):
        from stringdata import STRID_NAVPOINT
        assert STRID_NAVPOINT == 33, f"Expected 33, got {STRID_NAVPOINT}"

    def test_strid_thr_name_is_13(self):
        from stringdata import STRID_THR_NAME
        assert STRID_THR_NAME == 13

    def test_read_all_strings_empty(self):
        from stringdata import read_all_strings
        result = read_all_strings(0, lambda a, s: None)
        assert result == {}

    def test_read_all_strings_valid(self):
        from stringdata import read_all_strings, STRID_THR_NAME
        blob = _make_string_blob([(13, "Korea"), (29, "F-16C")])
        reader = _fake_reader(blob)
        result = read_all_strings(0, reader)
        assert STRID_THR_NAME in result
        assert result[13] == ["Korea"]
        assert result[29] == ["F-16C"]

    def test_read_all_strings_corrupt_header(self):
        from stringdata import read_all_strings
        result = read_all_strings(0, lambda a, s: b'\xff' * 4)
        assert result == {}

    def test_detect_theater(self):
        from stringdata import detect_theater
        from theaters import get_theater_name, set_active_theater
        import stringdata
        set_active_theater("Korea")
        stringdata._last_thr_name = ""  # reset detection cache
        strings = {13: ["Balkans"]}
        changed = detect_theater(strings)
        assert changed is True
        assert get_theater_name() == "Balkans"
        set_active_theater("Korea")  # reset

    def test_detect_theater_no_thr_name(self):
        from stringdata import detect_theater
        strings = {29: ["F-16C"]}
        changed = detect_theater(strings)
        assert changed is False

    def test_parse_navpoint_wp(self):
        from stringdata import get_steerpoints
        raw = "NP:3,WP,1168000.0,1544000.0,-150.0,50.0;"
        strings = {33: [raw]}
        stpts = get_steerpoints(strings)
        assert len(stpts) == 1
        assert stpts[0]["index"] == 0
        assert stpts[0]["alt"] == 1500
        assert 37.0 < stpts[0]["lat"] < 37.2

    def test_parse_navpoint_dl(self):
        from stringdata import get_dl_markpoints
        raw = "NP:55,DL,1170000.0,1550000.0,-200.0,50.0;"
        strings = {33: [raw]}
        marks = get_dl_markpoints(strings)
        assert len(marks) == 1
        assert marks[0]["label"] == "DL 55"
        assert "lat" in marks[0] and "lon" in marks[0]

    def test_parse_navpoint_dl_excludes_ownship(self):
        from stringdata import get_dl_markpoints
        from theaters import bms_to_latlon
        raw = "NP:55,DL,1170000.0,1550000.0,-200.0,50.0;"
        lat, lon = bms_to_latlon(1170000.0, 1550000.0)
        strings = {33: [raw]}
        marks = get_dl_markpoints(strings, own_lat=lat, own_lon=lon)
        assert len(marks) == 0, "Le marqueur ownship doit être exclu"

    def test_parse_navpoint_ppt(self):
        from stringdata import get_ppt_threats
        raw = 'NP:57,PT,1168000.0,1544000.0,-100.0,50.0;PT:"SA-2",50000.0,0;'
        strings = {33: [raw]}
        ppts = get_ppt_threats(strings)
        assert len(ppts) == 1
        assert ppts[0]["name"] == "SA-2"
        assert ppts[0]["range_nm"] == 8

    def test_parse_navpoint_invalid_type_ignored(self):
        from stringdata import get_steerpoints, get_dl_markpoints
        raw = "NP:10,CB,1168000.0,1544000.0,-100.0,50.0;"  # CB = bullseye, non reconnu
        strings = {33: [raw]}
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
        # Should be re-indexed 0,1,2 but sorted by original NP index
        assert stpts[0]["index"] == 0
        assert stpts[1]["index"] == 1
        assert stpts[2]["index"] == 2

    def test_parse_navpoint_out_of_bbox(self):
        """NavPoints outside theater bbox should be dropped."""
        from stringdata import get_steerpoints
        # Coords far from Korea
        raw = "NP:1,WP,99999999.0,99999999.0,-100.0,50.0;"
        strings = {33: [raw]}
        assert get_steerpoints(strings) == []

    def test_parse_navpoint_malformed(self):
        from stringdata import get_steerpoints
        strings = {33: ["GARBAGE_DATA_NOT_A_NAVPOINT"]}
        assert get_steerpoints(strings) == []

    def test_get_bms_basedir(self):
        from stringdata import get_bms_basedir
        strings = {2: [r"D:\Falcon BMS 4.38"]}
        assert get_bms_basedir(strings) == r"D:\Falcon BMS 4.38"

    def test_get_bms_basedir_missing(self):
        from stringdata import get_bms_basedir
        assert get_bms_basedir({}) is None

    def test_get_aircraft_name(self):
        from stringdata import get_aircraft_name
        strings = {29: ["F-16C"]}
        assert get_aircraft_name(strings) == "F-16C"


# ═══════════════════════════════════════════════════════════════════════════
#  trtt.py
# ═══════════════════════════════════════════════════════════════════════════

class TestTRTT:
    """Test TRTT parsers (no actual network)."""

    def test_parse_color(self):
        from trtt import _parse_color
        assert _parse_color("Blue") == 1
        assert _parse_color("Red") == 2
        assert _parse_color("Grey") == 3
        assert _parse_color("") == 3

    def test_parse_type(self):
        from trtt import _parse_type
        assert _parse_type("Air+FixedWing") == "air"
        assert _parse_type("Air+Rotorcraft") == "air"
        assert _parse_type("Ground+Static") == "ground"
        assert _parse_type("Weapon+Missile") == "weapon"
        assert _parse_type("Sea+Watercraft") == "sea"
        assert _parse_type("Navaid+Static+Bullseye") == "navaid"
        assert _parse_type("Unknown") == "other"

    def test_parse_props(self):
        from trtt import _parse_props
        result = _parse_props("Name=Viper1,Color=Blue,Type=Air+FixedWing")
        assert result == {"Name": "Viper1", "Color": "Blue", "Type": "Air+FixedWing"}

    def test_parse_props_with_position(self):
        from trtt import _parse_props
        result = _parse_props("T=0.123|0.456|5000|||180.0")
        assert result == {"T": "0.123|0.456|5000|||180.0"}

    def test_parse_props_empty(self):
        from trtt import _parse_props
        assert _parse_props("") == {}

    def test_get_contacts_empty(self):
        from trtt import get_contacts
        result = get_contacts()
        assert result == []

    def test_get_diagnostics(self):
        from trtt import get_diagnostics
        d = get_diagnostics()
        assert "connected" in d
        assert "nb_contacts_raw" in d
        assert d["connected"] is False
        assert d["nb_contacts_raw"] == 0


# ═══════════════════════════════════════════════════════════════════════════
#  mission.py
# ═══════════════════════════════════════════════════════════════════════════

class TestMission:
    """Test INI parsing and mission state."""

    def setup_method(self):
        from theaters import set_active_theater
        set_active_theater("Korea")

    def test_parse_ini_content_basic(self):
        from mission import parse_ini_content
        ini = """[STPT]
stpt_0 = 1168000.0,1544000.0,-15000,0
stpt_1 = 1170000.0,1550000.0,-20000,0
"""
        result = parse_ini_content(ini)
        assert len(result["route"]) == 2
        assert len(result["threats"]) == 0
        assert len(result["flightplan"]) == 0

    def test_parse_ini_content_with_ppt(self):
        from mission import parse_ini_content
        ini = """[STPT]
stpt_0 = 1168000.0,1544000.0,-15000,0
ppt_0 = 1165000.0,1540000.0,-10000,50000,SA-2
"""
        result = parse_ini_content(ini)
        assert len(result["route"]) == 1
        assert len(result["threats"]) == 1
        assert result["threats"][0]["name"] == "SA-2"

    def test_parse_ini_content_with_lines(self):
        from mission import parse_ini_content
        ini = """[STPT]
line_0 = 1168000.0,1544000.0,-15000,0
line_1 = 1170000.0,1550000.0,-20000,0
"""
        result = parse_ini_content(ini)
        assert len(result["flightplan"]) == 2
        assert len(result["route"]) == 0

    def test_parse_ini_content_empty(self):
        from mission import parse_ini_content
        result = parse_ini_content("[OTHER]\nfoo=bar")
        assert result["route"] == []
        assert result["threats"] == []

    def test_parse_ini_content_malformed(self):
        from mission import parse_ini_content
        ini = """[STPT]
stpt_0 = not,a,valid,entry
stpt_1 = 1168000.0,1544000.0,-15000,0
"""
        result = parse_ini_content(ini)
        assert len(result["route"]) == 1  # only valid entry

    def test_update_from_shm(self):
        import mission
        mission._shm_mission_hash = ""  # force update
        route = [{"lat": 37.09, "lon": 127.03, "alt": 1500, "index": 0}]
        mission.update_from_shm(route, [])
        assert len(mission.mission_data["route"]) == 1
        assert mission.mission_data["route"][0]["lat"] == 37.09

    def test_update_from_shm_no_change(self):
        """Calling update_from_shm with same data should be a no-op."""
        import mission
        route = [{"lat": 37.09, "lon": 127.03, "alt": 1500, "index": 0}]
        mission._shm_mission_hash = ""  # reset
        mission.update_from_shm(route, [])
        old_hash = mission._shm_mission_hash
        mission.update_from_shm(route, [])
        assert mission._shm_mission_hash == old_hash

    def test_set_from_upload(self):
        import mission
        ini = """[STPT]
stpt_0 = 1168000.0,1544000.0,-15000,0
"""
        result = mission.set_from_upload(ini, "test.ini")
        assert len(result["route"]) == 1
        assert len(mission.mission_data["route"]) == 1

    def test_ini_status(self):
        from mission import ini_status, set_from_upload
        set_from_upload("[STPT]\nstpt_0=1168000.0,1544000.0,-15000,0", "test.ini")
        status = ini_status()
        assert status["loaded"] is True
        assert status["file"] == "test.ini"
        assert status["steerpoints"] == 1


# ═══════════════════════════════════════════════════════════════════════════
#  sharedmem.py (non-Windows: skip SHM tests, test helpers)
# ═══════════════════════════════════════════════════════════════════════════

class TestSharedMem:
    """Test sharedmem helpers (safe_read etc). SHM itself only works on Windows."""

    def test_safe_read_null_addr(self):
        from sharedmem import safe_read
        assert safe_read(0, 4) is None

    def test_safe_float_null(self):
        from sharedmem import safe_float
        assert safe_float(0) is None

    def test_safe_int32_null(self):
        from sharedmem import safe_int32
        assert safe_int32(0) is None

    def test_fd_offsets_exist(self):
        from sharedmem import FD_KIAS, FD_CURRENT_HDG, FD2_LAT, FD2_LON
        assert FD_KIAS == 0x034
        assert FD_CURRENT_HDG == 0x0BC
        assert FD2_LAT == 0x408
        assert FD2_LON == 0x40C

    def test_bms_shared_memory_not_connected(self):
        """On non-Windows, BMSSharedMemory should fail gracefully."""
        import sys
        if sys.platform == 'win32':
            pytest.skip("Windows-only test")
        from sharedmem import BMSSharedMemory
        bms = BMSSharedMemory()
        assert bms.connected is False
        assert bms.ptr1 is None
        assert bms.ptr2 is None

    def test_get_position_disconnected(self):
        import sys
        if sys.platform == 'win32':
            pytest.skip("Windows-only test")
        from sharedmem import BMSSharedMemory
        bms = BMSSharedMemory()
        assert bms.get_position() is None


# ═══════════════════════════════════════════════════════════════════════════
#  Integration tests
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Cross-module integration tests."""

    def setup_method(self):
        from theaters import set_active_theater
        set_active_theater("Korea")

    def test_stringdata_to_mission_steerpoints(self):
        """StringData NavPoints → mission.update_from_shm → mission_data."""
        from stringdata import get_steerpoints, get_ppt_threats
        import mission

        strings = {33: [
            "NP:1,WP,1150000.0,1530000.0,-200.0,40.0;",
            "NP:2,WP,1160000.0,1540000.0,-180.0,45.0;",
            "NP:3,WP,1168000.0,1544000.0,-150.0,50.0;",
            'NP:57,PT,1168000.0,1544000.0,-100.0,50.0;PT:"SA-2",50000.0,0;',
        ]}
        route = get_steerpoints(strings)
        threats = get_ppt_threats(strings)
        mission._shm_mission_hash = ""  # force update
        mission.update_from_shm(route, threats)
        assert len(mission.mission_data["route"]) == 3
        assert len(mission.mission_data["threats"]) == 1

    def test_theater_switch_affects_projection(self):
        """Switching theater should change bms_to_latlon output."""
        from theaters import set_active_theater, bms_to_latlon

        set_active_theater("Korea")
        lat_kr, _ = bms_to_latlon(1168000.0, 1544000.0)

        set_active_theater("Balkans")
        lat_bk, _ = bms_to_latlon(1168000.0, 1544000.0)

        assert abs(lat_kr - lat_bk) > 1.0
        set_active_theater("Korea")

    def test_theater_detection_from_stringdata(self):
        """Full chain: StringData blob → detect_theater → theater name changes."""
        from stringdata import read_all_strings, detect_theater
        from theaters import get_theater_name, set_active_theater
        import stringdata

        set_active_theater("Korea")
        stringdata._last_thr_name = ""  # reset detection cache

        blob = _make_string_blob([(13, "Balkans")])
        reader = _fake_reader(blob)
        strings = read_all_strings(0, reader)
        changed = detect_theater(strings)
        assert changed is True, f"detect_theater returned False, _last_thr_name={stringdata._last_thr_name!r}"
        assert get_theater_name() == "Balkans"

        set_active_theater("Korea")


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
