# -*- coding: utf-8 -*-
"""Cross-module integration tests."""

from conftest import make_string_blob, fake_reader


class TestStringDataToMission:
    def test_steerpoints_and_threats(self, reset_mission):
        """StringData NavPoints → steerpoints + PPTs → mission_data."""
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
        mission.update_from_shm(route, threats)
        assert len(mission.mission_data["route"]) == 3
        assert len(mission.mission_data["threats"]) == 1


class TestTheaterSwitchProjection:
    def test_same_coords_different_results(self):
        from theaters import bms_to_latlon, set_active_theater
        lat_kr, _ = bms_to_latlon(1168000.0, 1544000.0)
        set_active_theater("Balkans")
        lat_bk, _ = bms_to_latlon(1168000.0, 1544000.0)
        assert abs(lat_kr - lat_bk) > 1.0


class TestTheaterDetectionChain:
    def test_full_chain(self, reset_stringdata_cache):
        """StringData blob → detect_theater → airports change."""
        from stringdata import read_all_strings, detect_theater
        from theaters import get_airports, get_theater_name

        assert len(get_airports()) >= 40  # Korea airports

        blob = make_string_blob([(13, "Balkans")])
        strings = read_all_strings(0, fake_reader(blob))
        changed = detect_theater(strings)
        assert changed is True
        assert get_theater_name() == "Balkans"
        assert len(get_airports()) == 0  # Balkans has no airports yet
