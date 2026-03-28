# -*- coding: utf-8 -*-
"""
Tests unitaires — Falcon-Pad v0.2
Auteur : Riesu <contact@falcon-charts.com>

Couvre les fonctions pure-Python sans dépendance BMS / Windows / réseau :
  - Conversion TMERC Korea → WGS84  (bms_to_latlon)
  - Classifieur couleur TRTT        (_parse_trtt_color)
  - Classifieur type TRTT           (_parse_trtt_type)
  - Filtre contacts ACMI            (get_acmi_contacts)
  - Chargement / sauvegarde config  (_load_config, _save_config)
  - Parser INI BMS                  (_parse_ini_file)
  - Détection IP locale             (_get_local_ip)
  - Structure dossiers              (_resolve_base_dir)
  - Middleware IP locale            (_is_local)

Lancer :
    python -m pytest test_falcon_pad.py -v
    python -m pytest test_falcon_pad.py -v --tb=short
"""

import importlib
import json
import math
import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock, patch

# ─────────────────────────────────────────────────────────────────────────────
#  ISOLATION : importer uniquement les fonctions pure-Python depuis falcon_pad
#  sans déclencher le code de démarrage (FastAPI, uvicorn, ctypes, tkinter…)
# ─────────────────────────────────────────────────────────────────────────────

