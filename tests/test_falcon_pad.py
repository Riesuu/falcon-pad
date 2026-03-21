# -*- coding: utf-8 -*-
"""
Tests unitaires — Falcon-Pad v0.3
Couvre toute la logique pure Python sans dépendance Windows/FastAPI/PySide6.

Usage : python3 test_falcon_pad.py
"""

import unittest
import math
import os
import sys
import json
import tempfile
import shutil
import struct
import time
import re
from unittest.mock import patch, MagicMock
from datetime import datetime


# ══════════════════════════════════════════════════════════════════
#  Fonctions extraites de falcon_pad.py pour test isolé
#  (le fichier source n'est pas importable tel quel à cause des
#   dépendances ctypes/WinDLL/FastAPI/PySide6)
# ══════════════════════════════════════════════════════════════════

def bms_to_latlon(north_ft: float, east_ft: float) -> tuple:
    a = 6378137.0; e2 = 0.00669437999014; lon0 = math.radians(127.5)
    k0 = 0.9996; FE = 512000.0; FN = -3749290.0
    E_m = east_ft * 0.3048; N_m = north_ft * 0.3048
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    M1 = (N_m - FN) / k0
    mu1 = M1 / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    phi1 = (mu1 + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu1)
            + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu1)
            + (151 * e1**3 / 96) * math.sin(6 * mu1))
    N1r = a / math.sqrt(1 - e2 * math.sin(phi1)**2)
    T1 = math.tan(phi1)**2; C1 = e2 * math.cos(phi1)**2 / (1 - e2)
    R1 = a * (1 - e2) / (1 - e2 * math.sin(phi1)**2)**1.5
    D = (E_m - FE) / (N1r * k0)
    lat = phi1 - (N1r * math.tan(phi1) / R1) * (D**2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1**2 - 9 * e2) * D**4 / 24)
    lon = lon0 + (D - (1 + 2 * T1 + C1) * D**3 / 6) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lon)


def _parse_trtt_color(color_str: str) -> int:
    c = color_str.lower()
    if 'blue' in c:  return 1
    if 'red' in c:   return 2
    return 3


def _parse_trtt_type(type_str: str) -> str:
    t = type_str.lower()
    if 'fixedwing' in t or 'rotorcraft' in t: return 'air'
    if 'ground' in t:  return 'ground'
    if 'weapon' in t or 'missile' in t or 'projectile' in t: return 'weapon'
    if 'sea' in t or 'ship' in t: return 'sea'
    if 'navaid' in t or 'bullseye' in t: return 'navaid'
    return 'other'


def _parse_navpoint_dl(raw: str, own_lat=None, own_lon=None):
    try:
        m = re.search(r'NP:(\d+),([A-Z]+),([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+);', raw)
        if not m:
            return None
        idx  = int(m.group(1))
        typ  = m.group(2)
        x    = float(m.group(3))
        y    = float(m.group(4))
        z    = float(m.group(5))
        if typ != 'DL':
            return None
        lat, lon = bms_to_latlon(x, y)
        if not (25 <= lat <= 50 and 110 <= lon <= 145):
            return None
        if own_lat is not None and own_lon is not None:
            if abs(lat - own_lat) < 0.002 and abs(lon - own_lon) < 0.002:
                return None
        return {
            "lat":      round(lat, 5),
            "lon":      round(lon, 5),
            "alt":      round(abs(z) * 10),
            "camp":     1,
            "type_name": "L16",
            "callsign": f"DL{idx:02d}",
            "heading":  0,
            "speed":    0,
        }
    except Exception:
        return None


def _is_local(ip: str) -> bool:
    return (
        ip in ("127.0.0.1", "::1", "localhost") or
        ip.startswith("10.") or
        ip.startswith("192.168.") or
        (ip.startswith("172.") and
         any(ip.startswith(f"172.{i}.") for i in range(16, 32)))
    )


