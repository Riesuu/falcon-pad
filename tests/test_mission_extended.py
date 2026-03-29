# -*- coding: utf-8 -*-
"""Tests — mission.py : extended coverage (status, SHM update, file I/O, upload)."""
import os
import textwrap

import pytest

import mission


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_mission_state():
    """Reset global state between tests."""
    mission.mission_data = {"route": [], "threats": [], "flightplan": []}
    mission._ini_last_path = ""
    mission._ini_last_mtime = 0.0
    mission._shm_mission_hash = ""
    yield


INI_VALID = textwrap.dedent("""\
    [STPT]
    Steerpoint_1 = 390000,1040000,10000
    Steerpoint_2 = 395000,1045000,12000
""")


# ── ini_status ──────────────────────────────────────────────────────────────

class TestIniStatus:
    def test_initial_status(self):
        s = mission.ini_status()
        assert s["file"] is None
        assert s["path"] == ""
        assert s["loaded"] is False
        assert s["steerpoints"] == 0
        assert s["ppt"] == 0
        assert s["flightplan"] == 0

    def test_status_after_load(self):
        mission._ini_last_path = "/some/test.ini"
        mission._ini_last_mtime = 1000.0
        mission.mission_data["route"] = [{"lat": 37, "lon": 127}]
        s = mission.ini_status()
        assert s["file"] == "test.ini"
        assert s["loaded"] is True
        assert s["steerpoints"] == 1


# ── update_from_shm ────────────────────────────────────────────────────────

class TestUpdateFromShm:
    def test_updates_route(self):
        route = [{"lat": 37.0, "lon": 127.0}]
        mission.update_from_shm(route, [])
        assert mission.mission_data["route"] == route

    def test_dedup_skips_identical(self):
        route = [{"lat": 37.0, "lon": 127.0}]
        mission.update_from_shm(route, [])
        old_data = mission.mission_data
        mission.update_from_shm(route, [])
        # Should be exact same object (not updated)
        assert mission.mission_data is old_data

    def test_updates_threats_when_nonempty(self):
        threats = [{"lat": 36.0, "lon": 126.0}]
        mission.update_from_shm([], threats)
        assert mission.mission_data["threats"] == threats

    def test_keeps_old_threats_when_empty(self):
        mission.mission_data["threats"] = [{"lat": 36.0}]
        mission.update_from_shm([{"lat": 37.0, "lon": 127.0}], [])
        assert mission.mission_data["threats"] == [{"lat": 36.0}]

    def test_different_route_triggers_update(self):
        mission.update_from_shm([{"lat": 37.0, "lon": 127.0}], [])
        first = mission.mission_data
        mission.update_from_shm([{"lat": 38.0, "lon": 128.0}], [])
        assert mission.mission_data is not first


# ── set_from_upload ─────────────────────────────────────────────────────────

class TestSetFromUpload:
    def test_sets_mission_data(self):
        result = mission.set_from_upload(INI_VALID, "test.ini")
        assert len(result["route"]) == 2
        assert mission.mission_data is result

    def test_sets_ini_path(self):
        mission.set_from_upload(INI_VALID, "my_dtc.ini")
        assert mission._ini_last_path == "my_dtc.ini"
        assert mission._ini_last_mtime > 0

    def test_empty_ini_returns_empty_route(self):
        result = mission.set_from_upload("[OTHER]\nkey=val", "empty.ini")
        assert result["route"] == []


# ── parse_ini_file ──────────────────────────────────────────────────────────

class TestParseIniFile:
    def test_parse_real_file(self, tmp_path):
        ini = tmp_path / "test.ini"
        ini.write_text(INI_VALID, encoding="latin-1")
        result = mission.parse_ini_file(str(ini))
        assert len(result["route"]) == 2
        assert mission.mission_data is result

    def test_parse_missing_file(self):
        result = mission.parse_ini_file("/nonexistent_12345.ini")
        assert result == {}

    def test_parse_corrupt_file(self, tmp_path):
        ini = tmp_path / "bad.ini"
        ini.write_bytes(b"\x00\xff\xfe" * 100)
        result = mission.parse_ini_file(str(ini))
        # Should not crash — returns empty or parsed
        assert isinstance(result, dict)


# ── find_latest_ini ─────────────────────────────────────────────────────────

class TestFindLatestIni:
    def test_no_files_returns_empty(self, monkeypatch):
        monkeypatch.setattr("mission._registry_ini_patterns", lambda: [])
        path, mtime = mission.find_latest_ini()
        assert path == ""
        assert mtime == 0.0

    def test_finds_ini_with_stpt(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mission._registry_ini_patterns", lambda: [])
        ini = tmp_path / "dtc.ini"
        ini.write_text("[STPT]\nSteerpoint_1 = 390000,1040000,10000\n")
        patterns = [str(tmp_path / "*.ini")]
        path, mtime = mission.find_latest_ini(patterns)
        assert path == str(ini)
        assert mtime > 0

    def test_ignores_ini_without_stpt(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mission._registry_ini_patterns", lambda: [])
        ini = tmp_path / "nope.ini"
        ini.write_text("[OTHER]\nkey=val\n")
        patterns = [str(tmp_path / "*.ini")]
        path, _ = mission.find_latest_ini(patterns)
        assert path == ""

    def test_mission_ini_deprioritized(self, tmp_path, monkeypatch):
        """mission.ini should be deprioritized vs a same-mtime DTC file."""
        monkeypatch.setattr("mission._registry_ini_patterns", lambda: [])
        stpt = "[STPT]\nSteerpoint_1 = 390000,1040000,10000\n"
        dtc = tmp_path / "callsign.ini"
        dtc.write_text(stpt)
        mi = tmp_path / "mission.ini"
        mi.write_text(stpt)
        # Set same mtime
        os.utime(str(dtc), (1000, 1000))
        os.utime(str(mi), (1000, 1000))
        patterns = [str(tmp_path / "*.ini")]
        path, _ = mission.find_latest_ini(patterns)
        assert os.path.basename(path) == "callsign.ini"


# ── _registry_ini_patterns ──────────────────────────────────────────────────

class TestRegistryPatterns:
    def test_returns_list(self):
        # On non-Windows or if BMS not installed, returns empty list
        result = mission._registry_ini_patterns()
        assert isinstance(result, list)

    def test_patterns_are_strings(self):
        for p in mission._registry_ini_patterns():
            assert isinstance(p, str)