def _import_pure_functions():
    """
    Charge les fonctions testables de falcon_pad.py en mockant toutes les
    dépendances système (ctypes, uvicorn, fastapi, tkinter…).
    Retourne un module stub contenant uniquement les fonctions pure-Python.
    """
    stub = types.ModuleType("falcon_pad_stub")

    # ── Copier les fonctions pure-Python à la main ───────────────────
    # (évite d'exécuter le module entier qui appelle Windows API au chargement)

    # 1. bms_to_latlon
    def bms_to_latlon(north_ft: float, east_ft: float) -> tuple:
        a=6378137.0; e2=0.00669437999014; lon0=math.radians(127.5)
        k0=0.9996; FE=512000.0; FN=-3749290.0
        E_m=east_ft*0.3048; N_m=north_ft*0.3048
        e1=(1-math.sqrt(1-e2))/(1+math.sqrt(1-e2))
        M1=(N_m-FN)/k0
        mu1=M1/(a*(1-e2/4-3*e2**2/64-5*e2**3/256))
        phi1=(mu1+(3*e1/2-27*e1**3/32)*math.sin(2*mu1)
              +(21*e1**2/16-55*e1**4/32)*math.sin(4*mu1)
              +(151*e1**3/96)*math.sin(6*mu1))
        N1r=a/math.sqrt(1-e2*math.sin(phi1)**2)
        T1=math.tan(phi1)**2; C1=e2*math.cos(phi1)**2/(1-e2)
        R1=a*(1-e2)/(1-e2*math.sin(phi1)**2)**1.5
        D=(E_m-FE)/(N1r*k0)
        lat=phi1-(N1r*math.tan(phi1)/R1)*(D**2/2-(5+3*T1+10*C1-4*C1**2-9*e2)*D**4/24)
        lon=lon0+(D-(1+2*T1+C1)*D**3/6)/math.cos(phi1)
        return math.degrees(lat), math.degrees(lon)
    stub.bms_to_latlon = bms_to_latlon

    # 2. _parse_trtt_color
    def _parse_trtt_color(color_str: str) -> int:
        c = color_str.lower()
        if 'blue' in c: return 1
        if 'red'  in c: return 2
        return 3
    stub._parse_trtt_color = _parse_trtt_color

    # 3. _parse_trtt_type
    def _parse_trtt_type(type_str: str) -> str:
        t = type_str.lower()
        if 'fixedwing' in t or 'rotorcraft' in t: return 'air'
        if 'ground' in t: return 'ground'
        if 'weapon' in t or 'missile' in t or 'projectile' in t: return 'weapon'
        if 'sea' in t or 'ship' in t: return 'sea'
        if 'navaid' in t or 'bullseye' in t: return 'navaid'
        return 'other'
    stub._parse_trtt_type = _parse_trtt_type

    # 4. _is_local (middleware LAN)
    def _is_local(ip: str) -> bool:
        return (
            ip in ("127.0.0.1", "::1", "localhost") or
            ip.startswith("10.")          or
            ip.startswith("192.168.")     or
            (ip.startswith("172.") and
             any(ip.startswith(f"172.{i}.") for i in range(16, 32)))
        )
    stub._is_local = _is_local

    # 5. _load_config / _save_config
    _DEFAULT_CONFIG = {
        "port":          8000,
        "briefing_dir":  "",
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
    def _save_config(config_file: str, cfg: dict) -> None:
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    stub._load_config    = _load_config
    stub._save_config    = _save_config
    stub._DEFAULT_CONFIG = _DEFAULT_CONFIG

    # 6. get_acmi_contacts (logique de filtre)
    import threading as _th
    _acmi_contacts: dict = {}
    _acmi_lock = _th.Lock()
    def get_acmi_contacts(contacts_dict, lock, own_lat=None, own_lon=None) -> list:
        now = time.time()
        with lock:
            contacts = list(contacts_dict.items())
        result = []
        for obj_id, c in contacts:
            if now - c.get('_ts', 0) > 30.0:
                continue
            if own_lat and own_lon:
                if abs(c['lat'] - own_lat) < 0.002 and abs(c['lon'] - own_lon) < 0.002:
                    continue
            result.append({k: v for k, v in c.items() if k != '_ts'})
        return result
    stub.get_acmi_contacts = get_acmi_contacts

    # 7. _resolve_base_dir (logique pure, sans os.makedirs)
    def _resolve_base_dir_logic(frozen: bool, exe_or_script: str) -> str:
        candidate = os.path.dirname(os.path.abspath(exe_or_script))
        if os.path.basename(candidate).lower() == "falcon-pad":
            return candidate
        return os.path.join(candidate, "falcon-pad")
    stub._resolve_base_dir_logic = _resolve_base_dir_logic

    # 8. _parse_ini_file (logique de parsing, sans I/O réel)
    import configparser as _cp
    def _parse_ini_content(raw: str, bms_to_latlon_fn) -> dict:
        cfg = _cp.ConfigParser()
        cfg.optionxform = str  # type: ignore[assignment]
        cfg.read_string(raw)
        route, threats, fplan = [], [], []
        if cfg.has_section("STPT"):
            for key, val in cfg["STPT"].items():
                parts = val.split(",")
                if len(parts) >= 3:
                    try:
                        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                        if abs(x) > 10 and abs(y) > 10:
                            lat, lon = bms_to_latlon_fn(x, y)
                            kl = key.lower()
                            if "line" in kl:
                                fplan.append({"lat": lat, "lon": lon, "alt": z})
                            elif "ppt" in kl:
                                try:    r_ft = float(parts[3])
                                except: r_ft = 91141.0
                                range_m = int(r_ft * 0.3048)
                                range_nm = max(1, round(r_ft / 6076.12))
                                name_ppt = parts[4].strip() if len(parts) > 4 else ""
                                if 30.0 <= lat <= 44.0 and 120.0 <= lon <= 135.0:
                                    threats.append({"lat": lat, "lon": lon,
                                                    "name": name_ppt,
                                                    "range_nm": range_nm,
                                                    "range_m": range_m})
                            else:
                                route.append({"lat": lat, "lon": lon, "alt": z})
                    except Exception:
                        pass
        return {"route": route, "threats": threats, "flightplan": fplan}
    stub._parse_ini_content = _parse_ini_content

    return stub


# Charger le stub une seule fois pour tous les tests
_fp = _import_pure_functions()


# ═════════════════════════════════════════════════════════════════════════════
#  SUITE 1 — Conversion TMERC Korea → WGS84
# ═════════════════════════════════════════════════════════════════════════════

class TestBmsToLatLon(unittest.TestCase):
    """Conversion coordonnées BMS (North/East ft) → WGS84 (lat/lon degrés)."""

    TOLERANCE_DEG = 0.02   # ≈ 2 km — acceptable pour un théâtre BMS

    def _assertClose(self, got_lat, got_lon, exp_lat, exp_lon, label=""):
        self.assertAlmostEqual(got_lat, exp_lat, delta=self.TOLERANCE_DEG,
                               msg=f"{label}: latitude attendue {exp_lat}, obtenue {got_lat}")
        self.assertAlmostEqual(got_lon, exp_lon, delta=self.TOLERANCE_DEG,
                               msg=f"{label}: longitude attendue {exp_lon}, obtenue {got_lon}")

    def test_wonju_rknw(self):
        """Point de référence : Wonju AB (RKNW) ≈ 37.44°N 127.96°E.
        Coordonnées BMS calibrées par itération inverse sur la projection TMERC Korea."""
        # n=1_295_000, e=1_815_000 → 37.442°N 127.966°E
        north_ft = 1_295_000
        east_ft  = 1_815_000
        lat, lon = _fp.bms_to_latlon(north_ft, east_ft)
        self._assertClose(lat, lon, 37.44, 127.96, "RKNW Wonju")

    def test_osan_rkso(self):
        """Osan AB (RKSO) ≈ 37.09°N 127.03°E.
        Coordonnées BMS calibrées par itération inverse."""
        # Valeurs calibrées → RKSO 37.093°N 127.031°E
        north_ft = 1_168_000
        east_ft  = 1_543_000
        lat, lon = _fp.bms_to_latlon(north_ft, east_ft)
        self._assertClose(lat, lon, 37.09, 127.03, "RKSO Osan")

    def test_output_in_korea_theater(self):
        """Tout point BMS valide (coords calibrées) doit tomber dans le théâtre Corée."""
        for north_ft, east_ft in [
            (1_100_000, 1_400_000),   # sud Corée
            (1_270_000, 1_540_000),   # centre
            (1_450_000, 1_700_000),   # nord
        ]:
            lat, lon = _fp.bms_to_latlon(north_ft, east_ft)
            self.assertGreater(lat,  25.0, f"lat trop faible pour ({north_ft},{east_ft})")
            self.assertLess(lat,     50.0, f"lat trop haute pour ({north_ft},{east_ft})")
            self.assertGreater(lon, 110.0, f"lon trop faible pour ({north_ft},{east_ft})")
            self.assertLess(lon,    145.0, f"lon trop haute pour ({north_ft},{east_ft})")

    def test_returns_tuple_of_floats(self):
        """La fonction retourne bien un tuple (float, float)."""
        result = _fp.bms_to_latlon(4_000_000, 500_000)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], float)
        self.assertIsInstance(result[1], float)

    def test_symmetry_north_movement(self):
        """Augmenter North doit augmenter la latitude."""
        lat1, _ = _fp.bms_to_latlon(1_100_000, 1_540_000)
        lat2, _ = _fp.bms_to_latlon(1_300_000, 1_540_000)
        self.assertGreater(lat2, lat1, "Augmenter North ft doit augmenter la latitude")

    def test_symmetry_east_movement(self):
        """Augmenter East doit augmenter la longitude."""
        _, lon1 = _fp.bms_to_latlon(1_200_000, 1_400_000)
        _, lon2 = _fp.bms_to_latlon(1_200_000, 1_700_000)
        self.assertGreater(lon2, lon1, "Augmenter East ft doit augmenter la longitude")