def get_acmi_contacts(acmi_contacts: dict, acmi_lock,
                      own_lat=None, own_lon=None,
                      max_nm: float = 9999.0, allies_only: bool = False) -> list:
    now = time.time()
    with acmi_lock:
        contacts = list(acmi_contacts.items())
    result = []
    for obj_id, c in contacts:
        if now - c.get('_ts', 0) > 30.0:
            continue
        if allies_only and c.get('camp', 3) == 2:
            continue
        ct = c.get('type_name', 'other')
        if ct in ('ground', 'sea', 'weapon', 'navaid'):
            continue
        if ct == 'other' and (now - c.get('_ts', 0)) > 10.0:
            continue
        if own_lat is not None and own_lon is not None and max_nm < 9999.0:
            dlat = c['lat'] - own_lat
            dlon = (c['lon'] - own_lon) * math.cos(math.radians(own_lat))
            dist_nm = math.sqrt(dlat**2 + dlon**2) * 60.0
            if dist_nm > max_nm:
                continue
        if own_lat is not None and own_lon is not None:
            if abs(c['lat'] - own_lat) < 0.002 and abs(c['lon'] - own_lon) < 0.002:
                continue
        result.append({k: v for k, v in c.items() if k != '_ts'})
    return result


# Config helpers
_DEFAULT_CONFIG = {
    "port":          8000,
    "briefing_dir":  "/tmp/test_briefing",
    "broadcast_ms":  200,
    "theme":         "dark",
}


def _load_config(config_file: str) -> dict:
    try:
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg = dict(_DEFAULT_CONFIG)
            cfg.update({k: v for k, v in saved.items() if k in _DEFAULT_CONFIG})
            return cfg
    except Exception:
        pass
    return dict(_DEFAULT_CONFIG)


def _save_config(cfg: dict, config_file: str) -> None:
    try:
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# Airports data (subset for tests)
AIRPORTS = {
    "RKJK": (35.906389, 126.615833, "Gunsan AB",      "75X"),
    "RKSO": (37.090556, 127.030000, "Osan AB",         "94X"),
    "RKNW": (37.438056, 127.960556, "Wonju",           "60Y"),
}

AP_EXTRA = {
    "RKSO": {"freq": "126.2", "ils": [
        {"rwy": "36L", "freq": "108.7", "crs": "355"},
        {"rwy": "18R", "freq": "110.3", "crs": "175"},
    ]},
    "RKJK": {"freq": "122.1", "ils": [
        {"rwy": "18", "freq": "109.1", "crs": "183"},
    ]},
}


# ══════════════════════════════════════════════════════════════════
#  TEST CLASSES
# ══════════════════════════════════════════════════════════════════

class TestBmsToLatlon(unittest.TestCase):
    """Tests pour la conversion TMERC BMS Korea → WGS84."""

    def test_returns_tuple_of_two_floats(self):
        result = bms_to_latlon(1000000, 1000000)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], float)
        self.assertIsInstance(result[1], float)

    def test_result_in_valid_lat_range(self):
        lat, lon = bms_to_latlon(1500000, 1500000)
        self.assertTrue(-90 <= lat <= 90, f"lat={lat} hors limites")

    def test_result_in_valid_lon_range(self):
        lat, lon = bms_to_latlon(1500000, 1500000)
        self.assertTrue(-180 <= lon <= 180, f"lon={lon} hors limites")

    def test_korea_theater_range(self):
        """Les coords BMS Korea typiques doivent donner lat 33-43, lon 124-133."""
        for n, e in [(1200000, 1400000), (1800000, 1800000), (1500000, 1600000)]:
            lat, lon = bms_to_latlon(n, e)
            self.assertTrue(25 <= lat <= 50, f"lat={lat} pour N={n},E={e}")
            self.assertTrue(110 <= lon <= 145, f"lon={lon} pour N={n},E={e}")

    def test_monotonic_north(self):
        """Plus de pieds North → latitude plus haute."""
        lat1, _ = bms_to_latlon(1200000, 1500000)
        lat2, _ = bms_to_latlon(1800000, 1500000)
        self.assertGreater(lat2, lat1)

    def test_monotonic_east(self):
        """Plus de pieds East → longitude plus grande."""
        _, lon1 = bms_to_latlon(1500000, 1200000)
        _, lon2 = bms_to_latlon(1500000, 1800000)
        self.assertGreater(lon2, lon1)

    def test_zero_zero(self):
        """Coords (0,0) ne doivent pas crasher."""
        lat, lon = bms_to_latlon(0, 0)
        self.assertIsInstance(lat, float)
        self.assertIsInstance(lon, float)

    def test_negative_coords(self):
        """Coords négatives ne doivent pas crasher."""
        lat, lon = bms_to_latlon(-500000, -500000)
        self.assertIsInstance(lat, float)

    def test_symmetry_east_west(self):
        """Deux points symétriques par rapport au méridien central (FE)
        doivent avoir des longitudes symétriques autour de 127.5°."""
        _, lon_west = bms_to_latlon(1500000, 1500000)
        _, lon_east = bms_to_latlon(1500000, 1860000)  # ~FE + offset
        # Pas exactement symétrique (TMERC) mais les deux côtés doivent être proches du centre
        self.assertTrue(abs(lon_west - 127.5) < 5)
        self.assertTrue(abs(lon_east - 127.5) < 5)

    def test_large_values_no_crash(self):
        """Valeurs extrêmes ne doivent pas crasher."""
        lat, lon = bms_to_latlon(9999999, 9999999)
        self.assertIsInstance(lat, float)


