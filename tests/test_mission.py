# -*- coding: utf-8 -*-
"""Tests for mission.py — INI parsing, SHM steerpoints, state management."""


class TestParseIniContent:
    def test_basic_steerpoints(self):
        from mission import parse_ini_content
        ini = "[STPT]\nstpt_0 = 1168000.0,1544000.0,-15000,0\nstpt_1 = 1170000.0,1550000.0,-20000,0\n"
        result = parse_ini_content(ini)
        assert len(result["route"]) == 2
        assert len(result["threats"]) == 0
        assert len(result["flightplan"]) == 0

    def test_with_ppt(self):
        from mission import parse_ini_content
        ini = "[STPT]\nstpt_0 = 1168000.0,1544000.0,-15000,0\nppt_0 = 1165000.0,1540000.0,-10000,50000,SA-2\n"
        result = parse_ini_content(ini)
        assert len(result["route"]) == 1
        assert len(result["threats"]) == 1
        assert result["threats"][0]["name"] == "SA-2"

    def test_with_flight_lines(self):
        from mission import parse_ini_content
        ini = "[STPT]\nline_0 = 1168000.0,1544000.0,-15000,0\nline_1 = 1170000.0,1550000.0,-20000,0\n"
        result = parse_ini_content(ini)
        assert len(result["flightplan"]) == 2
        assert len(result["route"]) == 0

    def test_empty_ini(self):
        from mission import parse_ini_content
        result = parse_ini_content("[OTHER]\nfoo=bar")
        assert result["route"] == []
        assert result["threats"] == []
        assert result["flightplan"] == []

    def test_malformed_entries_skipped(self):
        from mission import parse_ini_content
        ini = "[STPT]\nstpt_0 = not,a,valid\nstpt_1 = 1168000.0,1544000.0,-15000,0\n"
        result = parse_ini_content(ini)
        assert len(result["route"]) == 1


class TestUpdateFromShm:
    def test_update(self, reset_mission):
        import mission
        route = [{"lat": 37.09, "lon": 127.03, "alt": 1500, "index": 0}]
        mission.update_from_shm(route, [])
        assert len(mission.mission_data["route"]) == 1
        assert mission.mission_data["route"][0]["lat"] == 37.09

    def test_no_change_when_same_data(self, reset_mission):
        import mission
        route = [{"lat": 37.09, "lon": 127.03, "alt": 1500, "index": 0}]
        mission.update_from_shm(route, [])
        old_hash = mission._shm_mission_hash
        mission.update_from_shm(route, [])
        assert mission._shm_mission_hash == old_hash


class TestUploadAndStatus:
    def test_set_from_upload(self, reset_mission):
        import mission
        ini = "[STPT]\nstpt_0 = 1168000.0,1544000.0,-15000,0\n"
        result = mission.set_from_upload(ini, "test.ini")
        assert len(result["route"]) == 1
        assert len(mission.mission_data["route"]) == 1

    def test_ini_status(self, reset_mission):
        import mission
        mission.set_from_upload("[STPT]\nstpt_0=1168000.0,1544000.0,-15000,0", "test.ini")
        status = mission.ini_status()
        assert status["loaded"] is True
        assert status["file"] == "test.ini"
        assert status["steerpoints"] == 1