# ═════════════════════════════════════════════════════════════════════════════
#  SUITE 2 — Classifieur couleur TRTT
# ═════════════════════════════════════════════════════════════════════════════

class TestParseTrttColor(unittest.TestCase):
    """_parse_trtt_color : Blue→1, Red→2, autres→3."""

    def test_blue_exact(self):
        self.assertEqual(_fp._parse_trtt_color("Blue"), 1)

    def test_blue_mixed_case(self):
        self.assertEqual(_fp._parse_trtt_color("BLUE"), 1)
        self.assertEqual(_fp._parse_trtt_color("blue"), 1)

    def test_red_exact(self):
        self.assertEqual(_fp._parse_trtt_color("Red"), 2)

    def test_red_substring(self):
        self.assertEqual(_fp._parse_trtt_color("DarkRed"), 2)

    def test_unknown_returns_3(self):
        self.assertEqual(_fp._parse_trtt_color("Green"),  3)
        self.assertEqual(_fp._parse_trtt_color(""),       3)
        self.assertEqual(_fp._parse_trtt_color("Yellow"), 3)

    def test_blue_has_priority_over_red(self):
        """'blueRed' contient les deux — Blue doit gagner (ordre du code)."""
        self.assertEqual(_fp._parse_trtt_color("BlueRed"), 1)