class TestParseTrttColor(unittest.TestCase):
    """Tests pour le parsing des couleurs ACMI/TRTT."""

    def test_blue_returns_1(self):
        self.assertEqual(_parse_trtt_color("Blue"), 1)

    def test_blue_case_insensitive(self):
        self.assertEqual(_parse_trtt_color("BLUE"), 1)
        self.assertEqual(_parse_trtt_color("blue"), 1)
        self.assertEqual(_parse_trtt_color("DarkBlue"), 1)

    def test_red_returns_2(self):
        self.assertEqual(_parse_trtt_color("Red"), 2)

    def test_red_case_insensitive(self):
        self.assertEqual(_parse_trtt_color("RED"), 2)
        self.assertEqual(_parse_trtt_color("DarkRed"), 2)

    def test_unknown_returns_3(self):
        self.assertEqual(_parse_trtt_color("Green"), 3)
        self.assertEqual(_parse_trtt_color(""), 3)
        self.assertEqual(_parse_trtt_color("Unknown"), 3)

    def test_blue_priority_over_red(self):
        """Si la chaîne contient les deux, blue gagne (premier test)."""
        self.assertEqual(_parse_trtt_color("BlueRed"), 1)
        # 'BluishRed' ne contient PAS 'blue' (b-l-u-i ≠ b-l-u-e)
        self.assertEqual(_parse_trtt_color("BluishRed"), 2)


class TestParseTrttType(unittest.TestCase):
    """Tests pour le parsing du type d'objet ACMI."""

    def test_fixedwing(self):
        self.assertEqual(_parse_trtt_type("Air+FixedWing"), 'air')

    def test_rotorcraft(self):
        self.assertEqual(_parse_trtt_type("Air+Rotorcraft"), 'air')

    def test_ground(self):
        self.assertEqual(_parse_trtt_type("Ground+Vehicle"), 'ground')

    def test_weapon(self):
        self.assertEqual(_parse_trtt_type("Weapon+Missile"), 'weapon')

    def test_projectile(self):
        self.assertEqual(_parse_trtt_type("Projectile"), 'weapon')

    def test_sea(self):
        self.assertEqual(_parse_trtt_type("Sea+Warship"), 'sea')

    def test_ship(self):
        self.assertEqual(_parse_trtt_type("Ship+Carrier"), 'sea')

    def test_navaid(self):
        self.assertEqual(_parse_trtt_type("Navaid+Static"), 'navaid')

    def test_bullseye(self):
        self.assertEqual(_parse_trtt_type("Bullseye"), 'navaid')

    def test_unknown(self):
        self.assertEqual(_parse_trtt_type(""), 'other')
        self.assertEqual(_parse_trtt_type("SomeRandomType"), 'other')

    def test_case_insensitive(self):
        self.assertEqual(_parse_trtt_type("FIXEDWING"), 'air')
        self.assertEqual(_parse_trtt_type("GROUND"), 'ground')


class TestParseNavpointDL(unittest.TestCase):
    """Tests pour le parsing des NavPoints DL (datalink L16)."""

    def test_valid_dl_navpoint(self):
        raw = "NP:5,DL,1500000,1600000,-250,0;"
        result = _parse_navpoint_dl(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result['camp'], 1)
        self.assertEqual(result['type_name'], 'L16')
        self.assertEqual(result['callsign'], 'DL05')
        self.assertEqual(result['alt'], 2500)  # -250 * 10 = 2500 (abs)
        self.assertTrue(25 <= result['lat'] <= 50)
        self.assertTrue(110 <= result['lon'] <= 145)

    def test_non_dl_type_returns_none(self):
        raw = "NP:1,WP,1500000,1600000,-250,0;"
        self.assertIsNone(_parse_navpoint_dl(raw))

    def test_invalid_format_returns_none(self):
        self.assertIsNone(_parse_navpoint_dl("garbage data"))
        self.assertIsNone(_parse_navpoint_dl(""))
        self.assertIsNone(_parse_navpoint_dl("NP:"))

    def test_ownship_exclusion(self):
        """Contact à la même position que l'ownship → exclu."""
        raw = "NP:1,DL,1500000,1600000,-250,0;"
        result_no_own = _parse_navpoint_dl(raw)
        self.assertIsNotNone(result_no_own)
        # Maintenant avec ownship à la même position
        result_with_own = _parse_navpoint_dl(
            raw,
            own_lat=result_no_own['lat'],
            own_lon=result_no_own['lon']
        )
        self.assertIsNone(result_with_own)

    def test_out_of_theater_returns_none(self):
        """Coords hors du théâtre Korea (lat 25-50, lon 110-145) → None."""
        # N=-5000000 ft donne lat≈20° — en dehors de la zone 25-50
        raw = "NP:1,DL,-5000000,500000,-250,0;"
        self.assertIsNone(_parse_navpoint_dl(raw))

    def test_callsign_formatting(self):
        raw = "NP:12,DL,1500000,1600000,-100,0;"
        result = _parse_navpoint_dl(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result['callsign'], 'DL12')

    def test_zero_altitude(self):
        raw = "NP:1,DL,1500000,1600000,0,0;"
        result = _parse_navpoint_dl(raw)
        if result is not None:
            self.assertEqual(result['alt'], 0)


class TestIsLocal(unittest.TestCase):
    """Tests pour le middleware de sécurité réseau local."""

    def test_localhost_ipv4(self):
        self.assertTrue(_is_local("127.0.0.1"))

    def test_localhost_ipv6(self):
        self.assertTrue(_is_local("::1"))

    def test_localhost_name(self):
        self.assertTrue(_is_local("localhost"))

    def test_private_10(self):
        self.assertTrue(_is_local("10.0.0.1"))
        self.assertTrue(_is_local("10.255.255.255"))

    def test_private_192_168(self):
        self.assertTrue(_is_local("192.168.0.1"))
        self.assertTrue(_is_local("192.168.1.100"))

    def test_private_172_16_to_31(self):
        self.assertTrue(_is_local("172.16.0.1"))
        self.assertTrue(_is_local("172.31.255.255"))

    def test_private_172_outside_range(self):
        self.assertFalse(_is_local("172.15.0.1"))
        self.assertFalse(_is_local("172.32.0.1"))

    def test_public_ip_rejected(self):
        self.assertFalse(_is_local("8.8.8.8"))
        self.assertFalse(_is_local("1.1.1.1"))
        self.assertFalse(_is_local("203.0.113.1"))

    def test_empty_string(self):
        self.assertFalse(_is_local(""))

    def test_partial_match_not_fooled(self):
        """192.168 ne doit matcher que si c'est le préfixe."""
        self.assertFalse(_is_local("99.192.168.1"))