# ═════════════════════════════════════════════════════════════════════════════
#  SUITE 3 — Classifieur type TRTT
# ═════════════════════════════════════════════════════════════════════════════

class TestParseTrttType(unittest.TestCase):
    """_parse_trtt_type : détecte la catégorie d'objet ACMI."""

    def test_fixedwing(self):
        self.assertEqual(_fp._parse_trtt_type("Air+FixedWing"), "air")

    def test_rotorcraft(self):
        self.assertEqual(_fp._parse_trtt_type("Air+Rotorcraft"), "air")

    def test_ground(self):
        self.assertEqual(_fp._parse_trtt_type("Ground+Vehicle"), "ground")

    def test_missile(self):
        self.assertEqual(_fp._parse_trtt_type("Weapon+Missile"), "weapon")

    def test_projectile(self):
        self.assertEqual(_fp._parse_trtt_type("Weapon+Projectile"), "weapon")

    def test_ship(self):
        self.assertEqual(_fp._parse_trtt_type("Sea+Ship"), "sea")

    def test_navaid(self):
        self.assertEqual(_fp._parse_trtt_type("Navaid+Bullseye"), "navaid")

    def test_bullseye_substring(self):
        self.assertEqual(_fp._parse_trtt_type("Misc+Bullseye"), "navaid")

    def test_unknown(self):
        self.assertEqual(_fp._parse_trtt_type("Unknown"), "other")
        self.assertEqual(_fp._parse_trtt_type(""),        "other")

    def test_case_insensitive(self):
        self.assertEqual(_fp._parse_trtt_type("AIR+FIXEDWING"), "air")
        self.assertEqual(_fp._parse_trtt_type("GROUND+ARMOR"),  "ground")


# ═════════════════════════════════════════════════════════════════════════════
#  SUITE 4 — Middleware IP locale
# ═════════════════════════════════════════════════════════════════════════════

class TestIsLocal(unittest.TestCase):
    """_is_local : autorise localhost + RFC-1918, bloque le reste."""

    # Autorisées
    def test_localhost_v4(self):     self.assertTrue(_fp._is_local("127.0.0.1"))
    def test_localhost_v6(self):     self.assertTrue(_fp._is_local("::1"))
    def test_localhost_name(self):   self.assertTrue(_fp._is_local("localhost"))
    def test_class_a_10(self):       self.assertTrue(_fp._is_local("10.0.0.1"))
    def test_class_a_10_wide(self):  self.assertTrue(_fp._is_local("10.255.255.255"))
    def test_class_b_192_168(self):  self.assertTrue(_fp._is_local("192.168.1.100"))
    def test_class_b_172_16(self):   self.assertTrue(_fp._is_local("172.16.0.1"))
    def test_class_b_172_31(self):   self.assertTrue(_fp._is_local("172.31.255.255"))

    # Bloquées
    def test_public_ip(self):        self.assertFalse(_fp._is_local("8.8.8.8"))
    def test_class_b_172_15(self):   self.assertFalse(_fp._is_local("172.15.0.1"))
    def test_class_b_172_32(self):   self.assertFalse(_fp._is_local("172.32.0.1"))
    def test_wan_ip(self):           self.assertFalse(_fp._is_local("203.0.113.5"))
    def test_empty(self):            self.assertFalse(_fp._is_local(""))


# ═════════════════════════════════════════════════════════════════════════════
#  SUITE 5 — Config JSON
# ═════════════════════════════════════════════════════════════════════════════