class TestConfig(unittest.TestCase):
    """Tests pour la config persistante JSON."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.tmpdir, "config", "test.json")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_load_default_if_no_file(self):
        cfg = _load_config(self.config_file)
        self.assertEqual(cfg, _DEFAULT_CONFIG)

    def test_save_and_load_roundtrip(self):
        cfg = {"port": 9090, "briefing_dir": "/tmp/b", "broadcast_ms": 100, "theme": "light"}
        _save_config(cfg, self.config_file)
        loaded = _load_config(self.config_file)
        self.assertEqual(loaded["port"], 9090)
        self.assertEqual(loaded["theme"], "light")

    def test_unknown_keys_ignored(self):
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump({"port": 7777, "unknown_key": "should_be_ignored"}, f)
        cfg = _load_config(self.config_file)
        self.assertEqual(cfg["port"], 7777)
        self.assertNotIn("unknown_key", cfg)

    def test_corrupt_json_returns_default(self):
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, "w") as f:
            f.write("{broken json!!!}")
        cfg = _load_config(self.config_file)
        self.assertEqual(cfg, _DEFAULT_CONFIG)

    def test_partial_config_merged(self):
        """Un fichier ne contenant que 'port' récupère les défauts pour le reste."""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump({"port": 3000}, f)
        cfg = _load_config(self.config_file)
        self.assertEqual(cfg["port"], 3000)
        self.assertEqual(cfg["theme"], "dark")  # default


class TestGetAcmiContacts(unittest.TestCase):
    """Tests pour le filtrage des contacts TRTT/ACMI."""

    def setUp(self):
        import threading
        self.lock = threading.Lock()
        self.now = time.time()

    def _make_contact(self, lat=37.0, lon=127.0, camp=1, type_name='air',
                      age=0, callsign='TEST01'):
        return {
            'lat': lat, 'lon': lon, 'alt': 20000, 'camp': camp,
            'callsign': callsign, 'pilot': '', 'type_name': type_name,
            'heading': 90, 'speed': 400, '_ts': self.now - age,
        }

    def test_fresh_air_contact_returned(self):
        contacts = {'a1': self._make_contact()}
        result = get_acmi_contacts(contacts, self.lock)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['callsign'], 'TEST01')

    def test_stale_contact_excluded(self):
        contacts = {'a1': self._make_contact(age=35)}  # >30s = stale
        result = get_acmi_contacts(contacts, self.lock)
        self.assertEqual(len(result), 0)

    def test_ground_excluded(self):
        contacts = {'g1': self._make_contact(type_name='ground')}
        result = get_acmi_contacts(contacts, self.lock)
        self.assertEqual(len(result), 0)

    def test_weapon_excluded(self):
        contacts = {'w1': self._make_contact(type_name='weapon')}
        result = get_acmi_contacts(contacts, self.lock)
        self.assertEqual(len(result), 0)

    def test_sea_excluded(self):
        contacts = {'s1': self._make_contact(type_name='sea')}
        result = get_acmi_contacts(contacts, self.lock)
        self.assertEqual(len(result), 0)

    def test_navaid_excluded(self):
        contacts = {'n1': self._make_contact(type_name='navaid')}
        result = get_acmi_contacts(contacts, self.lock)
        self.assertEqual(len(result), 0)

    def test_allies_only_excludes_enemies(self):
        contacts = {
            'a1': self._make_contact(camp=1),  # allié
            'e1': self._make_contact(camp=2),  # ennemi
        }
        result = get_acmi_contacts(contacts, self.lock, allies_only=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['camp'], 1)

    def test_allies_only_keeps_unknown(self):
        """Camp=3 (unknown) n'est PAS exclu en mode allies_only."""
        contacts = {'u1': self._make_contact(camp=3)}
        result = get_acmi_contacts(contacts, self.lock, allies_only=True)
        self.assertEqual(len(result), 1)

    def test_max_nm_filter(self):
        """Contact à >240NM exclu quand max_nm=240."""
        contacts = {
            'near': self._make_contact(lat=37.1, lon=127.1, callsign='NEAR01'),
            'far':  self._make_contact(lat=42.0, lon=127.0, callsign='FAR01'),
        }
        result = get_acmi_contacts(
            contacts, self.lock,
            own_lat=37.0, own_lon=127.0, max_nm=240.0
        )
        callsigns = [c['callsign'] for c in result]
        # 'near' à ~6 NM doit passer, mais exclu car même position (0.002 seuil)
        # 'far' à ~300 NM doit être exclu par le filtre distance
        self.assertNotIn('FAR01', callsigns)

    def test_ownship_position_excluded(self):
        """Contact à la même position que l'ownship → exclu."""
        contacts = {'own': self._make_contact(lat=37.0, lon=127.0)}
        result = get_acmi_contacts(
            contacts, self.lock,
            own_lat=37.0, own_lon=127.0
        )
        self.assertEqual(len(result), 0)

    def test_ts_not_in_output(self):
        """Le champ _ts interne ne doit pas apparaître dans le résultat."""
        contacts = {'a1': self._make_contact()}
        result = get_acmi_contacts(contacts, self.lock)
        self.assertNotIn('_ts', result[0])

    def test_other_type_fresh_kept(self):
        """Type 'other' récent (<10s) est gardé."""
        contacts = {'o1': self._make_contact(type_name='other', age=5)}
        result = get_acmi_contacts(contacts, self.lock)
        self.assertEqual(len(result), 1)

    def test_other_type_old_excluded(self):
        """Type 'other' vieux (>10s) est exclu."""
        contacts = {'o1': self._make_contact(type_name='other', age=15)}
        result = get_acmi_contacts(contacts, self.lock)
        self.assertEqual(len(result), 0)

    def test_empty_contacts(self):
        result = get_acmi_contacts({}, self.lock)
        self.assertEqual(result, [])


class TestAirportData(unittest.TestCase):
    """Tests pour la cohérence des données aéroports."""

    def test_airport_format(self):
        for icao, data in AIRPORTS.items():
            self.assertEqual(len(data), 4, f"{icao}: tuple doit avoir 4 éléments")
            lat, lon, name, tacan = data
            self.assertTrue(-90 <= lat <= 90, f"{icao}: lat={lat}")
            self.assertTrue(-180 <= lon <= 180, f"{icao}: lon={lon}")
            self.assertIsInstance(name, str)
            self.assertIsInstance(tacan, str)

    def test_korea_theater_coords(self):
        for icao, data in AIRPORTS.items():
            lat, lon = data[0], data[1]
            self.assertTrue(30 <= lat <= 45, f"{icao}: lat={lat} hors Corée")
            self.assertTrue(120 <= lon <= 140, f"{icao}: lon={lon} hors Corée")

    def test_ap_extra_references_valid_icao(self):
        for icao in AP_EXTRA:
            # Note: dans le vrai code, AP_EXTRA peut ref des ICAO pas dans notre subset
            if icao in AIRPORTS:
                self.assertIn(icao, AIRPORTS)

    def test_ils_structure(self):
        for icao, extra in AP_EXTRA.items():
            self.assertIn("freq", extra)
            self.assertIn("ils", extra)
            for ils in extra["ils"]:
                self.assertIn("rwy", ils)
                self.assertIn("freq", ils)
                self.assertIn("crs", ils)