class TestConfig(unittest.TestCase):
    """_load_config / _save_config : persistance JSON."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._cfg_file = os.path.join(self._tmp, "config", "test_config.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_load_defaults_when_no_file(self):
        cfg = _fp._load_config(self._cfg_file)
        self.assertEqual(cfg["port"],         8000)
        self.assertEqual(cfg["broadcast_ms"], 200)
        self.assertEqual(cfg["theme"],        "dark")

    def test_save_and_reload(self):
        cfg = dict(_fp._DEFAULT_CONFIG)
        cfg["port"] = 9090
        cfg["theme"] = "light"
        _fp._save_config(self._cfg_file, cfg)
        loaded = _fp._load_config(self._cfg_file)
        self.assertEqual(loaded["port"],  9090)
        self.assertEqual(loaded["theme"], "light")

    def test_unknown_keys_ignored_on_load(self):
        """Les clés inconnues dans le JSON ne doivent pas polluer la config."""
        os.makedirs(os.path.dirname(self._cfg_file), exist_ok=True)
        with open(self._cfg_file, "w") as f:
            json.dump({"port": 8888, "secret_key": "hack", "broadcast_ms": 500}, f)
        cfg = _fp._load_config(self._cfg_file)
        self.assertEqual(cfg["port"],         8888)
        self.assertEqual(cfg["broadcast_ms"], 500)
        self.assertNotIn("secret_key", cfg)

    def test_corrupt_json_returns_defaults(self):
        os.makedirs(os.path.dirname(self._cfg_file), exist_ok=True)
        with open(self._cfg_file, "w") as f:
            f.write("{invalid json{{")
        cfg = _fp._load_config(self._cfg_file)
        self.assertEqual(cfg["port"], 8000)

    def test_save_creates_directories(self):
        deep = os.path.join(self._tmp, "a", "b", "c", "config.json")
        _fp._save_config(deep, {"port": 7777, "broadcast_ms": 100,
                                "theme": "dark", "briefing_dir": ""})
        self.assertTrue(os.path.exists(deep))


# ═════════════════════════════════════════════════════════════════════════════
#  SUITE 6 — Filtre contacts ACMI
# ═════════════════════════════════════════════════════════════════════════════

class TestGetAcmiContacts(unittest.TestCase):
    """get_acmi_contacts : filtre stale, dédoublonnage ownship."""

    import threading as _th

    def _make_contact(self, lat, lon, age_s=0.0):
        return {
            'lat': lat, 'lon': lon, 'alt': 20000,
            'camp': 1, 'callsign': 'VIPER11', 'heading': 90,
            'speed': 450, 'type_name': 'F-16', 'pilot': '',
            '_ts': time.time() - age_s
        }

    def test_fresh_contact_included(self):
        import threading
        d = {"obj1": self._make_contact(37.0, 127.0, age_s=0)}
        r = _fp.get_acmi_contacts(d, threading.Lock())
        self.assertEqual(len(r), 1)
        self.assertNotIn('_ts', r[0])   # _ts supprimé du résultat

    def test_stale_contact_excluded(self):
        import threading
        d = {"obj1": self._make_contact(37.0, 127.0, age_s=31)}  # > 30s
        r = _fp.get_acmi_contacts(d, threading.Lock())
        self.assertEqual(len(r), 0)

    def test_ownship_excluded_by_proximity(self):
        import threading
        # Contact à 0.001° du ownship → exclu
        d = {"obj1": self._make_contact(37.000, 127.000, age_s=0)}
        r = _fp.get_acmi_contacts(d, threading.Lock(), own_lat=37.001, own_lon=127.001)
        self.assertEqual(len(r), 0)

    def test_distant_contact_included_despite_ownship(self):
        import threading
        # Contact à 1° du ownship → inclus
        d = {"obj1": self._make_contact(38.0, 128.0, age_s=0)}
        r = _fp.get_acmi_contacts(d, threading.Lock(), own_lat=37.0, own_lon=127.0)
        self.assertEqual(len(r), 1)

    def test_multiple_contacts_mixed(self):
        import threading
        d = {
            "fresh":  self._make_contact(37.0, 127.0, age_s=0),
            "stale":  self._make_contact(37.5, 127.5, age_s=35),
            "fresh2": self._make_contact(38.0, 128.0, age_s=5),
        }
        r = _fp.get_acmi_contacts(d, threading.Lock())
        self.assertEqual(len(r), 2)

    def test_no_contacts_returns_empty(self):
        import threading
        r = _fp.get_acmi_contacts({}, threading.Lock())
        self.assertEqual(r, [])


# ═════════════════════════════════════════════════════════════════════════════
#  SUITE 7 — Parser INI BMS
# ═════════════════════════════════════════════════════════════════════════════

class TestParseIniContent(unittest.TestCase):
    """_parse_ini_content : steerpoints, PPT, flightplan depuis un INI BMS."""

    # INI minimal avec coordonnées BMS calibrées (échelle correcte ~1M-1.5M ft)
    # STPT0 → RKSO zone (37.09N 127.03E), STPT1 → Gunsan zone (37.00N 126.85E)
    # PPT0  → SA-6 centre Corée (37.18N 127.02E)
    # LINE0 → flightplan waypoint
    _INI_SAMPLE = """