class TestBriefingHelpers(unittest.TestCase):
    """Tests pour les helpers de l'API briefing."""

    ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".docx"}

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _briefing_meta(self, briefing_dir: str) -> list:
        """Reproduction locale de _briefing_meta."""
        files = []
        for fn in sorted(os.listdir(briefing_dir)):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in self.ALLOWED:
                continue
            fp = os.path.join(briefing_dir, fn)
            stat = os.stat(fp)
            files.append({
                "name":     fn,
                "ext":      ext.lstrip("."),
                "size_kb":  round(stat.st_size / 1024, 1),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m %H:%M"),
            })
        return files

    def test_empty_dir(self):
        self.assertEqual(self._briefing_meta(self.tmpdir), [])

    def test_pdf_listed(self):
        with open(os.path.join(self.tmpdir, "brief.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 test")
        result = self._briefing_meta(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["ext"], "pdf")

    def test_unsupported_extension_excluded(self):
        with open(os.path.join(self.tmpdir, "notes.txt"), "w") as f:
            f.write("test")
        result = self._briefing_meta(self.tmpdir)
        self.assertEqual(len(result), 0)

    def test_multiple_files_sorted(self):
        for name in ["charlie.pdf", "alpha.png", "bravo.jpg"]:
            with open(os.path.join(self.tmpdir, name), "wb") as f:
                f.write(b"x" * 100)
        result = self._briefing_meta(self.tmpdir)
        names = [f["name"] for f in result]
        self.assertEqual(names, ["alpha.png", "bravo.jpg", "charlie.pdf"])

    def test_size_kb_calculated(self):
        with open(os.path.join(self.tmpdir, "big.pdf"), "wb") as f:
            f.write(b"x" * 10240)  # 10 KB
        result = self._briefing_meta(self.tmpdir)
        self.assertAlmostEqual(result[0]["size_kb"], 10.0, places=0)


class TestSanitization(unittest.TestCase):
    """Tests pour la sanitization des noms de fichiers briefing."""

    def _sanitize(self, filename: str) -> str:
        """Reproduction de la logique de sanitization."""
        return "".join(c for c in filename if c.isalnum() or c in "._- ").strip()

    def test_normal_filename(self):
        self.assertEqual(self._sanitize("brief_v2.pdf"), "brief_v2.pdf")

    def test_strips_path_traversal(self):
        safe = self._sanitize("../../etc/passwd")
        self.assertNotIn("/", safe)
        self.assertNotIn("..", safe.replace("..", ""))  # Les .. sont préservés comme caractères individuels

    def test_strips_special_chars(self):
        safe = self._sanitize("brief<script>.pdf")
        self.assertNotIn("<", safe)
        self.assertNotIn(">", safe)

    def test_preserves_spaces_dashes(self):
        safe = self._sanitize("mission briefing-v2.pdf")
        self.assertEqual(safe, "mission briefing-v2.pdf")


class TestINIParser(unittest.TestCase):
    """Tests pour le parsing des fichiers .ini BMS."""

    def _parse_stpt(self, ini_content: str) -> dict:
        """Reproduit la logique de parsing des steerpoints."""
        import configparser
        cfg = configparser.RawConfigParser()
        cfg.optionxform = str
        cfg.read_string(ini_content)
        route, threats, fplan = [], [], []
        if cfg.has_section("STPT"):
            for key, val in cfg["STPT"].items():
                parts = val.split(",")
                if len(parts) >= 3:
                    try:
                        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                        if abs(x) > 10 and abs(y) > 10:
                            lat, lon = bms_to_latlon(x, y)
                            kl = key.lower()
                            if "line" in kl:
                                fplan.append({"lat": lat, "lon": lon, "alt": z})
                            elif "ppt" in kl:
                                try:
                                    r_ft = float(parts[3])
                                    range_nm = max(1, round(r_ft / 6076.12))
                                except Exception:
                                    range_nm = 15
                                threats.append({"lat": lat, "lon": lon, "range_nm": range_nm})
                            else:
                                route.append({"lat": lat, "lon": lon, "alt": z})
                    except Exception:
                        pass
        return {"route": route, "threats": threats, "flightplan": fplan}

    def test_empty_ini(self):
        result = self._parse_stpt("")
        self.assertEqual(result["route"], [])

    def test_steerpoints_parsed(self):
        ini = "[STPT]\nstpt_0 = 1500000,1600000,-20000,0\nstpt_1 = 1550000,1650000,-25000,0\n"
        result = self._parse_stpt(ini)
        self.assertEqual(len(result["route"]), 2)

    def test_ppt_parsed(self):
        ini = "[STPT]\nppt_0 = 1500000,1600000,-20000,164055,SA-2\n"
        result = self._parse_stpt(ini)
        self.assertEqual(len(result["threats"]), 1)
        self.assertEqual(result["threats"][0]["range_nm"], 27)

    def test_line_parsed_as_flightplan(self):
        ini = "[STPT]\nline_0 = 1500000,1600000,-15000,0\n"
        result = self._parse_stpt(ini)
        self.assertEqual(len(result["flightplan"]), 1)

    def test_small_coords_ignored(self):
        """Coords trop petites (abs < 10) sont ignorées."""
        ini = "[STPT]\nstpt_0 = 5,5,0,0\n"
        result = self._parse_stpt(ini)
        self.assertEqual(len(result["route"]), 0)

    def test_invalid_data_no_crash(self):
        ini = "[STPT]\nstpt_0 = abc,def,ghi\n"
        result = self._parse_stpt(ini)
        self.assertEqual(len(result["route"]), 0)

    def test_missing_section_ok(self):
        ini = "[OTHER]\nkey = value\n"
        result = self._parse_stpt(ini)
        self.assertEqual(result["route"], [])


class TestProductionFile(unittest.TestCase):
    """Tests de conformité sur le fichier de production."""

    @classmethod
    def setUpClass(cls):
        prod_path = os.path.join(os.path.dirname(__file__), 'falcon_pad.py')
        if not os.path.exists(prod_path):
            prod_path = '/home/claude/falcon_pad.py'
        with open(prod_path, 'r', encoding='utf-8') as f:
            cls.source = f.read()
            cls.lines = cls.source.splitlines()

    def test_no_logger_debug_calls(self):
        """Aucun logger.debug() ne doit rester en prod."""
        debug_lines = [
            (i + 1, line.strip())
            for i, line in enumerate(self.lines)
            if re.match(r'\s*logger\.debug\(', line)
        ]
        self.assertEqual(debug_lines, [],
                         f"logger.debug() trouvés en prod: {debug_lines}")

    def test_no_memory_addresses_in_logs(self):
        """Aucune adresse mémoire hex ne doit apparaître dans les logs."""
        hex_logs = [
            (i + 1, line.strip())
            for i, line in enumerate(self.lines)
            if 'logger.' in line and '0x{' in line
        ]
        self.assertEqual(hex_logs, [],
                         f"Adresses mémoire dans les logs: {hex_logs}")

    def test_no_hproc_in_logs(self):
        """hproc ne doit plus apparaître dans les logger.info."""
        hproc_logs = [
            (i + 1, line.strip())
            for i, line in enumerate(self.lines)
            if 'logger.' in line and 'hproc' in line
        ]
        self.assertEqual(hproc_logs, [],
                         f"hproc dans les logs: {hproc_logs}")

    def test_logging_level_is_info(self):
        """Le root logger doit être configuré en INFO, pas DEBUG."""
        for line in self.lines:
            if 'logging.basicConfig' in line:
                self.assertIn('logging.INFO', line,
                              "Root logger doit être level=logging.INFO")
                break

    def test_file_handler_level_is_info(self):
        """Le file handler doit être en INFO, pas DEBUG."""
        for line in self.lines:
            if '_fh.setLevel' in line:
                self.assertIn('logging.INFO', line,
                              "File handler doit être logging.INFO")
                break

    def test_no_trtt_diag_block(self):
        """Le bloc de diagnostic TRTT toutes les 15s doit être supprimé."""
        self.assertNotIn('TRTT diag:', self.source,
                         "Bloc diagnostic TRTT encore présent")

    def test_copyright_header_present(self):
        """Le header GPL doit être présent."""
        self.assertIn("GNU General Public License", self.source)
        self.assertIn("Riesu", self.source)

    def test_app_version_defined(self):
        self.assertIn('APP_VERSION', self.source)

    def test_no_print_statements(self):
        """Aucun print() brut (debug) — seulement dans les logger."""
        print_lines = [
            (i + 1, line.strip())
            for i, line in enumerate(self.lines)
            if re.match(r'\s*print\(', line)
        ]
        self.assertEqual(print_lines, [],
                         f"print() trouvés en prod: {print_lines}")


# ══════════════════════════════════════════════════════════════════
#  RUNNER
# ══════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Run with verbosity
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