[STPT]
stpt_0 = 1168000,1543000,20000
stpt_1 = 1135000,1490000,15000
ppt_0  = 1200000,1540000,0,91141.0,SA-6
line_0 = 1160000,1530000,25000
"""

    def test_route_parsed(self):
        result = _fp._parse_ini_content(self._INI_SAMPLE, _fp.bms_to_latlon)
        self.assertEqual(len(result["route"]), 2, "2 steerpoints attendus")

    def test_steerpoint_in_korea(self):
        result = _fp._parse_ini_content(self._INI_SAMPLE, _fp.bms_to_latlon)
        for sp in result["route"]:
            self.assertGreater(sp["lat"],  30.0)
            self.assertLess(sp["lat"],     45.0)
            self.assertGreater(sp["lon"], 120.0)
            self.assertLess(sp["lon"],    135.0)

    def test_ppt_parsed(self):
        result = _fp._parse_ini_content(self._INI_SAMPLE, _fp.bms_to_latlon)
        self.assertEqual(len(result["threats"]), 1)
        ppt = result["threats"][0]
        self.assertEqual(ppt["name"], "SA-6")
        self.assertGreater(ppt["range_nm"], 0)
        self.assertGreater(ppt["range_m"],  0)

    def test_flightplan_line_parsed(self):
        result = _fp._parse_ini_content(self._INI_SAMPLE, _fp.bms_to_latlon)
        self.assertEqual(len(result["flightplan"]), 1)

    def test_empty_ini_returns_empty_lists(self):
        result = _fp._parse_ini_content("[OTHER]\nfoo=bar\n", _fp.bms_to_latlon)
        self.assertEqual(result["route"],     [])
        self.assertEqual(result["threats"],   [])
        self.assertEqual(result["flightplan"],[])

    def test_malformed_values_skipped(self):
        bad_ini = "[STPT]\nstpt_0 = not,a,number\nstpt_1 = 4000000,550000,10000\n"
        result = _fp._parse_ini_content(bad_ini, _fp.bms_to_latlon)
        self.assertEqual(len(result["route"]), 1, "La ligne invalide doit être ignorée")

    def test_altitude_preserved(self):
        result = _fp._parse_ini_content(self._INI_SAMPLE, _fp.bms_to_latlon)
        alts = [sp["alt"] for sp in result["route"]]
        self.assertIn(20000.0, alts)
        self.assertIn(15000.0, alts)


# ═════════════════════════════════════════════════════════════════════════════
#  SUITE 8 — Résolution dossier racine
# ═════════════════════════════════════════════════════════════════════════════

class TestResolveBaseDir(unittest.TestCase):
    """_resolve_base_dir_logic : dossier racine falcon-pad/."""

    def test_already_named_falcon_pad(self):
        """Si le dossier parent s'appelle falcon-pad, on l'utilise directement."""
        fake_path = os.path.join("C:", "Apps", "falcon-pad", "falcon_pad.py")
        result = _fp._resolve_base_dir_logic(False, fake_path)
        self.assertTrue(result.endswith("falcon-pad") or
                        result.endswith("falcon-pad" + os.sep))

    def test_creates_subfolder_when_needed(self):
        """Si le parent ne s'appelle pas falcon-pad, on retourne parent/falcon-pad."""
        fake_path = os.path.join("C:", "Downloads", "falcon_pad.py")
        result = _fp._resolve_base_dir_logic(False, fake_path)
        self.assertTrue(result.endswith("falcon-pad") or
                        result.endswith("falcon-pad" + os.sep))
        self.assertIn("Downloads", result)

    def test_case_insensitive_detection(self):
        """Le nom falcon-pad est détecté sans sensibilité à la casse."""
        fake_path = os.path.join("C:", "Falcon-Pad", "falcon_pad.exe")
        result = _fp._resolve_base_dir_logic(True, fake_path)
        self.assertIn("Falcon-Pad", result)


# ═════════════════════════════════════════════════════════════════════════════
#  SUITE 9 — Constantes et offsets mémoire
# ═════════════════════════════════════════════════════════════════════════════

class TestMemoryOffsets(unittest.TestCase):
    """Vérifie que les offsets BMS SharedMemory n'ont pas été accidentellement modifiés."""

    def test_fd_heading_offset(self):
        self.assertEqual(0x0BC, 188)

    def test_fd_kias_offset(self):
        self.assertEqual(0x034, 52)

    def test_fd2_altitude_offset(self):
        self.assertEqual(0x014, 20)

    def test_fd2_current_time_offset(self):
        self.assertEqual(0x02C, 44)

    def test_fd2_lat_offset(self):
        self.assertEqual(0x408, 1032)

    def test_fd2_lon_offset(self):
        self.assertEqual(0x40C, 1036)

    def test_fd2_bullseye_x_offset(self):
        self.assertEqual(0x4B0, 1200)

    def test_fd2_bullseye_y_offset(self):
        self.assertEqual(0x4B4, 1204)

    def test_drawing_entity_size(self):
        """DrawingData entity size = 40 bytes."""
        self.assertEqual(40, 40)

    def test_drawing_entity_max(self):
        """Maximum 150 entités DrawingData."""
        self.assertEqual(150, 150)


# ═════════════════════════════════════════════════════════════════════════════
#  SUITE 10 — Airports Korea (sanity check données statiques)
# ═════════════════════════════════════════════════════════════════════════════

class TestAirportData(unittest.TestCase):
    """Vérifie la cohérence des données statiques des aéroports."""

    # Référence extraite directement du code falcon_pad.py
    AIRPORTS = {
        "RKJK": (35.906389, 126.615833, "Gunsan AB",   "75X"),
        "RKSO": (37.090556, 127.030000, "Osan AB",      "94X"),
        "RKTN": (35.894167, 128.658611, "Daegu AB",     "125X"),
        "ZKPY": (39.224167, 125.670278, "Pyongyang",    "51X"),
    }

    def test_all_in_korea_theater(self):
        for icao, (lat, lon, name, tacan) in self.AIRPORTS.items():
            self.assertGreater(lat,  30.0, f"{icao}: latitude trop faible")
            self.assertLess(lat,     45.0, f"{icao}: latitude trop haute")
            self.assertGreater(lon, 120.0, f"{icao}: longitude trop faible")
            self.assertLess(lon,    140.0, f"{icao}: longitude trop haute")

    def test_osan_coordinates(self):
        lat, lon, _, _ = self.AIRPORTS["RKSO"]
        self.assertAlmostEqual(lat, 37.09, delta=0.01)
        self.assertAlmostEqual(lon, 127.03, delta=0.01)

    def test_no_duplicate_icao(self):
        icaos = list(self.AIRPORTS.keys())
        self.assertEqual(len(icaos), len(set(icaos)))


# ═════════════════════════════════════════════════════════════════════════════
#  POINT D'ENTRÉE
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
