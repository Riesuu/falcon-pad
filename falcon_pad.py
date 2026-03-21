# -*- coding: utf-8 -*-
"""
Falcon-Pad — Tactical companion app for Falcon BMS
Copyright (C) 2024  Riesu <contact@falcon-charts.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

---
Falcon-Pad by Riesu
Contact : contact@falcon-charts.com
Website : https://www.falcon-charts.com
GitHub  : https://github.com/riesu/falcon-pad
BMS     : Falcon BMS 4.38 — Shared Memory SDK
"""

from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn, asyncio, json, ctypes, configparser, math, struct, os, sys
from datetime import datetime
from typing import List, Optional, Dict
import logging

APP_NAME    = "Falcon-Pad"
APP_VERSION = "0.3"
APP_AUTHOR  = "Riesu"
APP_CONTACT = "contact@falcon-charts.com"
APP_WEBSITE = "https://www.falcon-charts.com"

# ── Dossiers de base ─────────────────────────────────────────
# Structure cible : falcon-pad/ logs/ briefing/ config/ assets/
def _resolve_base_dir() -> str:
    if getattr(sys, "frozen", False):
        candidate = os.path.dirname(os.path.abspath(sys.executable))
    else:
        candidate = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(candidate).lower() == "falcon-pad":
        return candidate
    fp_dir = os.path.join(candidate, "falcon-pad")
    os.makedirs(fp_dir, exist_ok=True)
    return fp_dir

_BASE_DIR    = _resolve_base_dir()
ASSETS_DIR   = os.path.join(_BASE_DIR, "assets")
LOG_DIR      = os.path.join(_BASE_DIR, "logs")
BRIEFING_DIR = os.path.join(_BASE_DIR, "briefing")
_CONFIG_DIR  = os.path.join(_BASE_DIR, "config")
CONFIG_FILE  = os.path.join(_CONFIG_DIR, "falcon_pad_config.json")

for _d in (ASSETS_DIR, LOG_DIR, BRIEFING_DIR, _CONFIG_DIR):
    os.makedirs(_d, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, f"falcon_pad_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# ── Config persistante ───────────────────────────────────────────
import json as _json

_DEFAULT_CONFIG = {
    "port":          8000,
    "briefing_dir":  BRIEFING_DIR,
    "broadcast_ms":  200,
    "theme":         "dark",
}

def _load_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = _json.load(f)
            cfg = dict(_DEFAULT_CONFIG)
            cfg.update({k: v for k, v in saved.items() if k in _DEFAULT_CONFIG})
            return cfg
    except Exception:
        pass
    return dict(_DEFAULT_CONFIG)

def _save_config(cfg: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            _json.dump(cfg, f, indent=2)
    except Exception:
        pass

APP_CONFIG   = _load_config()
BRIEFING_DIR = str(APP_CONFIG["briefing_dir"])
os.makedirs(BRIEFING_DIR, exist_ok=True)

class _Fmt(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] [{record.levelname:<8}] {record.getMessage()}"

from logging.handlers import RotatingFileHandler as _RFH
_fh = _RFH(LOG_FILE, maxBytes=2*1024*1024, backupCount=3, encoding="utf-8")
_fh.setLevel(logging.INFO)
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_fh.setFormatter(_Fmt()); _ch.setFormatter(_Fmt())
logging.basicConfig(level=logging.INFO, handlers=[_fh, _ch])
logger = logging.getLogger(__name__)

def log_sep(t=""):
    logger.info("="*60)
    if t: logger.info(f"  {t}"); logger.info("="*60)

#  OFFSETS SHARED MEMORY — calculés depuis FlightData.h SDK BMS 4.38
#
#  FlightData ("FalconSharedMemoryArea") :
#    +0x000  float  x              Ownship North (ft)
#    +0x004  float  y              Ownship East  (ft)
#    +0x008  float  z              Ownship Down  (ft)
#    +0x034  float  kias           IAS (knots)
#    +0x0BC  float  currentHeading Cap vrai HSI (degrés, 0-360)
#
#  FlightData2 ("FalconSharedMemoryArea2") :
#    +0x014  float  AAUZ           Altitude baro (ft)
#    +0x408  float  latitude       Latitude WGS84 (degrés)
#    +0x40C  float  longitude      Longitude WGS84 (degrés)
#
#  Fichiers .ini BMS :
#    col1 = North (ft), col2 = East (ft)   [confirmé par Wonju target_0≈RKNW]

# Offsets FlightData
FD_CURRENT_HDG  = 0x0BC   # float, degrés vrais 0-360
FD_KIAS         = 0x034   # float, knots

# Offsets FlightData2
FD2_AAUZ         = 0x014   # float,  altitude baro ft
FD2_CURRENT_TIME = 0x02C   # int,    heure BMS en secondes depuis minuit (0-86400)
FD2_LAT          = 0x408   # float,  latitude degrés WGS84
FD2_LON          = 0x40C   # float,  longitude degrés WGS84
FD2_BULLSEYE_X   = 0x4B0   # float,  bullseye North ft (coords BMS)
FD2_PILOTS_ONLINE = 0x260  # char,   nombre de pilotes en MP (0 ou 1 = solo)
FD2_BULLSEYE_Y   = 0x4B4   # float,  bullseye East  ft (coords BMS)

#  CONVERSION TMERC KOREA → WGS84 (pour fichiers .ini)
#  .ini: col1=North(ft), col2=East(ft)
# Conversion TMERC Korea → WGS84 (pure Python, pas de dépendance externe)
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

#  AÉROPORTS KOREA (47)
AIRPORTS = {
    "RKJK": (35.906389, 126.615833, "Gunsan AB",      "75X"),
    "RKSO": (37.090556, 127.030000, "Osan AB",         "94X"),
    "RKSG": (36.961111, 127.030556, "Pyeongtaek",      "19X"),
    "RKSW": (37.239167, 127.005556, "Suwon AB",        "22X"),
    "RKTN": (35.894167, 128.658611, "Daegu AB",        "125X"),
    "RKTU": (36.716944, 127.499167, "Cheongju AB",     "42X"),
    "RKJJ": (35.126389, 126.808889, "Gwangju AB",      "91X"),
    "RKTH": (35.987778, 129.419444, "Pohang AB",       "72X"),
    "RKSM": (37.444722, 127.113889, "Seoul AB",        "46X"),
    "RKTP": (36.703889, 126.485278, "Seosan AB",       "52X"),
    "RKSI": (37.469444, 126.450556, "Incheon",         "85X"),
    "RKSS": (37.558333, 126.790833, "Gimpo",           "83X"),
    "RKPK": (35.179444, 128.938056, "Gimhae/Busan",   "117X"),
    "RKNY": (38.061111, 128.669167, "Yangyang",        "43X"),
    "RKNN": (37.753611, 128.943889, "Gangneung",       "056X"),
    "RKNW": (37.438056, 127.960556, "Wonju",           "60Y"),
    "RKND": (38.142778, 128.598611, "Sokcho",          "43X"),
    "RKPS": (35.088333, 128.070833, "Sacheon",         "37X"),
    "RKJB": (34.991389, 126.382778, "Muan",            "65X"),
    "RKTI": (36.635000, 127.498611, "Jungwon",         "05X"),
    "RKTY": (36.633333, 128.350000, "Yecheon",         "026X"),
    "ZKPY": (39.224167, 125.670278, "Pyongyang",       "51X"),
    "ZKWS": (39.166667, 127.486111, "Wonsan",          "54X"),
    "ZKUJ": (40.050000, 124.533333, "Uiju",            "55X"),
    "ZKTS": (39.283333, 127.366667, "Toksan",          "53X"),
    "KP-0011": (39.066667, 125.600000, "Mirim",        "59X"),
    "KP-0018": (39.800000, 125.900000, "Kaechon",      ""),
    "KP-0020": (38.666667, 125.783333, "Hwangju",      ""),
    "KP-0021": (39.433333, 125.933333, "Sunchon",      ""),
    "KP-0023": (39.816667, 124.916667, "Onchon",       ""),
    "KP-0030": (39.900000, 124.933333, "Panghyon",     ""),
    "KP-0032": (41.383333, 129.450000, "Orang",        ""),
    "KP-0008": (39.745833, 127.473333, "Sondok",       ""),
    "KP-0015": (38.816667, 126.400000, "Koksan",       ""),
    "KP-0019": (39.150000, 125.883333, "Hyon-Ni",      ""),
    "KP-0035": (38.683333, 125.366667, "Hwangsuwon",   ""),
    "KP-0039": (38.700000, 125.550000, "Kwail",        ""),
    "KP-0050": (38.033333, 125.366667, "Ongjin",       ""),
    "KP-0053": (41.566667, 126.266667, "Manpo",        ""),
    "KP-0059": (40.316667, 128.633333, "Iwon",         ""),
    "KP-0006": (39.783333, 124.716667, "Taechon",      ""),
    "KP-0005": (38.250000, 126.650000, "Taetan",       ""),
    "KP-0029": (42.066667, 128.400000, "Samjiyon",     ""),
    "RJOI":   (34.143889, 132.235556, "Iwakuni",       "126X"),
    "RJOA":   (34.436111, 132.919444, "Hiroshima",     "024X"),
    "RJOW":   (34.676111, 131.789722, "Iwami",         "57X"),
    "RJDC":   (33.930000, 131.278611, "Yamaguchi",     ""),
}

#  SHARED MEMORY BMS 4.38 — OFFSETS CORRECTS
#
#  FalconSharedMemoryArea  = FlightData  (taille ~0x800)
#  FalconSharedMemoryArea2 = FlightData2 (taille ~0x900)
#
#  FlightData (source : BMS 4.38 SDK / FlightData.h) :
#    +0x000  float  x          (BMS east, pieds)
#    +0x004  float  y          (BMS north, pieds)
#    +0x008  float  z          (altitude MSL, pieds, négatif)
#    +0x010  float  roll       (rad)
#    +0x014  float  pitch      (rad)
#    +0x018  float  yaw        (cap vrai, rad) ← HEADING
#
#  FlightData2 :
#    +0x000  float  x          (BMS east, pieds)  — même que FD
#    +0x004  float  y          (BMS north, pieds)
#    +0x008  float  z          (altitude)
#    +0x184  double latitude   (rad WGS84) ← LAT
#    +0x18C  double longitude  (rad WGS84) ← LON


#  TACVIEW REAL-TIME TELEMETRY (TRTT) CLIENT
#  Protocole TCP documenté par Tacview — utilisé par OpenRadar (UOAF)
#  BMS config: set g_bTacviewRealTime 1 / set g_nTacviewPort 42674
#  Handshake: BMS envoie "XtraLib.Stream.0\nTacview.RealTimeTelemetry.0\nHost\n\0"
#             Client répond "XtraLib.Stream.0\nTacview.RealTimeTelemetry.0\nClient\n0\0"
#  Ensuite: stream ACMI 2.x texte UTF-8 continu
import socket as _socket
import threading, time as _time

TRTT_HOST = "127.0.0.1"
TRTT_PORT = 42674
TRTT_CLIENT_NAME = "BMS-GPS-Riesu"

_acmi_contacts: dict = {}
_acmi_lock = threading.Lock()
_acmi_thread = None
_acmi_running = False
_acmi_connected = False  # pour le status UI

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

def _trtt_client_loop():
    global _acmi_running, _acmi_connected
    obj_props: dict = {}
    ref_lon = ref_lat = 0.0
    buf = ""
    sock: _socket.socket | None = None   # init explicite — évite "possibly unbound"

    while _acmi_running:
        try:
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            sock.settimeout(5.0)
            logger.info(f"TRTT: connexion à {TRTT_HOST}:{TRTT_PORT}...")
            sock.connect((TRTT_HOST, TRTT_PORT))
            sock.settimeout(10.0)

            # ── Handshake ────────────────────────────────────────
            # Recevoir le handshake host (jusqu'au \0)
            hs = b""
            while b"\x00" not in hs:
                chunk = sock.recv(256)
                if not chunk:
                    raise ConnectionError("Handshake host incomplet")
                hs += chunk

            # Envoyer le handshake client
            client_hs = (
                "XtraLib.Stream.0\n"
                "Tacview.RealTimeTelemetry.0\n"
                f"{TRTT_CLIENT_NAME}\n"
                "0\x00"
            ).encode('utf-8')
            sock.sendall(client_hs)
            _acmi_connected = True
            sock.settimeout(30.0)
            buf = ""
            obj_props = {}
            ref_lon = ref_lat = 0.0

            # ── Stream ACMI ──────────────────────────────────────
            while _acmi_running:
                try:
                    data = sock.recv(65536)
                except _socket.timeout:
                    logger.warning("TRTT: timeout recv — BMS toujours connecté?")
                    continue
                if not data:
                    raise ConnectionError("BMS a fermé la connexion TRTT")
                buf += data.decode('utf-8', errors='replace')
                # Sécurité: borne le buffer pour éviter OOM
                if len(buf) > 2 * 1024 * 1024:
                    logger.warning("TRTT: buffer > 2MB, truncature")
                    nl = buf.rfind('\n')
                    buf = buf[nl+1:] if nl >= 0 else ""

                # Traiter lignes complètes
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    line = line.strip()
                    if not line or line.startswith('//'):
                        continue
                    if line.startswith('FileType') or line.startswith('FileVersion'):
                        continue

                    # Global object (id=0): références et métadonnées
                    if line.startswith('0,'):
                        for part in line[2:].split(','):
                            if '=' in part:
                                k, v = part.split('=', 1)
                                if k == 'ReferenceLongitude':
                                    try: ref_lon = float(v)
                                    except ValueError: pass
                                elif k == 'ReferenceLatitude':
                                    try: ref_lat = float(v)
                                    except ValueError: pass
                        continue

                    # Suppression: -hexid
                    if line.startswith('-'):
                        obj_id = line[1:].strip()
                        with _acmi_lock:
                            _acmi_contacts.pop(obj_id, None)
                        obj_props.pop(obj_id, None)
                        continue

                    # Timestamp: #47.13
                    if line.startswith('#'):
                        continue

                    # Objet: hexid,prop=val,...
                    if ',' not in line:
                        continue

                    try:
                        obj_id, rest = line.split(',', 1)
                        obj_id = obj_id.strip()
                        if not obj_id or obj_id == '0':
                            continue

                        props = {}
                        # Parser correctement (les virgules peuvent être échappées)
                        i, start_i = 0, 0
                        chars = rest
                        while i <= len(chars):
                            if i == len(chars) or (chars[i] == ',' and (i == 0 or chars[i-1] != '\\')):
                                part = chars[start_i:i]
                                if '=' in part:
                                    k, v = part.split('=', 1)
                                    props[k.strip()] = v.strip()
                                start_i = i + 1
                            i += 1

                        # Mémoriser propriétés permanentes (borné à 1000 objets)
                        if obj_id not in obj_props:
                            if len(obj_props) > 1000:
                                # Purger les entrées sans contact récent
                                stale = [k for k in obj_props if k not in _acmi_contacts]
                                for k in stale[:200]: del obj_props[k]
                            obj_props[obj_id] = {'name':'','color':3,'acmi_type':'other','pilot':''}
                        p = obj_props[obj_id]
                        if 'Name'   in props: p['name']      = props['Name']
                        if 'Color'  in props: p['color']     = _parse_trtt_color(props['Color'])
                        # Coalition=Allies/Enemies comme fallback si Color absent
                        if 'Coalition' in props and p['color'] == 3:
                            co = props['Coalition'].lower()
                            if 'allies' in co:  p['color'] = 1
                            elif 'enemies' in co: p['color'] = 2
                        if 'Type'   in props: p['acmi_type'] = _parse_trtt_type(props['Type'])
                        if 'Pilot'  in props: p['pilot']     = props['Pilot']
                        if 'Group'  in props and not p['name']: p['name'] = props['Group']

                        # Filtrer: air uniquement
                        # 'other' = type pas encore reçu → on garde en attendant
                        at = p.get('acmi_type', 'other')
                        if at in ('weapon', 'navaid', 'ground', 'sea'):
                            continue
                        # Si type connu et pas air → exclure
                        if at not in ('air', 'other'):
                            continue

                        # Position T=lon|lat|alt|roll|pitch|yaw|...
                        if 'T' not in props:
                            continue
                        coords = props['T'].split('|')
                        if len(coords) < 2:
                            continue
                        lon_s = coords[0]
                        lat_s = coords[1]
                        alt_s = coords[2] if len(coords) > 2 else ''
                        yaw_s = coords[5] if len(coords) > 5 else ''

                        # Coordonnées relatives si vide = pas de changement de pos
                        if not lon_s or not lat_s:
                            # Garder l'entrée existante avec mise à jour timestamp
                            with _acmi_lock:
                                if obj_id in _acmi_contacts:
                                    _acmi_contacts[obj_id]['_ts'] = _time.time()
                            continue

                        lon = float(lon_s) + ref_lon
                        lat = float(lat_s) + ref_lat
                        alt_m = float(alt_s) if alt_s else 0.0
                        hdg = float(yaw_s) % 360.0 if yaw_s else 0.0

                        # Sanity check Corée / zone BMS
                        if not (20 <= lat <= 50 and 110 <= lon <= 145):
                            continue

                        with _acmi_lock:
                            _acmi_contacts[obj_id] = {
                                'lat':      round(lat, 5),
                                'lon':      round(lon, 5),
                                'alt':      round(alt_m * 3.28084),  # m → ft
                                'camp':     p['color'],
                                'callsign': p['name'] or p['pilot'] or obj_id,
                                'pilot':    p['pilot'],
                                'type_name': at,
                                'heading':  hdg,
                                'speed':    round(float(props['IAS']) * 1.944) if props.get('IAS') else 0,
                                '_ts':      _time.time(),
                            }
                    except Exception:
                        pass

        except Exception as ex:
            _acmi_connected = False
            with _acmi_lock:
                _acmi_contacts.clear()
            try:
                if sock is not None:
                    sock.close()
            except OSError:
                pass
            _time.sleep(5)

    _acmi_connected = False
    logger.info("TRTT client arrêté")

def start_acmi_reader():
    global _acmi_thread, _acmi_running
    if _acmi_thread and _acmi_thread.is_alive():
        return
    _acmi_running = True
    _acmi_thread = threading.Thread(target=_trtt_client_loop, daemon=True)
    _acmi_thread.start()
    logger.info(f"TRTT client démarré → {TRTT_HOST}:{TRTT_PORT}")
    logger.info("  (BMS User.cfg requis: set g_bTacviewRealTime 1)")

def get_acmi_contacts(own_lat=None, own_lon=None,
                      max_nm: float = 9999.0, allies_only: bool = False) -> list:
    """
    Retourne les contacts TRTT filtrés.
    - max_nm     : rayon max en NM autour de l'ownship (solo=240, multi=ignoré)
    - allies_only: si True, filtre uniquement camp=1 (bleu)
    """
    now = _time.time()
    with _acmi_lock:
        contacts = list(_acmi_contacts.items())
    result = []
    for obj_id, c in contacts:
        # Ignorer stale (>30s sans update — objet détruit)
        if now - c.get('_ts', 0) > 30.0:
            continue
        # Filtrer par camp si allies_only
        # En solo BMS envoie souvent camp=3 (unknown) car les couleurs
        # ne sont pas injectées immédiatement via TRTT — on exclut seulement
        # les ennemis confirmés (camp=2 = rouge)
        if allies_only and c.get('camp', 3) == 2:
            continue
        # Filtrer : air uniquement (ground, sea, weapon exclus)
        # 'other' gardé seulement si récent (<10s) en attendant le type BMS
        ct = c.get('type_name', 'other')
        if ct in ('ground', 'sea', 'weapon', 'navaid'):
            continue
        if ct == 'other' and (now - c.get('_ts', 0)) > 10.0:
            continue
        # Filtrer par rayon NM
        if own_lat is not None and own_lon is not None and max_nm < 9999.0:
            dlat = c['lat'] - own_lat
            dlon = (c['lon'] - own_lon) * math.cos(math.radians(own_lat))
            dist_nm = math.sqrt(dlat**2 + dlon**2) * 60.0
            if dist_nm > max_nm:
                continue
        # Exclure ownship (même position)
        if own_lat is not None and own_lon is not None:
            if abs(c['lat'] - own_lat) < 0.002 and abs(c['lon'] - own_lon) < 0.002:
                continue
        result.append({k: v for k, v in c.items() if k != '_ts'})
    return result


# ── Lecture mémoire sécurisée (ReadProcessMemory) ────────────────
# ctypes.from_address() peut segfaulter — ReadProcessMemory retourne False
_k32 = _rpm = _hproc = None

def _init_safe_mem():
    global _k32, _rpm, _hproc
    try:
        _k32  = ctypes.WinDLL("kernel32", use_last_error=True)
        _rpm  = _k32.ReadProcessMemory
        _rpm.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_size_t,
                         ctypes.POINTER(ctypes.c_size_t)]
        _rpm.restype  = ctypes.c_bool
        _hproc = _k32.GetCurrentProcess()
        logger.info("SafeMemReader OK")
    except Exception as e:
        logger.error(f"SafeMemReader init FAILED: {e}")

def safe_read(addr: int, size: int):
    if not _rpm or not addr: return None
    try:
        buf  = (ctypes.c_char * size)()
        read = ctypes.c_size_t(0)
        ok   = _rpm(_hproc, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
        return bytes(buf) if ok and read.value == size else None
    except Exception: return None

def safe_float(addr: int):
    b = safe_read(addr, 4)
    return struct.unpack('<f', b)[0] if b else None

def safe_int32(addr: int):
    b = safe_read(addr, 4)
    return struct.unpack('<i', b)[0] if b else None

class BMSSharedMemory:
    def __init__(self):
        self.ptr1 = None
        self.ptr2 = None
        self.shm_ptrs = {}
        self.connected = False
        self._connect()

    def _connect(self):
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            OpenMap = k32.OpenFileMappingW
            OpenMap.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
            OpenMap.restype  = ctypes.c_void_p
            MapView = k32.MapViewOfFile
            MapView.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
            MapView.restype  = ctypes.c_void_p

            FILE_MAP_READ = 0x0004
            # Zones connues BMS 4.x
            SHM_NAMES = [
                "FalconSharedMemoryArea",
                "FalconSharedMemoryArea2",
                "FalconSharedMemoryArea3",
                "FalconSharedOSBMemoryArea",
                "FalconSharedIntellivibeMemoryArea",
                "FalconSharedDrawingMemoryArea",
                "FalconSharedCallsignMemoryArea",
                "FalconSharedTrafficMemoryArea",
            ]
            self.shm_ptrs = {}
            for name in SHM_NAMES:
                h = OpenMap(FILE_MAP_READ, False, name)
                if h:
                    p = MapView(h, FILE_MAP_READ, 0, 0, 0)
                    if p:
                        self.shm_ptrs[name] = p
                        logger.info(f"  SHM {name} mapped")
            # ptr1/ptr2 compatibilité
            self.ptr1 = self.shm_ptrs.get("FalconSharedMemoryArea")
            self.ptr2 = self.shm_ptrs.get("FalconSharedMemoryArea2")

            if self.ptr1 and self.ptr2:
                self.connected = True
                logger.info(f"SHM connectee: {len(self.shm_ptrs)} zones ouvertes")
                _init_safe_mem()
            else:
                self.shm_ptrs = {}
                self.ptr1 = self.ptr2 = None
                self.connected = False
        except Exception as e:
            self.shm_ptrs = {}
            self.ptr1 = self.ptr2 = None
            self.connected = False
            logger.error(f"Shared Memory error: {e}", exc_info=True)

    def try_reconnect(self):
        if not self.connected:
            self._connect()
        return self.connected

    def get_position(self) -> Optional[Dict]:
        if not self.ptr1 or not self.ptr2: return None
        hdg  = safe_float(self.ptr1 + FD_CURRENT_HDG)
        kias = safe_float(self.ptr1 + FD_KIAS)
        z    = safe_float(self.ptr1 + 0x008)
        lat  = safe_float(self.ptr2 + FD2_LAT)
        lon  = safe_float(self.ptr2 + FD2_LON)
        if None in (hdg, kias, z, lat, lon):
            logger.warning("get_position: safe_read echoue")
            return None
        # Cast explicite — les valeurs ne sont pas None ici (vérifié ci-dessus)
        hdg_f  = float(hdg)   # type: ignore[arg-type]
        kias_f = float(kias)  # type: ignore[arg-type]
        z_f    = float(z)     # type: ignore[arg-type]
        lat_f  = float(lat)   # type: ignore[arg-type]
        lon_f  = float(lon)   # type: ignore[arg-type]
        alt    = abs(z_f)
        hdg_f  = hdg_f % 360.0
        # Heure BMS (secondes depuis minuit)
        bms_time: Optional[int] = None
        raw_t = safe_read(self.ptr2 + FD2_CURRENT_TIME, 4)
        if raw_t:
            try:
                bms_time = int(struct.unpack('<i', raw_t)[0])
                if bms_time < 0 or bms_time > 86400:
                    bms_time = None
            except Exception:
                bms_time = None

        # Bullseye (coords BMS North/East ft → WGS84)
        bull_lat: Optional[float] = None
        bull_lon: Optional[float] = None
        raw_bx = safe_read(self.ptr2 + FD2_BULLSEYE_X, 4)
        raw_by = safe_read(self.ptr2 + FD2_BULLSEYE_Y, 4)
        if raw_bx and raw_by:
            try:
                bx = struct.unpack('<f', raw_bx)[0]
                by = struct.unpack('<f', raw_by)[0]
                if abs(bx) > 10 and abs(by) > 10:
                    _bl, _bn = bms_to_latlon(bx, by)
                    bull_lat = float(_bl)
                    bull_lon = float(_bn)
                    # Sanity check — Korea theater
                    if not (30.0 <= bull_lat <= 45.0 and 118.0 <= bull_lon <= 135.0):
                        bull_lat = bull_lon = None
            except Exception:
                pass

        # Nombre de pilotes (solo vs multi)
        pilots_online: int = 1
        raw_po = safe_read(self.ptr2 + FD2_PILOTS_ONLINE, 1)
        if raw_po:
            try:
                pilots_online = max(1, int(struct.unpack('<B', raw_po)[0]))
            except Exception:
                pilots_online = 1

        if -90 <= lat_f <= 90 and -180 <= lon_f <= 180 and not (lat_f == 0.0 and lon_f == 0.0):
            return {"lat": lat_f, "lon": lon_f, "heading": round(hdg_f, 1),
                    "altitude": round(alt), "kias": round(kias_f),
                    "bms_time": bms_time,
                    "pilots_online": pilots_online,
                    "bull_lat": round(bull_lat, 5) if bull_lat is not None else None,
                    "bull_lon": round(bull_lon, 5) if bull_lon is not None else None,
                    "connected": True}
        return None


#  APP
bms   = BMSSharedMemory()
from contextlib import asynccontextmanager

# ── Détection IP locale automatique ─────────────────────────────
import socket as _sock_ip
def _get_local_ip() -> str:
    s: _sock_ip.socket | None = None
    try:
        s = _sock_ip.socket(_sock_ip.AF_INET, _sock_ip.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip: str = s.getsockname()[0]
        return ip
    except Exception:
        return "0.0.0.0"
    finally:
        if s is not None:
            s.close()

SERVER_IP   = _get_local_ip()
SERVER_PORT = int(APP_CONFIG["port"])

@asynccontextmanager
async def lifespan(_a):
    asyncio.create_task(broadcast_loop())
    asyncio.create_task(_ini_watcher_loop())
    start_acmi_reader()  # TRTT — filtré alliés 240 NM solo / L16 multi
    log_sep(f"{APP_NAME} v{APP_VERSION} — by {APP_AUTHOR}")
    logger.info(f"  Contact  : {APP_CONTACT}")
    logger.info(f"  Website  : {APP_WEBSITE}")
    logger.info(f"  License  : GNU GPL v3")
    logger.info(f"  Log      : {LOG_FILE}")
    logger.info(f"  Briefing : {BRIEFING_DIR}")
    logger.info(f"  Config   : {CONFIG_FILE}")
    logger.info(f"  BMS      : {'CONNECTE' if bms.connected else 'NON DETECTE'}")
    logger.info(f"  Local    : http://localhost:{SERVER_PORT}       ← PC")
    logger.info(f"  Réseau   : http://{SERVER_IP}:{SERVER_PORT}  ← Tablette/Mobile")
    logger.info(f"  Sécurité : LAN uniquement (RFC-1918 + localhost)")
    log_sep()
    yield
    log_sep("ARRET")

app   = FastAPI(title="Falcon-Pad", lifespan=lifespan)

# ── Middleware — accès local uniquement (localhost + LAN) ────────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as _StarResponse

def _is_local(ip: str) -> bool:
    """Autorise uniquement localhost et réseaux privés RFC-1918."""
    return (
        ip in ("127.0.0.1", "::1", "localhost") or
        ip.startswith("10.")          or
        ip.startswith("192.168.")     or
        (ip.startswith("172.") and
         any(ip.startswith(f"172.{i}.") for i in range(16, 32)))
    )

class _LocalOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else ""
        if not _is_local(client_ip):
            return _StarResponse("Accès refusé — réseau local uniquement", status_code=403)
        return await call_next(request)

app.add_middleware(_LocalOnlyMiddleware)
ws_clients: List[WebSocket] = []  # snapshot avec list() à l'itération
mission_data = {"route": [], "threats": [], "flightplan": []}

# ── DrawingData constants (BMS 4.38 — FalconSharedMemoryArea) ───

# ── Broadcast loop — pousse les données BMS à tous les WS ────────
_bms_last_reconnect: float = 0.0
_BMS_RECONNECT_INTERVAL = 5.0

async def broadcast_loop() -> None:
    """Tâche asyncio : lit BMS et diffuse position + radar toutes les N ms."""
    global _bms_last_reconnect
    while True:
        try:
            if not bms.connected:
                _now = _time.time()
                if _now - _bms_last_reconnect >= _BMS_RECONNECT_INTERVAL:
                    _bms_last_reconnect = _now
                    bms.try_reconnect()
            pos = bms.get_position() if bms.connected else None

            if pos and ws_clients:
                # 1. Position ownship
                dead: list = []
                msg_ac = json.dumps({"type": "aircraft", "data": pos})
                for ws in list(ws_clients):
                    try:    await ws.send_text(msg_ac)
                    except Exception: dead.append(ws)
                for ws in dead:
                    try: ws_clients.remove(ws)
                    except ValueError: pass

                # 2. Contacts radar/datalink BMS (DrawingData — no god mode)
                own_lat = pos.get("lat"); own_lon = pos.get("lon")
                radar_c = get_radar_contacts(
                    bms.ptr1, own_lat=own_lat, own_lon=own_lon,
                    ptr2=bms.ptr2 if bms.ptr2 else 0
                ) if bms.ptr1 else []
                msg_r = json.dumps({"type": "radar", "data": radar_c})
                for ws in list(ws_clients):
                    try:    await ws.send_text(msg_r)
                    except Exception: pass

                # 3. Contacts TRTT — alliés filtrés (solo=240NM / multi=L16)
                pilots_online = pos.get("pilots_online", 1)
                is_multi = pilots_online > 1
                if not is_multi:
                    # Solo : TRTT filtré 240 NM, alliés seulement
                    acmi_c = get_acmi_contacts(
                        own_lat=own_lat, own_lon=own_lon,
                        max_nm=240.0, allies_only=True
                    )
                    if acmi_c:
                        msg_acmi = json.dumps({"type": "acmi", "data": acmi_c})
                        for ws in list(ws_clients):
                            try:    await ws.send_text(msg_acmi)
                            except Exception: pass

            # 4. Statut connexion
            if ws_clients:
                status_msg = json.dumps({"type": "status", "data": {"connected": bms.connected}})
                for ws in list(ws_clients):
                    try:    await ws.send_text(status_msg)
                    except Exception: pass

        except Exception:
            pass
        await asyncio.sleep(APP_CONFIG.get("broadcast_ms", 200) / 1000.0)


#  DATALINK L16 — via StringData (FalconSharedMemoryAreaString, BMS 4.38)
#
#  Structure StringData (depuis FlightData.h) :
#    uint32 VersionNum
#    uint32 NoOfStrings
#    uint32 dataSize
#    Pour chaque string :
#      uint32 strId      (index dans enum StringIdentifier)
#      uint32 strLength  (longueur sans \0)
#      char   strData[strLength+1]
#
#  StringIdentifier::NavPoint = 30
#  Format NavPoint : "NP:<idx>,<type>,<x>,<y>,<z>,<grnd_elev>;"
#  Types : WP=waypoint, DL=datalink L16, MK=markpoint, CB=bullseye, etc.
#
import math as _math  # alias local

STRING_ID_NAVPOINT = 30   # enum StringIdentifier::NavPoint

def _read_string_data(ptr_str: int) -> list:
    """
    Lit FalconSharedMemoryAreaString et retourne la liste des NavPoints DL.
    Retourne [] si inaccessible ou vide.
    """
    if not ptr_str:
        return []
    # Lire l'en-tête : VersionNum(4) + NoOfStrings(4) + dataSize(4)
    hdr = safe_read(ptr_str, 12)
    if not hdr or len(hdr) < 12:
        return []
    try:
        _ver, no_strings, data_size = struct.unpack_from('<III', hdr, 0)
    except Exception:
        return []
    if no_strings == 0 or no_strings > 500 or data_size > 4 * 1024 * 1024:
        return []
    # Lire tout le blob StringData
    blob = safe_read(ptr_str + 12, data_size)
    if not blob or len(blob) < data_size:
        return []
    navpoints = []
    off = 0
    for _ in range(no_strings):
        if off + 8 > len(blob):
            break
        try:
            str_id, str_len = struct.unpack_from('<II', blob, off)
            off += 8
            if off + str_len + 1 > len(blob):
                break
            raw = blob[off:off + str_len].decode('utf-8', errors='replace')
            off += str_len + 1  # +1 pour le \0
            if str_id == STRING_ID_NAVPOINT:
                navpoints.append(raw)
        except Exception:
            break
    return navpoints


def _parse_navpoint_dl(raw: str, own_lat=None, own_lon=None) -> Optional[dict]:
    """
    Parse une entrée NavPoint BMS et retourne un contact DL si type=DL.
    Format : "NP:<idx>,<type>,<x>,<y>,<z>,<grnd_elev>;"
    x,y = coordonnées BMS en pieds (North, East)
    z   = altitude en dizaines de pieds
    """
    try:
        # Extraire le bloc NP:...;
        import re as _re
        m = _re.search(r'NP:(\d+),([A-Z]+),([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+);', raw)
        if not m:
            return None
        idx  = int(m.group(1))
        typ  = m.group(2)
        x    = float(m.group(3))   # North ft
        y    = float(m.group(4))   # East ft
        z    = float(m.group(5))   # alt × 10 ft
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
            "alt":      round(abs(z) * 10),   # dizaines → pieds
            "camp":     1,                     # L16 = toujours alliés
            "type_name": "L16",
            "callsign": f"DL{idx:02d}",
            "heading":  0,
            "speed":    0,
        }
    except Exception:
        return None


def get_radar_contacts(ptr1: int, own_lat=None, own_lon=None, ptr2: int = 0) -> list:
    """
    Lit les contacts L16/Datalink depuis StringData (NavPoint type=DL).
    Source officielle SDK BMS 4.38 : FalconSharedMemoryAreaString.
    """
    ptr_str = bms.shm_ptrs.get("FalconSharedMemoryAreaString") if bms.shm_ptrs else None
    if not ptr_str:
        return []
    navpoints = _read_string_data(ptr_str)
    if not navpoints:
        return []
    result = []
    for raw in navpoints:
        c = _parse_navpoint_dl(raw, own_lat=own_lat, own_lon=own_lon)
        if c:
            result.append(c)
    return result


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        await websocket.send_text(json.dumps({"type":"status","data":{"connected": bms.connected}}))
        while True:
            try:
                # receive_text avec timeout — détecte les connexions mortes
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # ping pour maintenir la connexion
                try: await websocket.send_text('{"type":"ping"}')
                except Exception: break
    except WebSocketDisconnect:
        pass
    finally:
        try: ws_clients.remove(websocket)
        except ValueError: pass


AP_EXTRA = {
    "RKSO": {"freq":"126.2","ils":[{"rwy":"36L","freq":"108.7","crs":"355"},{"rwy":"18R","freq":"110.3","crs":"175"}]},
    "RKJK": {"freq":"122.1","ils":[{"rwy":"18","freq":"109.1","crs":"183"},{"rwy":"36","freq":"110.1","crs":"003"}]},
    "RKTN": {"freq":"126.2","ils":[{"rwy":"32","freq":"108.3","crs":"323"},{"rwy":"14","freq":"109.5","crs":"143"}]},
    "RKJJ": {"freq":"123.3","ils":[{"rwy":"24","freq":"108.9","crs":"241"},{"rwy":"06","freq":"109.9","crs":"061"}]},
    "RKSM": {"freq":"126.2","ils":[{"rwy":"09","freq":"110.5","crs":"085"},{"rwy":"27","freq":"108.5","crs":"265"}]},
    "RKSW": {"freq":"126.2","ils":[{"rwy":"09","freq":"108.1","crs":"092"},{"rwy":"27","freq":"109.3","crs":"272"}]},
    "RKTU": {"freq":"126.2","ils":[{"rwy":"06","freq":"108.7","crs":"059"},{"rwy":"24","freq":"110.7","crs":"239"}]},
    "RKTH": {"freq":"123.3","ils":[{"rwy":"09","freq":"108.3","crs":"093"},{"rwy":"27","freq":"109.7","crs":"273"}]},
    "RKSI": {"freq":"119.1","ils":[{"rwy":"33L","freq":"110.1","crs":"328"},{"rwy":"15R","freq":"109.5","crs":"148"}]},
    "RKSS": {"freq":"118.1","ils":[{"rwy":"14L","freq":"108.9","crs":"142"},{"rwy":"32R","freq":"110.3","crs":"322"}]},
    "RKPK": {"freq":"118.8","ils":[{"rwy":"36L","freq":"108.5","crs":"358"},{"rwy":"18R","freq":"109.9","crs":"178"}]},
    "RKNY": {"freq":"126.2","ils":[{"rwy":"33","freq":"108.3","crs":"326"},{"rwy":"15","freq":"109.1","crs":"146"}]},
    "RKNN": {"freq":"126.2","ils":[{"rwy":"06","freq":"108.7","crs":"063"},{"rwy":"24","freq":"110.5","crs":"243"}]},
    "RKNW": {"freq":"126.2","ils":[{"rwy":"03","freq":"108.9","crs":"033"},{"rwy":"21","freq":"109.3","crs":"213"}]},
    "RKPS": {"freq":"126.2","ils":[{"rwy":"04","freq":"108.3","crs":"037"},{"rwy":"22","freq":"109.5","crs":"217"}]},
    "RKJB": {"freq":"118.1","ils":[{"rwy":"01","freq":"108.5","crs":"011"},{"rwy":"19","freq":"110.1","crs":"191"}]},
    "RKTI": {"freq":"126.2","ils":[{"rwy":"27","freq":"108.7","crs":"276"},{"rwy":"09","freq":"109.7","crs":"096"}]},
    "RKTY": {"freq":"126.2","ils":[{"rwy":"18","freq":"108.9","crs":"184"},{"rwy":"36","freq":"110.3","crs":"004"}]},
    "RKSG": {"freq":"126.2","ils":[{"rwy":"18","freq":"108.3","crs":"182"},{"rwy":"36","freq":"109.9","crs":"002"}]},
    "RKTP": {"freq":"126.2","ils":[{"rwy":"03","freq":"108.5","crs":"032"},{"rwy":"21","freq":"109.1","crs":"212"}]},
    "RJOI": {"freq":"126.2","ils":[{"rwy":"07","freq":"108.3","crs":"072"},{"rwy":"25","freq":"110.7","crs":"252"}]},
    "RJOW": {"freq":"122.8","ils":[{"rwy":"17","freq":"108.9","crs":"168"},{"rwy":"35","freq":"109.5","crs":"348"}]},
    "RJOA": {"freq":"118.7","ils":[{"rwy":"10","freq":"109.1","crs":"100"},{"rwy":"28","freq":"110.3","crs":"280"}]},
    "RKND": {"freq":"126.2","ils":[{"rwy":"07","freq":"108.5","crs":"073"},{"rwy":"25","freq":"109.3","crs":"253"}]},
    # Bases NK — fréquences approximatives BMS
    "ZKPY": {"freq":"126.2","ils":[{"rwy":"17","freq":"108.3","crs":"173"},{"rwy":"35","freq":"109.5","crs":"353"}]},
    "ZKWS": {"freq":"126.2","ils":[{"rwy":"18","freq":"108.7","crs":"183"},{"rwy":"36","freq":"110.1","crs":"003"}]},
    "ZKUJ": {"freq":"126.2","ils":[{"rwy":"05","freq":"108.9","crs":"049"},{"rwy":"23","freq":"109.7","crs":"229"}]},
    "ZKTS": {"freq":"126.2","ils":[{"rwy":"05","freq":"108.5","crs":"052"},{"rwy":"23","freq":"109.3","crs":"232"}]},
    "KP-0011":{"freq":"126.2","ils":[{"rwy":"17","freq":"108.3","crs":"172"},{"rwy":"35","freq":"109.5","crs":"352"}]},
    "KP-0018":{"freq":"126.2","ils":[{"rwy":"18","freq":"108.7","crs":"184"},{"rwy":"36","freq":"110.1","crs":"004"}]},
    "KP-0020":{"freq":"126.2","ils":[{"rwy":"18","freq":"108.9","crs":"181"},{"rwy":"36","freq":"109.7","crs":"001"}]},
    "KP-0021":{"freq":"126.2","ils":[{"rwy":"18","freq":"108.3","crs":"183"},{"rwy":"36","freq":"110.3","crs":"003"}]},
    "KP-0023":{"freq":"126.2","ils":[{"rwy":"18","freq":"108.5","crs":"182"},{"rwy":"36","freq":"109.1","crs":"002"}]},
    "KP-0030":{"freq":"126.2","ils":[{"rwy":"17","freq":"108.7","crs":"174"},{"rwy":"35","freq":"109.9","crs":"354"}]},
    "KP-0032":{"freq":"126.2","ils":[]},
    "KP-0008":{"freq":"126.2","ils":[{"rwy":"18","freq":"108.3","crs":"183"},{"rwy":"36","freq":"109.5","crs":"003"}]},
    "KP-0015":{"freq":"126.2","ils":[]},
    "KP-0019":{"freq":"126.2","ils":[]},
    "KP-0035":{"freq":"126.2","ils":[]},
    "KP-0039":{"freq":"126.2","ils":[]},
    "KP-0050":{"freq":"126.2","ils":[]},
    "KP-0053":{"freq":"126.2","ils":[]},
    "KP-0059":{"freq":"126.2","ils":[]},
    "KP-0006":{"freq":"126.2","ils":[]},
    "KP-0005":{"freq":"126.2","ils":[{"rwy":"03","freq":"108.5","crs":"032"},{"rwy":"21","freq":"109.1","crs":"212"}]},
    "KP-0029":{"freq":"126.2","ils":[]},
    "RJDC":   {"freq":"122.8","ils":[{"rwy":"07","freq":"108.3","crs":"072"},{"rwy":"25","freq":"109.5","crs":"252"}]},
}

@app.get("/api/airports")
async def get_airports():
    result = []
    for k, v in AIRPORTS.items():
        extra = AP_EXTRA.get(k, {})
        result.append({
            "icao": k, "name": v[2], "lat": v[0], "lon": v[1],
            "tacan": v[3],
            "freq": extra.get("freq", ""),
            "ils":  extra.get("ils", []),
        })
    return result

@app.get("/api/ini/status")
async def ini_status():
    """Statut du dernier .ini chargé automatiquement."""
    return {
        "file": os.path.basename(_ini_last_path) if _ini_last_path else None,
        "path": _ini_last_path,
        "loaded": bool(_ini_last_path),
        "steerpoints": len(mission_data.get("route", [])),
        "ppt": len(mission_data.get("threats", [])),
        "flightplan": len(mission_data.get("flightplan", [])),
    }

@app.get("/api/mission")
async def get_mission(): return mission_data

@app.post("/api/upload")
async def upload_mission(file: UploadFile = File(...)):
    global mission_data
    try:
        raw = await file.read()
        if len(raw) > 1024 * 1024:  # 1 MB max
            return {"status": "error", "message": "Fichier trop volumineux (max 1 MB)"}
        content = raw.decode("latin-1")
        cfg = configparser.RawConfigParser(); cfg.optionxform = str  # type: ignore[assignment]
        cfg.read_string(content)
        route, threats, fplan = [], [], []
        if cfg.has_section("STPT"):
            for key, val in cfg["STPT"].items():
                parts = val.split(",")
                if len(parts) >= 3:
                    try:
                        x,y,z = float(parts[0]),float(parts[1]),float(parts[2])
                        if abs(x)>10 and abs(y)>10:
                            # .ini BMS: col1=North(x), col2=East(y) — confirmé
                            lat,lon = bms_to_latlon(x, y)
                            if   "line" in key.lower(): fplan.append({"lat":lat,"lon":lon,"alt":z,"index":len(fplan)})
                            elif "ppt"  in key.lower():
                                # col4 = range en pieds (164055 ft ≈ 27 NM pour SA2, etc.)
                                try:
                                    r_ft=float(parts[3]);range_m=int(r_ft*0.3048);range_nm=max(1,round(r_ft/6076.12))
                                except:
                                    range_m=27800;range_nm=15
                                name_ppt=parts[4].strip() if len(parts)>4 else ""
                                try:    ppt_num = 56 + int(key.lower().replace("ppt_","").strip())
                                except: ppt_num = 56 + len(threats)
                                # Ignorer les PPTs hors du théâtre Korea (IPs hors zone, etc.)
                                if 30.0 <= lat <= 44.0 and 120.0 <= lon <= 135.0:
                                    threats.append({"lat":lat,"lon":lon,"name":name_ppt,"range_nm":range_nm,"range_m":range_m,"num":ppt_num,"index":len(threats)})
                            else:                       route.append({"lat":lat,"lon":lon,"alt":z,"index":len(route)})
                    except Exception:
                        pass
        mission_data = {"route":route,"threats":threats,"flightplan":fplan}
        return {"status":"ok"}
    except Exception as e:
        return {"status":"error","message":str(e)}

#  AUTO-LOADER .INI MISSION BMS
#  Surveille les dossiers BMS connus et charge le dernier .ini modifié
import glob as _glob, configparser as _configparser

_ini_last_path: str = ""
_ini_last_mtime: float = 0.0

INI_SEARCH_PATHS = [
    r"C:\Falcon BMS 4.38\User\DTC\*.ini",
    r"C:\Falcon BMS 4.37\User\DTC\*.ini",
    r"C:\Falcon BMS 4.38\User\Acmi\*.ini",
    r"D:\Falcon BMS 4.38\User\DTC\*.ini",
    r"D:\Falcon BMS 4.37\User\DTC\*.ini",
]

def _find_latest_ini() -> tuple[str, float]:
    """Trouve le .ini BMS le plus récemment modifié."""
    # Ajouter chemin depuis registre BMS
    patterns = list(INI_SEARCH_PATHS)
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\WOW6432Node\Benchmark Sims\Falcon BMS 4.38")
        install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
        patterns.insert(0, os.path.join(install_dir, "User", "DTC", "*.ini"))
    except Exception:
        pass
    files = []
    for pat in patterns:
        try: files.extend(_glob.glob(pat))
        except Exception: pass
    if not files:
        return "", 0.0
    best = max(files, key=os.path.getmtime)
    return best, os.path.getmtime(best)

def _parse_ini_file(path: str) -> dict:
    """Parse un .ini BMS et retourne mission_data."""
    global mission_data
    try:
        with open(path, encoding="latin-1") as f:
            raw = f.read()
        cfg = _configparser.ConfigParser()
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
                            lat, lon = bms_to_latlon(x, y)
                            kl = key.lower()
                            if "line" in kl:
                                fplan.append({"lat": lat, "lon": lon, "alt": z, "index": len(fplan)})
                            elif "ppt" in kl:
                                try:
                                    r_ft = float(parts[3])
                                    range_m = int(r_ft * 0.3048)
                                    range_nm = max(1, round(r_ft / 6076.12))
                                except:
                                    range_m = 27800; range_nm = 15
                                name_ppt = parts[4].strip() if len(parts) > 4 else ""
                                try:    ppt_num = 56 + int(kl.replace("ppt_", "").strip())
                                except: ppt_num = 56 + len(threats)
                                if 30.0 <= lat <= 44.0 and 120.0 <= lon <= 135.0:
                                    threats.append({"lat": lat, "lon": lon, "name": name_ppt,
                                                    "range_nm": range_nm, "range_m": range_m,
                                                    "num": ppt_num, "index": len(threats)})
                            else:
                                route.append({"lat": lat, "lon": lon, "alt": z, "index": len(route)})
                    except Exception:
                        pass
        result = {"route": route, "threats": threats, "flightplan": fplan}
        mission_data = result
        logger.info(f"INI auto-chargé: {os.path.basename(path)} — {len(route)} steerpoints, {len(threats)} PPT")
        return result
    except Exception as e:
        logger.error(f"INI parse error: {e}")
        return {}

async def _ini_watcher_loop():
    """Tâche asyncio: surveille et charge automatiquement le dernier .ini BMS."""
    global _ini_last_path, _ini_last_mtime
    _ini_startup = _time.time()
    while True:
        try:
            path, mtime = _find_latest_ini()
            # Ignorer les .ini trop anciens au premier démarrage (> 30 min)
            _age = _time.time() - mtime
            _is_first = _ini_last_path == ""
            if path and (path != _ini_last_path or mtime > _ini_last_mtime + 1):
                if _is_first and _age > 1800:
                    pass  # INI trop ancien au premier démarrage — ignoré
                else:
                    _ini_last_path = path
                    _ini_last_mtime = mtime
                    _parse_ini_file(path)
        except Exception:
            pass
        await asyncio.sleep(3)  # vérifier toutes les 3s


#  HTML / CSS / JS
HTML = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Falcon-Pad</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
.leaflet-popup-content-wrapper{background:transparent!important;border:none!important;box-shadow:none!important;padding:0!important}
.leaflet-popup-content{margin:0!important}
.leaflet-popup-tip-container{display:none}
.leaflet-popup-close-button{color:#94a3b8!important;font-size:16px!important;top:6px!important;right:8px!important}
.leaflet-popup-close-button:hover{color:#e2e8f0!important}
</style>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;overflow:hidden;background:#060a12}
#map{position:absolute;inset:0;bottom:72px;contain:layout;will-change:transform}

/* ═══ TOOLBAR ═════════════════════════════════════════════════════ */
#toolbar{
  position:absolute;top:80px;left:20px;z-index:1000;
  background:rgba(4,8,16,.94);
  backdrop-filter:blur(20px) saturate(1.4);
  border:1px solid rgba(74,222,128,.1);
  border-top:2px solid rgba(74,222,128,.35);
  border-radius:3px;
  padding:10px 7px;
  display:flex;flex-direction:column;gap:3px;
  box-shadow:0 24px 60px rgba(0,0,0,.8),inset 0 1px 0 rgba(74,222,128,.08);
  will-change:transform;
}
#toolbar::before{
  content:'';position:absolute;left:0;top:10px;bottom:10px;width:2px;
  background:linear-gradient(180deg,transparent,rgba(74,222,128,.55),transparent);
  border-radius:2px;
}
#toolbar::after{
  content:'FALCON-PAD';
  position:absolute;top:-9px;left:12px;
  background:rgba(4,8,16,1);padding:0 6px;
  font-family:system-ui,sans-serif;font-size:9px;font-weight:700;
  letter-spacing:2px;color:rgba(74,222,128,.75);text-transform:uppercase;
}
.tool-btn{
  width:40px;height:40px;border-radius:2px;cursor:pointer;
  background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.05);
  display:flex;align-items:center;justify-content:center;
  position:relative;transition:all .15s ease;overflow:hidden;
}
.tool-btn svg{stroke:#5a8c70;transition:all .15s;z-index:1;position:relative;fill:none;stroke-linecap:round;stroke-linejoin:round;}
.tool-btn:hover{background:rgba(74,222,128,.07);border-color:rgba(74,222,128,.5);transform:translateX(2px);box-shadow:inset 2px 0 0 rgba(74,222,128,.45);}
.tool-btn:hover svg{stroke:#4ade80}
.tool-btn.active{background:rgba(74,222,128,.1);border-color:rgba(74,222,128,.35);box-shadow:inset 2px 0 0 #4ade80,0 0 12px rgba(74,222,128,.12);}
.tool-btn.active svg{stroke:#4ade80}
.tool-btn.danger svg{stroke:#ef4444}
.tool-btn.danger:hover{background:rgba(239,68,68,.08);border-color:rgba(239,68,68,.3);box-shadow:inset 2px 0 0 rgba(239,68,68,.5);}
.tool-divider{height:1px;margin:4px 4px;background:linear-gradient(90deg,transparent,rgba(74,222,128,.18),transparent);}

/* ═══ STATUS BAR ══════════════════════════════════════════════════ */
/* statusBar supprimé — intégré dans #sysBar sous la tabBar */
.dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.dot.off{background:#ef4444;box-shadow:0 0 6px rgba(239,68,68,.7);animation:blink 2s infinite}
.dot.on{background:#10b981;box-shadow:0 0 6px rgba(16,185,129,.7);animation:glow 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes glow{0%,100%{opacity:1}50%{opacity:.5}}

/* ═══ SYSTEM STATUS BAR (sous tab bar) ════════════════════════════ */
#sysBar{
  position:fixed;bottom:50px;left:0;right:0;height:22px;z-index:1999;
  background:rgba(1,3,8,.98);
  border-top:1px solid rgba(74,222,128,.07);
  display:flex;align-items:center;padding:0 14px;gap:0;
  box-shadow:0 -4px 20px rgba(0,0,0,.6);
}
/* Segment gauche: BMS status */
.sys-left{display:flex;align-items:center;gap:7px;flex:1;min-width:0}
/* Segment centre: copyright */
.sys-center{
  position:absolute;left:50%;transform:translateX(-50%);
  display:flex;align-items:center;gap:6px;white-space:nowrap;
}
/* Segment droite: zulu + site */
.sys-right{display:flex;align-items:center;gap:8px;margin-left:auto;flex-shrink:0}

.sys-bms-tag{
  font-family:'Consolas','Courier New',monospace;font-size:9px;
  color:rgba(74,222,128,.45);letter-spacing:2px;text-transform:uppercase;
}
#statusText{
  font-family:system-ui,sans-serif;font-size:9px;font-weight:700;
  letter-spacing:1.5px;text-transform:uppercase;color:rgba(148,163,184,.45);
  white-space:nowrap;
}
.sys-sep{width:1px;height:9px;background:rgba(255,255,255,.06);margin:0 8px;flex-shrink:0}

/* Signature tactique centrale */
.sys-sig{
  display:flex;align-items:center;gap:5px;
}
.sys-sig-line{width:18px;height:1px;background:linear-gradient(90deg,transparent,rgba(74,222,128,.25))}
.sys-sig-line.r{background:linear-gradient(90deg,rgba(74,222,128,.25),transparent)}
.sys-sig-text{
  font-family:system-ui,sans-serif;font-size:9px;font-weight:700;
  color:rgba(255,255,255,.28);letter-spacing:2.5px;text-transform:uppercase;
}
.sys-sig-author{
  font-family:'Consolas','Courier New',monospace;font-size:9px;
  color:rgba(74,222,128,.55);letter-spacing:1px;
}
.sys-sig-dot{width:3px;height:3px;border-radius:50%;background:rgba(74,222,128,.2);flex-shrink:0}

/* Zulu */
.sys-zulu{
  font-family:'Consolas','Courier New',monospace;font-size:9px;
  color:rgba(74,222,128,.4);letter-spacing:1.5px;
}
/* Server IP */
.sys-ip{
  font-family:'Consolas','Courier New',monospace;font-size:9px;
  color:rgba(96,165,250,.35);letter-spacing:1px;
  padding:1px 6px;border:1px solid rgba(96,165,250,.08);border-radius:1px;
  cursor:default;transition:color .25s;
}
.sys-ip:hover{color:rgba(96,165,250,.75);border-color:rgba(96,165,250,.25)}
/* Falcon Charts link */
.sys-fc{
  font-family:system-ui,sans-serif;font-size:9px;font-weight:700;
  color:rgba(74,222,128,.45);letter-spacing:2px;text-transform:uppercase;
  text-decoration:none;transition:color .25s;
  padding:1px 6px;border:1px solid rgba(74,222,128,.06);border-radius:1px;
}
.sys-fc:hover{color:rgba(74,222,128,.7);border-color:rgba(74,222,128,.5);background:rgba(74,222,128,.04)}

/* ═══ SETTINGS GEAR BUTTON ══════════════════════════════════════ */
#settingsBtn{
  cursor:pointer;background:transparent;border:none;padding:0 8px;
  height:100%;display:flex;align-items:center;
  color:rgba(74,222,128,.3);transition:color .2s;
  flex-shrink:0;
}
#settingsBtn:hover{color:rgba(74,222,128,.7)}
#settingsBtn svg{width:13px;height:13px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;transition:transform .4s}
#settingsBtn:hover svg{transform:rotate(60deg)}

/* ═══ SETTINGS PANEL ════════════════════════════════════════════ */
#settingsPanel{
  display:none;position:fixed;bottom:72px;right:14px;z-index:3000;
  width:320px;
  background:rgba(3,7,18,.98);
  border:1px solid rgba(74,222,128,.15);
  border-top:2px solid rgba(74,222,128,.4);
  border-radius:3px;
  backdrop-filter:blur(24px);
  box-shadow:0 -12px 48px rgba(0,0,0,.7);
  overflow:hidden;
}
#settingsPanel.open{display:block}
.sp-header{
  display:flex;align-items:center;gap:8px;padding:10px 14px;
  border-bottom:1px solid rgba(74,222,128,.08);
}
.sp-title{
  font-family:system-ui,sans-serif;font-size:11px;font-weight:700;
  color:#4ade80;letter-spacing:2px;text-transform:uppercase;
}
.sp-close{
  margin-left:auto;background:transparent;border:none;cursor:pointer;
  color:rgba(148,163,184,.4);font-size:16px;line-height:1;padding:0 2px;
  transition:color .15s;
}
.sp-close:hover{color:#94a3b8}
.sp-body{padding:12px 14px;display:flex;flex-direction:column;gap:10px}
.sp-row{display:flex;flex-direction:column;gap:4px}
.sp-label{
  font-family:system-ui,sans-serif;font-size:10px;font-weight:700;
  color:#4a6e80;letter-spacing:1.5px;text-transform:uppercase;
}
.sp-input{
  background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);
  border-radius:2px;padding:7px 10px;color:#e2e8f0;
  font-family:'Consolas','Courier New',monospace;font-size:13px;outline:none;width:100%;
  transition:border-color .2s;
}
.sp-input:focus{border-color:rgba(74,222,128,.4)}
.sp-hint{
  font-family:system-ui,sans-serif;font-size:10px;
  color:rgba(148,163,184,.3);line-height:1.4;
}
.sp-warn{
  font-family:system-ui,sans-serif;font-size:10px;font-weight:700;
  color:#fbbf24;letter-spacing:.5px;display:none;
}
.sp-warn.show{display:block}
.sp-divider{height:1px;background:linear-gradient(90deg,transparent,rgba(74,222,128,.1),transparent);margin:2px 0}
.sp-footer{padding:10px 14px;border-top:1px solid rgba(74,222,128,.08);display:flex;gap:8px}
.sp-save{
  flex:1;background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.3);
  border-radius:2px;padding:7px;color:#4ade80;
  font-family:system-ui,sans-serif;font-size:12px;font-weight:700;
  letter-spacing:1.5px;text-transform:uppercase;cursor:pointer;transition:all .2s;
}
.sp-save:hover{background:rgba(74,222,128,.2);border-color:rgba(74,222,128,.6)}
.sp-cancel{
  background:transparent;border:1px solid rgba(255,255,255,.08);
  border-radius:2px;padding:7px 12px;color:#546e82;
  font-family:system-ui,sans-serif;font-size:12px;font-weight:700;
  cursor:pointer;transition:all .2s;
}
.sp-cancel:hover{border-color:rgba(255,255,255,.2);color:#94a3b8}
.sp-theme-row{display:flex;gap:6px}
.sp-theme-btn{
  flex:1;padding:6px;border-radius:2px;cursor:pointer;
  font-family:system-ui,sans-serif;font-size:11px;font-weight:700;
  letter-spacing:1px;text-transform:uppercase;transition:all .2s;
  border:1px solid rgba(255,255,255,.08);background:transparent;color:#546e82;
}
.sp-theme-btn.sel{border-color:rgba(74,222,128,.4);background:rgba(74,222,128,.08);color:#4ade80}
.sp-status{
  font-family:'Consolas','Courier New',monospace;font-size:10px;
  color:#4ade80;letter-spacing:1px;display:none;padding:6px 14px;
  border-top:1px solid rgba(74,222,128,.08);text-align:center;
}
.sp-status.show{display:block}
/* TRTT gear btn */
#trttConfigBtn{cursor:pointer;font-size:10px;color:rgba(148,163,184,.45);user-select:none;transition:color .2s;line-height:1}
#trttConfigBtn:hover{color:rgba(148,163,184,.6)}

/* ═══ RULER LABEL ══════════════════════════════════════════════════ */
.ruler-label{
  display:inline-flex;flex-direction:column;align-items:flex-start;
  background:rgba(2,6,14,.9);
  border:1px solid rgba(74,222,128,.2);
  border-left:2px solid rgba(74,222,128,.65);
  border-radius:2px;padding:5px 12px 6px;
  pointer-events:none;white-space:nowrap;
  box-shadow:0 4px 20px rgba(0,0,0,.7);
  backdrop-filter:blur(10px);
}
.ruler-hdg{font-size:15px;font-weight:700;color:#4ade80;letter-spacing:2px;line-height:1.2;font-family:system-ui,sans-serif}
.ruler-nm{font-size:13px;font-weight:700;color:#e2e8f0;line-height:1.3;margin-top:2px;font-family:'Consolas','Courier New',monospace;letter-spacing:.5px}
.ruler-km{font-size:9px;color:#475569;line-height:1.2;margin-top:1px;font-family:'Consolas','Courier New',monospace}

/* ═══ ARROW LABEL ══════════════════════════════════════════════════ */
.arrow-label{
  display:inline-block;
  background:rgba(2,6,14,.88);
  border:1px solid rgba(255,255,255,.12);
  border-radius:2px;padding:2px 8px;
  font-family:'Consolas','Courier New',monospace;font-size:10px;
  color:#94a3b8;pointer-events:none;white-space:nowrap;
  box-shadow:0 2px 10px rgba(0,0,0,.5);
}

/* ═══ COLOR PANEL ══════════════════════════════════════════════════ */
#colorPanel{
  position:absolute;top:80px;left:74px;z-index:1010;
  background:rgba(4,8,16,.97);
  backdrop-filter:blur(20px);
  border:1px solid rgba(74,222,128,.15);
  border-top:2px solid rgba(74,222,128,.3);
  border-radius:3px;padding:14px;display:none;
  box-shadow:0 16px 48px rgba(0,0,0,.65)
}
#colorPanel.open{display:block}
#colorPanel h4{color:#94a3b8;font-size:9px;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px;font-family:system-ui,sans-serif}
.c-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}
.c-swatch{width:30px;height:30px;border-radius:4px;cursor:pointer;border:2px solid transparent;transition:all .15s}
.c-swatch:hover{transform:scale(1.18);border-color:rgba(255,255,255,.4)}
.c-swatch.sel{border-color:#fff;box-shadow:0 0 0 2px rgba(74,222,128,.5)}

/* ═══ LAYER PANEL ══════════════════════════════════════════════════ */
#layerPanel{
  position:absolute;bottom:78px;left:20px;z-index:1010;
  background:rgba(4,8,16,.97);
  backdrop-filter:blur(20px);
  border:1px solid rgba(74,222,128,.15);
  border-top:2px solid rgba(74,222,128,.3);
  border-radius:3px;padding:14px 16px;display:none;
  box-shadow:0 16px 48px rgba(0,0,0,.65)
}
#layerPanel.open{display:block}
#layerPanel h4{color:#94a3b8;font-size:9px;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px;font-family:system-ui,sans-serif}
.layer-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;cursor:pointer}
.layer-row:last-child{margin-bottom:0}
.layer-row input{accent-color:#4ade80;width:14px;height:14px;cursor:pointer}
.layer-row label{color:#cbd5e1;font-size:13px;font-family:system-ui,sans-serif;font-weight:600;cursor:pointer;letter-spacing:.5px}

/* ═══ NOTES / ANNOTATIONS ══════════════════════════════════════════ */
.note-wrapper{
  position:absolute;z-index:2000;min-width:170px;min-height:80px;
  border-radius:3px;overflow:hidden;
  box-shadow:0 8px 32px rgba(0,0,0,.55);
  display:flex;flex-direction:column;resize:both;
  border:1px solid rgba(255,255,255,.12)
}
.note-header{
  height:26px;flex-shrink:0;
  display:flex;align-items:center;justify-content:space-between;
  padding:0 7px;cursor:move;user-select:none;
  background:rgba(0,0,0,.25)
}
.note-header-colors{display:flex;align-items:center;gap:5px}
.note-mini-picker{width:16px;height:16px;border-radius:3px;cursor:pointer;border:1px solid rgba(255,255,255,.2);position:relative;overflow:hidden;flex-shrink:0}
.note-mini-picker input[type=color]{position:absolute;width:200%;height:200%;top:-50%;left:-50%;cursor:pointer;border:none;padding:0;opacity:0}
.note-mini-picker .swatch{position:absolute;inset:0;border-radius:2px;pointer-events:none}
.note-close{width:18px;height:18px;border-radius:2px;background:rgba(239,68,68,.12);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;color:#f87171;font-size:13px;line-height:1;transition:background .15s;flex-shrink:0}
.note-close:hover{background:rgba(239,68,68,.3)}
.note-body{flex:1;resize:none;border:none;outline:none;padding:8px 10px;font-size:13px;font-family:system-ui,sans-serif;font-weight:500;line-height:1.5;background:transparent}

/* ═══ DATALINK CONTACTS ════════════════════════════════════════════ */
/* Label principal contact */
.dl-block{
  display:flex;flex-direction:column;align-items:flex-start;
  pointer-events:none;white-space:nowrap;
}
.dl-callsign{
  font-family:system-ui,sans-serif;font-weight:700;
  font-size:12px;letter-spacing:.8px;line-height:1.2;
  text-shadow:0 1px 4px rgba(0,0,0,.9),0 0 8px rgba(0,0,0,.7);
  padding:1px 5px;border-radius:2px;
}
.dl-data{
  font-family:'Consolas','Courier New',monospace;
  font-size:10px;letter-spacing:.3px;line-height:1.2;
  text-shadow:0 1px 4px rgba(0,0,0,.9);
  padding:0 5px;opacity:.85;
}
.dl-callsign.friend{color:#4ade80}
.dl-callsign.foe{color:#f87171}
.dl-callsign.unknwn{color:#fbbf24}
.dl-data.friend{color:#86efac}
.dl-data.foe{color:#fca5a5}
.dl-data.unknwn{color:#fde68a}

/* ═══ AIRPORT LABELS ════════════════════════════════════════════════ */
.ap-label{
  font-family:'Consolas','Courier New',monospace;font-size:11px;font-weight:700;
  color:rgba(96,165,250,.9);letter-spacing:.8px;
  text-shadow:0 1px 4px #000,0 0 8px rgba(0,0,0,.9);
  white-space:nowrap;pointer-events:none;
}
.ap-name{
  font-family:system-ui,sans-serif;font-size:11px;font-weight:600;
  color:rgba(148,163,184,.85);letter-spacing:.3px;
  text-shadow:0 1px 4px #000;
  white-space:nowrap;pointer-events:none;
}
/* Popup aéroport — compact 2 lignes */
.ap-popup{
  background:rgba(4,8,18,.97);border:1px solid rgba(96,165,250,.2);
  border-top:2px solid rgba(96,165,250,.45);border-radius:3px;
  padding:8px 28px 8px 11px;min-width:200px;font-family:'Consolas','Courier New',monospace;
  box-shadow:0 4px 20px rgba(0,0,0,.7);white-space:nowrap;
}
/* Ligne 1 : ICAO · TACAN · TOUR */
.ap-l1{display:flex;align-items:center;gap:5px;font-size:13px;font-weight:700;margin-bottom:6px}
.ap-l1-icao{color:#60a5fa;letter-spacing:1px}
.ap-l1-dot{color:rgba(148,163,184,.25)}
.ap-l1-tacan{color:#fbbf24}          /* TACAN — ambre */
.ap-l1-freq{color:#4ade80}           /* Fréquence tour — vert */
/* Ligne 2 : chips ILS */
.ap-l2{display:flex;gap:6px;flex-wrap:wrap}
.ap-ils-chip{
  display:flex;align-items:center;gap:6px;
  background:rgba(251,191,36,.05);border:1px solid rgba(251,191,36,.15);
  border-radius:2px;padding:3px 8px;
}
.ap-ils-rwy{color:#fbbf24;font-size:12px;font-weight:700;letter-spacing:.5px}
.ap-ils-freq{color:#4ade80;font-size:12px}
.ap-ils-crs{color:#94a3b8;font-size:12px;font-weight:700}  /* CRS — gris clair lisible */

/* ═══ TOAST ════════════════════════════════════════════════════════ */
.bms-toast{
  position:fixed;bottom:80px;left:50%;transform:translateX(-50%);
  background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.3);
  color:#10b981;font-family:system-ui,sans-serif;font-size:11px;
  font-weight:700;letter-spacing:1.5px;padding:7px 16px;border-radius:2px;
  z-index:9999;pointer-events:none;text-transform:uppercase;
}

/* ═══ TAB BAR ══════════════════════════════════════════════════════ */
#tabBar{
  position:fixed;bottom:0;left:0;right:0;height:50px;z-index:2000;
  background:rgba(2,5,12,.98);
  backdrop-filter:blur(24px) saturate(1.6);
  border-top:1px solid rgba(74,222,128,.12);
  display:flex;align-items:stretch;
  box-shadow:0 -8px 32px rgba(0,0,0,.7);
}
#tabBar::before{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent 0%,rgba(74,222,128,.35) 30%,rgba(74,222,128,.35) 70%,transparent 100%);
}
/* Groupe de tabs */
.tab-group{
  display:flex;align-items:stretch;flex:1;position:relative;
}
/* Séparateur entre groupes */
.tab-group-sep{
  width:1px;flex-shrink:0;align-self:stretch;
  background:linear-gradient(180deg,transparent 10%,rgba(74,222,128,.22) 40%,rgba(74,222,128,.22) 60%,transparent 90%);
  position:relative;
}
.tab-group-sep::before{
  content:attr(data-label);
  position:absolute;top:50%;left:50%;
  transform:translate(-50%,-50%);
  background:rgba(2,5,12,.98);
  padding:2px 0;
  font-family:'Consolas','Courier New',monospace;font-size:7px;
  color:rgba(74,222,128,.5);letter-spacing:1px;
  white-space:nowrap;writing-mode:vertical-rl;text-orientation:mixed;
}
.tab-btn{
  flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:3px;cursor:pointer;background:transparent;border:none;
  border-right:1px solid rgba(255,255,255,.03);
  position:relative;transition:all .2s ease;
  padding:0 6px;outline:none;
}
.tab-btn:last-child{border-right:none}
.tab-btn::after{
  content:'';position:absolute;bottom:0;left:20%;right:20%;height:2px;
  background:rgba(74,222,128,.0);border-radius:2px 2px 0 0;
  transition:all .25s ease;
}
.tab-btn:hover{background:rgba(74,222,128,.04)}
.tab-btn:hover .tab-icon svg{stroke:rgba(74,222,128,.7)}
.tab-btn:hover .tab-label{color:rgba(74,222,128,.7)}
.tab-btn.active{background:rgba(74,222,128,.06)}
.tab-btn.active::after{background:rgba(74,222,128,.8)}
.tab-btn.active .tab-icon svg{stroke:#4ade80;filter:drop-shadow(0 0 6px rgba(74,222,128,.4))}
.tab-btn.active .tab-label{color:#4ade80}
/* Label de catégorie au-dessus des onglets */
.tab-group-label{
  position:absolute;top:3px;left:0;right:0;text-align:center;
  font-family:'Consolas','Courier New',monospace;font-size:7px;
  color:rgba(74,222,128,.38);letter-spacing:2px;text-transform:uppercase;
  pointer-events:none;
}
.tab-icon{width:20px;height:20px;display:flex;align-items:center;justify-content:center}
.tab-icon svg{stroke:#5a8c70;fill:none;stroke-linecap:round;stroke-linejoin:round;transition:all .2s}
.tab-label{
  font-family:system-ui,sans-serif;font-size:9px;font-weight:700;
  letter-spacing:1.5px;text-transform:uppercase;color:#4d7a62;
  transition:color .2s;white-space:nowrap;
}

/* ═══ TAB PANELS ════════════════════════════════════════════════════ */
.tab-panel{
  position:fixed;
  will-change:transform;
  contain:layout style;left:0;right:0;bottom:72px;z-index:1990;
  background:rgba(2,5,12,.99);
  backdrop-filter:blur(24px);
  border-top:1px solid rgba(74,222,128,.15);
  transform:translateY(100%);
  transition:transform .3s cubic-bezier(.4,0,.2,1);
  pointer-events:none;overflow:hidden;
}
.tab-panel.open{transform:translateY(0);pointer-events:all}

/* GPS panel — compact bar (map stays visible) */
#panel-gps{
  height:auto;
  border-top:2px solid rgba(59,130,246,.4);
  background:rgba(2,5,16,.97);
}
#panel-gps .gps-row{
  display:flex;align-items:center;gap:0;
  padding:8px 18px;
  border-bottom:1px solid rgba(255,255,255,.04);
}
.gps-field{
  display:flex;flex-direction:column;align-items:flex-start;
  padding:4px 16px;border-right:1px solid rgba(255,255,255,.06);
  flex:1;
}
.gps-field:last-child{border-right:none}
.gps-lbl{
  font-family:system-ui,sans-serif;font-size:11px;font-weight:700;
  color:#4a6e80;letter-spacing:1.5px;text-transform:uppercase;line-height:1;
}
.gps-val{
  font-family:'Consolas','Courier New',monospace;font-size:17px;
  color:#60a5fa;font-weight:400;line-height:1.4;letter-spacing:.5px;
}
.gps-val.green{color:#4ade80}
.gps-val.amber{color:#fbbf24}
.gps-val.white{color:#e2e8f0}
.gps-steer-list{
  display:flex;gap:6px;padding:6px 18px 10px;overflow-x:auto;
  scrollbar-width:none;
}
.gps-steer-list::-webkit-scrollbar{display:none}
.steer-chip{
  flex-shrink:0;background:rgba(255,255,255,.03);
  border:1px solid rgba(255,255,255,.08);border-radius:2px;
  padding:4px 10px;display:flex;flex-direction:column;align-items:center;
  cursor:pointer;transition:all .15s;
}
.steer-chip:hover{border-color:rgba(74,222,128,.3);background:rgba(74,222,128,.06)}
.steer-chip.active{border-color:rgba(74,222,128,.5);background:rgba(74,222,128,.08);border-left:2px solid #4ade80}
.steer-num{font-family:'Consolas','Courier New',monospace;font-size:11px;color:#475569;letter-spacing:1px}
.steer-fl{font-family:'Consolas','Courier New',monospace;font-size:13px;color:#94a3b8;font-weight:700}

/* CHARTS panel — fullscreen iframe */
#panel-charts{
  height:calc(100vh - 72px);top:0;bottom:72px;
  border-top:2px solid rgba(99,102,241,.4);
  display:flex;flex-direction:column;
}
#panel-charts .charts-header{
  height:36px;flex-shrink:0;
  background:rgba(2,5,16,.99);
  display:flex;align-items:center;gap:10px;padding:0 14px;
  border-bottom:1px solid rgba(99,102,241,.15);
}
#panel-charts .charts-header span{
  font-family:system-ui,sans-serif;font-size:13px;font-weight:700;
  color:#6366f1;letter-spacing:2px;text-transform:uppercase;
}
#panel-charts iframe{flex:1;border:none;background:#000}
.ext-badge{
  font-family:'Consolas','Courier New',monospace;font-size:9px;
  color:rgba(99,102,241,.5);letter-spacing:1px;
  background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.15);
  border-radius:2px;padding:1px 6px;margin-left:auto;
}

/* KNEEBOARD panel */
#panel-kneeboard{
  height:60vh;min-height:300px;
  border-top:2px solid rgba(251,191,36,.4);
  display:flex;flex-direction:column;
}
.kb-header{
  height:42px;flex-shrink:0;
  background:rgba(2,5,16,.99);
  display:flex;align-items:center;gap:10px;padding:0 16px;
  border-bottom:1px solid rgba(251,191,36,.12);
}
.kb-header-title{
  font-family:system-ui,sans-serif;font-size:13px;font-weight:700;
  color:#fbbf24;letter-spacing:2px;text-transform:uppercase;
}
.kb-tabs{display:flex;height:100%;margin-left:auto}
.kb-tab{
  height:100%;padding:0 16px;display:flex;align-items:center;
  font-family:system-ui,sans-serif;font-size:13px;font-weight:700;
  letter-spacing:1.5px;color:#546e82;text-transform:uppercase;cursor:pointer;
  border-bottom:2px solid transparent;transition:all .15s;border-left:1px solid rgba(255,255,255,.04);
}
.kb-tab:hover{color:#94a3b8;background:rgba(255,255,255,.02)}
.kb-tab.active{color:var(--kt,#fbbf24);border-bottom-color:var(--kt,#fbbf24)}
.kb-field-group{display:flex;flex-direction:column;gap:3px}
.kb-field-lbl{font-size:9px;font-weight:700;color:#475569;letter-spacing:1.5px;text-transform:uppercase}
.kb-input{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:2px;
  padding:6px 10px;color:#e2e8f0;font-family:'Consolas','Courier New',monospace;font-size:12px;
  outline:none;width:100%;transition:border-color .2s}
.kb-input:focus{border-color:rgba(96,165,250,.4)}
.kb-9l-num{font-family:'Consolas','Courier New',monospace;font-size:13px;font-weight:700;
  color:#f97316;width:20px;text-align:right;align-self:flex-end;padding-bottom:6px}
.kb-body{flex:1;overflow:hidden;position:relative}
.kb-page{position:absolute;inset:0;overflow-y:auto;padding:16px 20px;display:none}
.kb-page.active{display:block}
.kb-page::-webkit-scrollbar{width:4px}
.kb-page::-webkit-scrollbar-track{background:transparent}
.kb-page::-webkit-scrollbar-thumb{background:rgba(74,222,128,.2);border-radius:2px}
/* Brevity */
.brev-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:9px}
.brev-item{background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.07);border-radius:2px;padding:10px 14px}
.brev-word{font-family:'Consolas','Courier New',monospace;font-size:15px;color:#fbbf24;font-weight:700;letter-spacing:.5px}
.brev-def{font-family:system-ui,sans-serif;font-size:14px;color:#64748b;margin-top:3px;line-height:1.45}
/* Freq table */
.freq-table{width:100%;border-collapse:collapse;font-family:system-ui,sans-serif}
.freq-table th{font-size:12px;font-weight:700;color:#546e82;letter-spacing:1.5px;text-transform:uppercase;padding:7px 12px;border-bottom:1px solid rgba(255,255,255,.06);text-align:left}
.freq-table td{font-size:15px;color:#94a3b8;padding:7px 12px;border-bottom:1px solid rgba(255,255,255,.03)}
.freq-table td:first-child{color:#e2e8f0;font-weight:700}
.freq-table td.hi{color:#4ade80;font-family:'Consolas','Courier New',monospace}
/* Notes */
.kb-notes{width:100%;height:100%;resize:none;background:transparent;border:none;outline:none;
  font-family:'Consolas','Courier New',monospace;font-size:14px;color:#94a3b8;line-height:1.8;padding:4px 0}

/* ═══ BRIEFING PANEL ════════════════════════════════════════════ */
#panel-briefing{
  height:calc(100vh - 72px);top:0;bottom:72px;
  border-top:2px solid rgba(251,191,36,.45);
  display:flex;flex-direction:column;
}
.brief-header{
  height:44px;flex-shrink:0;background:rgba(2,5,16,.99);
  display:flex;align-items:center;gap:10px;padding:0 14px;
  border-bottom:1px solid rgba(251,191,36,.12);
}
.brief-header-title{
  font-family:system-ui,sans-serif;font-size:13px;font-weight:700;
  color:#fbbf24;letter-spacing:2px;text-transform:uppercase;
}
.brief-upload-btn{
  margin-left:auto;display:flex;align-items:center;gap:6px;
  background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.25);
  border-radius:2px;padding:5px 12px;cursor:pointer;
  font-family:system-ui,sans-serif;font-size:10px;font-weight:700;
  color:#fbbf24;letter-spacing:1.5px;text-transform:uppercase;transition:all .2s;
}
.brief-upload-btn:hover{background:rgba(251,191,36,.15);border-color:rgba(251,191,36,.5)}
.brief-body{flex:1;display:flex;overflow:hidden}
.brief-sidebar{
  width:210px;flex-shrink:0;background:rgba(1,3,10,.98);
  border-right:1px solid rgba(255,255,255,.05);
  display:flex;flex-direction:column;overflow:hidden;
}
.brief-sidebar-hdr{
  padding:8px 12px;font-family:system-ui,sans-serif;font-size:9px;
  font-weight:700;color:#3d6b52;letter-spacing:2px;text-transform:uppercase;
  border-bottom:1px solid rgba(255,255,255,.04);flex-shrink:0;
}
.brief-file-list{flex:1;overflow-y:auto;padding:4px 0}
.brief-file-list::-webkit-scrollbar{width:3px}
.brief-file-list::-webkit-scrollbar-thumb{background:rgba(251,191,36,.15)}
.brief-file-item{
  display:flex;align-items:center;gap:8px;padding:8px 10px;
  cursor:pointer;border-left:2px solid transparent;transition:all .15s;position:relative;
}
.brief-file-item:hover{background:rgba(255,255,255,.03);border-left-color:rgba(251,191,36,.3)}
.brief-file-item.active{background:rgba(251,191,36,.06);border-left-color:#fbbf24}
.brief-file-icon{
  width:26px;height:30px;border-radius:2px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-family:system-ui,sans-serif;font-size:7px;font-weight:700;letter-spacing:.5px;
}
.brief-file-icon.pdf{background:rgba(239,68,68,.1);color:#f87171;border:1px solid rgba(239,68,68,.2)}
.brief-file-icon.img{background:rgba(74,222,128,.07);color:#4ade80;border:1px solid rgba(74,222,128,.15)}
.brief-file-icon.docx{background:rgba(59,130,246,.08);color:#60a5fa;border:1px solid rgba(59,130,246,.18)}
.brief-file-info{flex:1;min-width:0}
.brief-file-name{
  font-family:system-ui,sans-serif;font-size:13px;font-weight:700;
  color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.brief-file-item.active .brief-file-name{color:#fbbf24}
.brief-file-meta{font-family:'Consolas','Courier New',monospace;font-size:10px;color:#3d6b52;margin-top:2px}
.brief-file-del{
  opacity:0;font-size:13px;color:#546e82;cursor:pointer;
  transition:all .15s;padding:2px 4px;position:absolute;right:4px;top:50%;transform:translateY(-50%);
}
.brief-file-item:hover .brief-file-del{opacity:1}
.brief-file-del:hover{color:#ef4444}
.brief-empty{padding:28px 12px;text-align:center;font-family:system-ui,sans-serif;font-size:11px;color:#3d6b52;line-height:1.8}
.brief-viewer{flex:1;overflow:hidden;position:relative;background:#04080f}
.brief-viewer iframe{width:100%;height:100%;border:none}
.brief-placeholder{
  position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:10px;pointer-events:none;
}
.brief-placeholder svg{opacity:.06}
.brief-placeholder-txt{font-family:system-ui,sans-serif;font-size:11px;font-weight:700;color:#3d6b52;letter-spacing:2px;text-transform:uppercase}
#briefingFileInput{display:none}

/* ═══ RESPONSIVE & TACTILE ══════════════════════════════════════ */

/* ── Cibles tactiles minimum (WCAG 2.5.5) ── */
.tab-btn,.tbtn2   { min-height:48px }
.tool-btn         { min-height:48px; min-width:48px }
#settingsBtn      { min-width:40px; min-height:28px }
.kb-tab           { min-height:40px; padding:0 12px }
.layer-row        { min-height:36px }

/* ── Tablet paysage (768px+) — layout optimisé ── */
@media (min-width:768px) {
  .tool-btn     { width:44px; height:44px }
  .tab-label    { font-size:12px }
  .gps-val      { font-size:16px }
  .gps-lbl      { font-size:11px }
  /* Briefing sidebar plus large */
  .brief-sidebar{ width:240px }
}

/* ── Grand écran (1200px+) ── */
@media (min-width:1200px) {
  #toolbar      { top:100px }
  .tab-label    { font-size:13px; letter-spacing:.5px }
  .gps-val      { font-size:18px }
  .brief-sidebar{ width:280px }
  .brev-grid    { grid-template-columns:repeat(3,1fr) }
}

/* ── Mobile portrait (≤600px) ── */
@media (max-width:600px) {
  /* Toolbar horizontal en bas */
  #toolbar{
    top:auto;bottom:72px;left:50%;transform:translateX(-50%);
    flex-direction:row;padding:6px 8px;gap:3px;
    border-top:2px solid rgba(74,222,128,.35);
    border-left:none;
  }
  .tbdiv{width:1px;height:24px;margin:0 2px;
    background:linear-gradient(180deg,transparent,rgba(74,222,128,.15),transparent)}
  /* Panels full height */
  #panel-charts,#panel-briefing,#panel-kneeboard{height:calc(100vh - 72px)}
  /* GPS responsive */
  #panel-gps .gps-row{flex-wrap:wrap}
  .gps-field{flex:0 0 50%;border-right:none;border-bottom:1px solid rgba(255,255,255,.04)}
  /* Settings full width */
  #settingsPanel{left:8px;right:8px;width:auto}
  /* Tab labels */
  .tab-label{font-size:11px;letter-spacing:.5px}
  /* SysBar compressé */
  .sys-ip{display:none}
  /* Police lisible sur petit écran */
  .dl-callsign{font-size:11px}
  .dl-data    {font-size:10px}
  .ap-label   {font-size:10px}
  /* Briefing sidebar réduite */
  .brief-sidebar{width:160px}
  .brief-file-name{font-size:11px}
}

/* ── Très petit (≤400px) ── */
@media (max-width:400px) {
  .sys-center,.sys-fc{display:none}
  .tab-label{font-size:10px}
  .brief-sidebar{width:130px}
}

/* ── Notch / safe-area (iPhone X+) ── */
@supports (padding-bottom:env(safe-area-inset-bottom)){
  #tabBar{padding-bottom:env(safe-area-inset-bottom)}
  #sysBar{padding-bottom:env(safe-area-inset-bottom)}
}

/* ── Touch feedback (animation GPU) ── */
.tab-btn:active,.tbtn2:active{
  background:rgba(74,222,128,.12)!important;
  transform:scale(.97);
  transition:transform .05s;
}
.tool-btn:active{
  background:rgba(74,222,128,.15)!important;
  transform:translateX(3px) scale(.95);
}
.brief-file-item:active{background:rgba(74,222,128,.08)!important}
.ap-ils-chip:active{background:rgba(251,191,36,.12)!important}
.kb-tab:active{opacity:.7}

/* ── Pointeur grossier (tactile) ── */
@media (pointer:coarse){
  /* Scrollbars plus larges */
  .brief-file-list::-webkit-scrollbar{width:8px}
  .kb-page::-webkit-scrollbar        {width:8px}
  /* Pas de sélection accidentelle */
  #map,#tabBar,#sysBar,#toolbar{
    user-select:none;-webkit-user-select:none;
    -webkit-tap-highlight-color:transparent;
  }
  /* Hover désactivé (pas pertinent au tactile) */
  .tool-btn:hover{transform:none}
  /* Touch action optimisé */
  #map{touch-action:pan-x pan-y pinch-zoom}
  .tool-btn,.tab-btn,.kb-tab{touch-action:manipulation}
}

/* ── Paysage mobile (hauteur réduite) ── */
@media (max-height:500px) and (orientation:landscape){
  #toolbar{top:60px}
  #sysBar{height:18px;font-size:8px}
  .tab-btn{min-height:40px}
  .gps-val{font-size:13px}
}

/* ── Réduction mouvement (accessibilité) ── */
@media (prefers-reduced-motion:reduce){
  *{animation-duration:.01ms!important;transition-duration:.01ms!important}
}
</style></head><body>
<div id="map"></div>

<div id="toolbar">
  
  <button class="tool-btn" id="uploadBtn" title="Importer .ini">
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2">
      <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>
      <polyline points="13 2 13 9 20 9"/>
      <line x1="12" y1="13" x2="12" y2="19"/><line x1="9" y1="16" x2="15" y2="16"/>
    </svg>
  </button>
  
  <button class="tool-btn" id="annotationBtn" title="Note tactique">
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2">
      <path d="M12 20h9"/>
      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
    </svg>
  </button>
  
  <button class="tool-btn" id="rulerBtn" title="Règle / Distance">
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2">
      <rect x="2" y="7" width="20" height="10" rx="2"/>
      <line x1="6" y1="7" x2="6" y2="10"/><line x1="10" y1="7" x2="10" y2="12"/>
      <line x1="14" y1="7" x2="14" y2="10"/><line x1="18" y1="7" x2="18" y2="10"/>
    </svg>
  </button>
  
  <button class="tool-btn" id="arrowBtn" title="Tracer une flèche">
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2">
      <line x1="5" y1="19" x2="19" y2="5"/>
      <polyline points="9 5 19 5 19 15"/>
    </svg>
  </button>
  
  <button class="tool-btn danger" id="clearArrowsBtn" title="Effacer les tracés">
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2">
      <polyline points="3 6 5 6 21 6"/>
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
      <path d="M10 11v6"/><path d="M14 11v6"/>
    </svg>
  </button>
  <div class="tool-divider"></div>
  
  <button class="tool-btn" id="colorBtn" title="Couleur active">
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2">
      <circle cx="13.5" cy="6.5" r="1" fill="currentColor"/><circle cx="17.5" cy="10.5" r="1" fill="currentColor"/>
      <circle cx="8.5" cy="7.5" r="1" fill="currentColor"/><circle cx="6.5" cy="12.5" r="1" fill="currentColor"/>
      <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>
    </svg>
  </button>
  <div class="tool-divider"></div>
  
  <button class="tool-btn active" id="pptBtn" title="Cercles de menace PPT">
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2">
      <circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/>
    </svg>
  </button>
  
  <button class="tool-btn active" id="airportBtn" title="Aéroports">
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2">
      <path d="M17.8 19.2L16 11l3.5-3.5C21 6 21 4 19 4c-2 0-4 0-5.5 1.5L10 9 1.8 7.2c-.5-.1-.9.4-.8.9L3 11l3-1 .8 2.8L5 14l2 2 1.2-1.8L10 15l-1 3 3.1 1c.4.1 1-.3.9-.8z"/>
    </svg>
  </button>
  
  <button class="tool-btn" id="radarBtn" title="Contacts datalink L16">
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2">
      <circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/>
      <circle cx="12" cy="12" r="2" fill="currentColor" stroke="none"/>
      <line x1="12" y1="2" x2="12" y2="6"/>
    </svg>
  </button>

  
  <button class="tool-btn active" id="followBtn" title="Centrer sur l'avion (actif)">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="9" stroke-dasharray="4 2"/>
      <line x1="12" y1="2" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22"/>
      <line x1="2" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="22" y2="12"/>
    </svg>
  </button>

  
  <button class="tool-btn" id="layerBtn" title="Fonds de carte">
    <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="2">
      <polygon points="12 2 2 7 12 12 22 7 12 2"/>
      <polyline points="2 17 12 22 22 17"/>
      <polyline points="2 12 12 17 22 12"/>
    </svg>
  </button>
</div>

<!-- SYSTEM STATUS BAR -->
<div id="sysBar">
  <!-- Gauche: BMS status -->
  <div class="sys-left">
    <div class="dot off" id="dot"></div>
    <span class="sys-bms-tag">BMS</span>
    <span id="statusText">NON DÉTECTÉ</span>
    <span id="trttConfigBtn" title="Serveur TRTT" onclick="toggleTRTTPanel()">⚙</span>
  </div>
  <!-- Centre: signature -->
  <div class="sys-center">
    <div class="sys-sig">
      <div class="sys-sig-line"></div>
      <div class="sys-sig-dot"></div>
      <span class="sys-sig-text">FALCON-PAD</span>
      <span class="sys-sig-author">by RIESU</span>
      <div class="sys-sig-dot"></div>
      <div class="sys-sig-line r"></div>
    </div>
  </div>
  <!-- Droite: IP serveur + zulu + site + settings -->
  <div class="sys-right">
    <span id="sysServerIp" class="sys-ip" title="URL tablette/mobile">—</span>
    <div class="sys-sep"></div>
    <span id="zuluClock" class="sys-zulu">00:00:00Z</span>
    <div class="sys-sep"></div>
    <a href="https://www.falcon-charts.com" target="_blank" class="sys-fc">FALCON-CHARTS</a>
    <div class="sys-sep"></div>
    <button id="settingsBtn" onclick="toggleSettings()" title="Settings">
      <svg viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
    </button>
  </div>
</div>

<!-- ═══ SETTINGS PANEL ════════════════════════════════════════ -->
<div id="settingsPanel">
  <div class="sp-header">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
    <span class="sp-title">SETTINGS</span>
    <button class="sp-close" onclick="toggleSettings()">✕</button>
  </div>
  <div class="sp-body">
    <!-- Port -->
    <div class="sp-row">
      <label class="sp-label">PORT D'ÉCOUTE</label>
      <input class="sp-input" id="sp-port" type="number" min="1024" max="65535" placeholder="8000"/>
      <span class="sp-hint">Plage valide : 1024 – 65535. Redémarrage requis.</span>
      <span class="sp-warn" id="sp-port-warn">⚠ Modification du port — relancez le script pour appliquer</span>
    </div>
    <div class="sp-divider"></div>
    <!-- Dossier briefing -->
    <div class="sp-row">
      <label class="sp-label">DOSSIER BRIEFING</label>
      <input class="sp-input" id="sp-briefdir" type="text" placeholder="C:\temp\gpsbyriesu\briefing"/>
      <span class="sp-hint">Chemin absolu Windows. Créé automatiquement si inexistant.</span>
    </div>
    <div class="sp-divider"></div>
    <!-- Broadcast interval -->
    <div class="sp-row">
      <label class="sp-label">BROADCAST INTERVAL</label>
      <input class="sp-input" id="sp-bcast" type="number" min="50" max="2000" placeholder="200"/>
      <span class="sp-hint">Fréquence de mise à jour position (ms). 100 = fluide, 500 = économie.</span>
    </div>
    <div class="sp-divider"></div>
    <!-- Thème -->
    <div class="sp-row">
      <label class="sp-label">THÈME</label>
      <div class="sp-theme-row">
        <button class="sp-theme-btn sel" id="sp-theme-dark"  onclick="selectTheme('dark')">◼ DARK</button>
        <button class="sp-theme-btn"     id="sp-theme-light" onclick="selectTheme('light')">◻ LIGHT</button>
      </div>
    </div>
  </div>
  <div class="sp-status" id="sp-status"></div>
  <div class="sp-footer">
    <button class="sp-cancel" onclick="toggleSettings()">ANNULER</button>
    <button class="sp-save"   onclick="saveSettings()">✓ SAUVEGARDER</button>
  </div>
</div>

<!-- COLOR PANEL -->
<div id="colorPanel">
  <h4>Couleur active</h4>
  <div class="c-grid" id="cGrid"></div>
</div>

<!-- LAYER PANEL -->
<div id="layerPanel">
  <h4>Fond de carte</h4>
  <div class="layer-row"><input type="radio" name="layer" id="lDark" value="dark" checked><label for="lDark">Dark</label></div>
  <div class="layer-row"><input type="radio" name="layer" id="lOsm" value="osm"><label for="lOsm">OSM (fallback)</label></div>
  <div class="layer-row"><input type="radio" name="layer" id="lSat" value="satellite"><label for="lSat">Satellite</label></div>
  <div class="layer-row"><input type="radio" name="layer" id="lTerrain" value="terrain"><label for="lTerrain">Terrain</label></div>
  <div class="tool-divider" style="margin:8px 0"></div>
  <h4 style="margin-top:4px">Affichage</h4>
  <div class="layer-row"><input type="checkbox" id="chkDMZ" checked><label for="chkDMZ">DMZ</label></div>
  <div class="layer-row" style="padding-left:14px"><input type="checkbox" id="chkApName"><label for="chkApName" style="font-size:10px;color:#94a3b8">Nom base aérienne</label></div>
  <div class="layer-row" style="padding-left:14px"><input type="checkbox" id="chkRunways" checked><label for="chkRunways" style="font-size:10px;color:#94a3b8">Pistes</label></div>
</div>

<!-- TRTT PANEL -->
<div id="trttPanel" style="display:none;position:fixed;bottom:78px;left:20px;background:rgba(4,8,16,.97);border:1px solid rgba(74,222,128,.2);border-top:2px solid rgba(74,222,128,.35);border-radius:3px;padding:12px 16px;z-index:2000;min-width:280px;backdrop-filter:blur(16px)">
  <div style="font-family:system-ui,sans-serif;font-size:9px;font-weight:700;color:#4ade80;letter-spacing:2px;margin-bottom:10px;text-transform:uppercase">⚙ Serveur TRTT</div>
  <div style="display:flex;gap:8px;align-items:center">
    <input id="trttHostInput" type="text" placeholder="127.0.0.1" style="flex:1;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);border-radius:2px;padding:5px 9px;color:#e2e8f0;font-family:'Consolas','Courier New',monospace;font-size:11px;outline:none">
    <input id="trttPortInput" type="text" placeholder="42674" style="width:58px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);border-radius:2px;padding:5px 9px;color:#e2e8f0;font-family:'Consolas','Courier New',monospace;font-size:11px;outline:none">
    <button onclick="applyTRTTConfig()" style="background:rgba(74,222,128,.12);border:1px solid rgba(74,222,128,.3);border-radius:2px;padding:5px 12px;color:#4ade80;font-family:system-ui,sans-serif;font-size:11px;font-weight:700;cursor:pointer;letter-spacing:1px">OK</button>
  </div>
  <div id="trttPanelStatus" style="font-family:'Consolas','Courier New',monospace;font-size:10px;color:#475569;margin-top:8px"></div>
</div>

<input type="file" id="fileInput" accept=".ini" style="display:none">

<script>
const map = L.map('map',{preferCanvas:true,zoomControl:true}).setView([37.5,127.5],7);
const layers = {
  osm:       L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:''}),
  osmfr:     L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png',{maxZoom:20,subdomains:'abc',attribution:''}),
  dark:      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:20,subdomains:'abcd',attribution:''}),
  satellite: L.tileLayer('https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',{maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:''}),
  terrain:   L.tileLayer('https://{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}',{maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:''})
};
let _activeTileKey = 'dark';
function switchLayer(key) {
  Object.values(layers).forEach(l => { try { map.removeLayer(l); } catch(e){} });
  if(layers[key]) layers[key].addTo(map);
  _activeTileKey = key;
  // Sync radio buttons
  document.querySelectorAll('input[name="layer"]').forEach(r => r.checked = (r.value === key));
}
// Démarrer sur Dark, fallback OSM si inaccessible
layers.dark.addTo(map);
let _darkFallbackDone = false;
layers.dark.on('tileerror', function(){
  if(_darkFallbackDone) return;
  _darkFallbackDone = true;
  console.warn('Dark tiles indisponibles, fallback OSM');
  map.removeLayer(layers.dark);
  layers.osm.addTo(map);
  _activeTileKey = 'osm';
  document.getElementById('lDark').checked = false;
  document.getElementById('lOsm').checked  = true;
});
map.attributionControl.setPrefix('');

// DMZ — 38ème parallèle Corée (coordonnées corrigées)
const _dmzLine = L.polyline([
  [38.31,125.10],[38.27,125.40],[38.25,125.68],[38.27,126.00],
  [38.25,126.35],[38.18,126.65],[38.12,126.95],[38.05,127.18],
  [38.00,127.45],[37.97,127.75],[38.00,128.02],[38.10,128.30],
  [38.20,128.55],[38.35,128.75],[38.45,129.00],[38.55,129.20]],
  {color:'#dc2626',weight:2,opacity:.7,dashArray:'10 5'}).addTo(map);
document.getElementById('chkDMZ').addEventListener('change',function(){
  this.checked ? _dmzLine.addTo(map) : map.removeLayer(_dmzLine);
});

const COLORS=['#ef4444','#f97316','#f59e0b','#eab308','#10b981','#4ade80','#3b82f6','#8b5cf6','#ec4899','#ffffff','#94a3b8','#1e293b'];
let activeColor='#3b82f6';
let rulerActive=false,arrowActive=false;
let drawMarkers=[],missionMarkers=[],aircraftMarker=null;
let pptCircles=[],airportMarkers=[];

function makeAircraftIcon(hdg,alt,kias){
  const hdgStr=String(Math.round(hdg)).padStart(3,'0')+'°';
  const altFL=alt!=null?'FL'+String(Math.round(Math.abs(alt)/100)).padStart(3,'0'):'';
  const spdStr=kias!=null&&kias>5?String(Math.round(kias))+'kt':'';
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="34" height="34" viewBox="0 0 34 34">
    <g transform="rotate(${hdg},17,17)">
      <polygon points="17,3 25,30 17,24 9,30"
        fill="#3b82f6" fill-opacity="0.95"
        stroke="#0c1a2e" stroke-width="1.5" stroke-linejoin="round"/>
      <line x1="17" y1="24" x2="17" y2="30" stroke="#93c5fd" stroke-width="1" opacity=".5"/>
    </g>
  </svg>`;
  const parts=[
    `<span style="color:#60a5fa;font-weight:700">${hdgStr}</span>`,
    altFL?`<span style="color:#bfdbfe">${altFL}</span>`:'',
    spdStr?`<span style="color:#93c5fd">${spdStr}</span>`:'',
  ].filter(Boolean).join('<span style="color:#1e3a5f;margin:0 3px">·</span>');
  const label=`<div style="
    position:absolute;left:50%;transform:translateX(-50%);top:36px;
    white-space:nowrap;background:rgba(3,8,20,.92);
    border:1px solid rgba(59,130,246,.5);border-radius:2px;
    padding:2px 8px;font-family:system-ui,sans-serif;font-weight:700;
    font-size:13px;pointer-events:none;letter-spacing:.5px;
    box-shadow:0 2px 10px rgba(0,0,0,.7),0 0 12px rgba(59,130,246,.12);
  ">${parts}</div>`;
  return L.divIcon({html:`<div style="position:relative;width:34px;height:34px">${svg}${label}</div>`,className:'',iconSize:[34,34],iconAnchor:[17,17]});
}

let followAircraft = true;
document.getElementById('followBtn').addEventListener('click', function() {
  followAircraft = !followAircraft;
  this.classList.toggle('active', followAircraft);
  this.title = followAircraft ? "Centrer sur l'avion (actif)" : "Centrer sur l'avion (désactivé)";
  if (followAircraft && aircraftMarker) {
    map.setView(aircraftMarker.getLatLng(), map.getZoom());
  }
});
map.on('dragstart', () => {
  if (followAircraft) {
    followAircraft = false;
    const btn = document.getElementById('followBtn');
    btn.classList.remove('active');
    btn.title = "Centrer sur l'avion (désactivé)";
  }
});

// ── Bullseye ─────────────────────────────────────────────────────
let _bullMarker = null;
let _bullLat = null, _bullLon = null;

function _bullIcon() {
  const col = '#f97316'; // orange distinct
  return L.divIcon({
    html: `<svg width="28" height="28" viewBox="0 0 28 28" style="overflow:visible">
      <circle cx="14" cy="14" r="11" fill="none" stroke="${col}" stroke-width="1.8" opacity=".85"/>
      <circle cx="14" cy="14" r="6"  fill="none" stroke="${col}" stroke-width="1.4" opacity=".7"/>
      <circle cx="14" cy="14" r="2"  fill="${col}" opacity=".9"/>
      <line x1="14" y1="0"  x2="14" y2="7"  stroke="${col}" stroke-width="1.4" opacity=".7"/>
      <line x1="14" y1="21" x2="14" y2="28" stroke="${col}" stroke-width="1.4" opacity=".7"/>
      <line x1="0"  y1="14" x2="7"  y2="14" stroke="${col}" stroke-width="1.4" opacity=".7"/>
      <line x1="21" y1="14" x2="28" y2="14" stroke="${col}" stroke-width="1.4" opacity=".7"/>
      <text x="14" y="-4" text-anchor="middle"
        style="font-family:'Consolas','Courier New',monospace;font-size:9px;fill:${col};letter-spacing:1px;font-weight:700">BULL</text>
    </svg>`,
    className:'', iconSize:[28,28], iconAnchor:[14,14]
  });
}

function updateBullseye(lat, lon) {
  if (lat == null || lon == null) return;
  _bullLat = lat; _bullLon = lon;
  if (_bullMarker) {
    _bullMarker.setLatLng([lat, lon]);
  } else {
    _bullMarker = L.marker([lat, lon], {
      icon: _bullIcon(), zIndexOffset: 500, interactive: false
    }).addTo(map);
  }
  // Mettre à jour le champ BULL dans le panel GPS
  const el = document.getElementById('gps-bull');
  if (el && _lastAircraftData) {
    const brg = bearingTo(_lastAircraftData.lat, _lastAircraftData.lon, lat, lon);
    const nm  = haversineNm(_lastAircraftData.lat, _lastAircraftData.lon, lat, lon);
    el.textContent = String(Math.round(brg)).padStart(3,'0') + '° / ' + nm.toFixed(1) + ' NM';
  }
}

function updateAircraft(d){
  if(!d||d.lat===undefined||d.lon===undefined)return;
  if(d.lat===0&&d.lon===0)return;
  const icon=makeAircraftIcon(d.heading||0,d.altitude,d.kias);
  if(aircraftMarker){aircraftMarker.setLatLng([d.lat,d.lon]);aircraftMarker.setIcon(icon);}
  else{aircraftMarker=L.marker([d.lat,d.lon],{icon,zIndexOffset:1000}).addTo(map);}
  if(followAircraft){
    const now=Date.now();
    if(!updateAircraft._lastPan||now-updateAircraft._lastPan>500){
      map.panTo([d.lat,d.lon],{animate:true,duration:0.4});
      updateAircraft._lastPan=now;
    }
  }
  // Bullseye
  if (d.bull_lat != null && d.bull_lon != null) {
    updateBullseye(d.bull_lat, d.bull_lon);
  }
}

let rStart=null,rLine=null,rLabel=null,rDot=null;

function updateRuler(to){
  if(!rStart)return;
  if(rLine)map.removeLayer(rLine);
  if(rLabel)map.removeLayer(rLabel);
  rLine=L.polyline([rStart,to],{color:activeColor,weight:2,opacity:.8,dashArray:'8 4'}).addTo(map);
  const dist=map.distance(rStart,to);
  const nm=dist/1852,km=dist/1000;
  const φ1=rStart.lat*Math.PI/180,φ2=to.lat*Math.PI/180;
  const dλ=(to.lng-rStart.lng)*Math.PI/180;
  const y=Math.sin(dλ)*Math.cos(φ2);
  const x=Math.cos(φ1)*Math.sin(φ2)-Math.sin(φ1)*Math.cos(φ2)*Math.cos(dλ);
  const hdg=((Math.atan2(y,x)*180/Math.PI)+360)%360;
  const mid=L.latLng((rStart.lat+to.lat)/2,(rStart.lng+to.lng)/2);
  rLabel=L.marker(mid,{icon:L.divIcon({
    className:'',iconSize:[130,60],iconAnchor:[65,30],
    html:`<div class="ruler-label">
      <div class="ruler-hdg">${String(Math.round(hdg)).padStart(3,'0')}° / ${String(Math.round((hdg+180)%360)).padStart(3,'0')}°</div>
      <div class="ruler-nm" style="color:${activeColor}">${nm.toFixed(1)} NM</div>
      <div class="ruler-km">${km.toFixed(2)} km</div>
    </div>`
  })}).addTo(map);
}
function clearRuler(){[rLine,rLabel,rDot].forEach(l=>{if(l)map.removeLayer(l)});rLine=rLabel=rDot=rStart=null;}
document.getElementById('rulerBtn').addEventListener('click',function(){
  rulerActive=!rulerActive;arrowActive=false;
  this.classList.toggle('active',rulerActive);
  document.getElementById('arrowBtn').classList.remove('active');
  if(!rulerActive)clearRuler();
  map.getContainer().style.cursor=rulerActive?'crosshair':'';
});
map.on('click',e=>{
  if(!rulerActive||arrowActive)return;
  if(!rStart){rStart=e.latlng;rDot=L.circleMarker(rStart,{radius:4,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);}
  else{clearRuler();}
});
map.on('mousemove',e=>{if(rulerActive&&rStart)updateRuler(e.latlng);});

let aStart=null,aLine=null,aHead=null,aDot=null;

function arrowHeadPts(from,to,zoom){
  const fp = map.latLngToLayerPoint(from);
  const tp = map.latLngToLayerPoint(to);
  const ang = Math.atan2(tp.y-fp.y, tp.x-fp.x);
  const A = Math.PI/5.5;
  const L2 = Math.max(14, Math.min(32, map.distance(from,to)/60));  // px, proportionnel dist
  const sz = L2 / Math.pow(2, zoom-7) * 0.00015;  // retour en degrés approx
  const cosLat = Math.cos(to.lat*Math.PI/180);
  return [
    L.latLng(to.lat - sz*Math.cos(ang-A),          to.lng - sz*Math.sin(ang-A)/cosLat),
    L.latLng(to.lat - sz*Math.cos(ang+A),          to.lng - sz*Math.sin(ang+A)/cosLat)
  ];
}

function updateArrow(to){
  if(!aStart)return;
  if(aLine)map.removeLayer(aLine);
  if(aHead)map.removeLayer(aHead);
  aLine=L.polyline([aStart,to],{color:activeColor,weight:2.5,opacity:.85}).addTo(map);
  const [p1,p2]=arrowHeadPts(aStart,to,map.getZoom());
  aHead=L.polygon([to,p1,p2],{color:activeColor,fillColor:activeColor,fillOpacity:.9,weight:1.5}).addTo(map);
}
function clearArrow(){[aLine,aHead,aDot].forEach(l=>{if(l)map.removeLayer(l)});aLine=aHead=aDot=aStart=null;}

document.getElementById('arrowBtn').addEventListener('click',function(){
  arrowActive=!arrowActive;rulerActive=false;
  this.classList.toggle('active',arrowActive);
  document.getElementById('rulerBtn').classList.remove('active');
  if(!arrowActive)clearArrow();
  map.getContainer().style.cursor=arrowActive?'crosshair':'';
});
map.on('click',e=>{
  if(!arrowActive||rulerActive)return;
  if(!aStart){
    aStart=e.latlng;
    aDot=L.circleMarker(aStart,{radius:4,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);
  } else {
    const fLine=L.polyline([aStart,e.latlng],{color:activeColor,weight:2.5,opacity:.9}).addTo(map);
    drawMarkers.push(fLine);
    const [p1,p2]=arrowHeadPts(aStart,e.latlng,map.getZoom());
    const fHead=L.polygon([e.latlng,p1,p2],{color:activeColor,fillColor:activeColor,fillOpacity:1,weight:1.5}).addTo(map);
    drawMarkers.push(fHead);
    const dist=map.distance(aStart,e.latlng)/1852;
    if(dist>0.05){
      const mid=L.latLng((aStart.lat+e.latlng.lat)/2,(aStart.lng+e.latlng.lng)/2);
      const lm=L.marker(mid,{icon:L.divIcon({html:`<div class="arrow-label" style="color:${activeColor}">${dist.toFixed(1)} NM</div>`,className:'',iconSize:[70,20],iconAnchor:[35,20]})}).addTo(map);
      drawMarkers.push(lm);
    }
    clearArrow();
  }
});
map.on('mousemove',e=>{if(arrowActive&&aStart)updateArrow(e.latlng);});

document.getElementById('clearArrowsBtn').addEventListener('click',()=>{
  drawMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});drawMarkers=[];clearArrow();
});

let _noteCount=0;
function createNote(){
  let bgColor='#0f172a',textColor='#94a3b8';
  const wrapper=document.createElement('div');
  wrapper.className='note-wrapper';
  const _no=_noteCount%8;_noteCount++;
  wrapper.style.left=(300+_no*28)+'px';wrapper.style.top=(200+_no*28)+'px';
  wrapper.style.background=bgColor;wrapper.style.border='1px solid rgba(74,222,128,.2)';
  const header=document.createElement('div');header.className='note-header';
  const bgPicker=document.createElement('div');bgPicker.className='note-mini-picker';bgPicker.title='Fond';
  const bgSwatch=document.createElement('div');bgSwatch.className='swatch';bgSwatch.style.background=bgColor;
  const bgInput=document.createElement('input');bgInput.type='color';bgInput.value='#0f172a';
  bgInput.addEventListener('input',()=>{bgColor=bgInput.value;bgSwatch.style.background=bgColor;wrapper.style.background=bgColor;});
  bgPicker.appendChild(bgSwatch);bgPicker.appendChild(bgInput);
  const txPicker=document.createElement('div');txPicker.className='note-mini-picker';txPicker.title='Texte';
  const txSwatch=document.createElement('div');txSwatch.className='swatch';txSwatch.style.background=textColor;
  const txInput=document.createElement('input');txInput.type='color';txInput.value='#94a3b8';
  txInput.addEventListener('input',()=>{textColor=txInput.value;txSwatch.style.background=textColor;body.style.color=textColor;});
  txPicker.appendChild(txSwatch);txPicker.appendChild(txInput);
  const txLabel=document.createElement('span');txLabel.textContent='T';txLabel.style.cssText='font-size:9px;color:rgba(255,255,255,.3);margin-right:1px;font-family:system-ui,sans-serif';
  const colors=document.createElement('div');colors.className='note-header-colors';
  colors.appendChild(bgPicker);colors.appendChild(txLabel);colors.appendChild(txPicker);
  const closeBtn=document.createElement('button');closeBtn.className='note-close';closeBtn.innerHTML='×';closeBtn.title='Supprimer';
  closeBtn.addEventListener('click',()=>wrapper.remove());
  header.appendChild(colors);header.appendChild(closeBtn);
  const body=document.createElement('textarea');body.className='note-body';
  body.placeholder='Note…';body.style.color=textColor;
  wrapper.appendChild(header);wrapper.appendChild(body);
  let drag=false,ox=0,oy=0;
  header.addEventListener('mousedown',e=>{if(e.target===closeBtn||e.target===bgInput||e.target===txInput)return;drag=true;ox=e.clientX-wrapper.offsetLeft;oy=e.clientY-wrapper.offsetTop;e.preventDefault();});
  document.addEventListener('mousemove',e=>{if(drag){wrapper.style.left=(e.clientX-ox)+'px';wrapper.style.top=(e.clientY-oy)+'px';}});
  document.addEventListener('mouseup',()=>{drag=false;});
  document.body.appendChild(wrapper);body.focus();
}
document.getElementById('annotationBtn').addEventListener('click',createNote);

const cGrid=document.getElementById('cGrid');
COLORS.forEach(c=>{
  const s=document.createElement('div');
  s.className='c-swatch'+(c===activeColor?' sel':'');
  s.style.background=c;
  s.onclick=()=>{activeColor=c;document.querySelectorAll('.c-swatch').forEach(x=>x.classList.remove('sel'));s.classList.add('sel');};
  cGrid.appendChild(s);
});
document.getElementById('colorBtn').addEventListener('click',()=>document.getElementById('colorPanel').classList.toggle('open'));

document.getElementById('layerBtn').addEventListener('click',()=>document.getElementById('layerPanel').classList.toggle('open'));
document.querySelectorAll('input[name="layer"]').forEach(r=>r.addEventListener('change',e=>{
  switchLayer(e.target.value);
}));

document.getElementById('pptBtn').addEventListener('click',function(){
  const v=this.classList.toggle('active');
  pptCircles.forEach(c=>v?c.addTo(map):map.removeLayer(c));
  const chk=document.getElementById('chkPPT');if(chk)chk.checked=v;
});
// chkPPT: géré uniquement via le bouton toolbar pptBtn

document.getElementById('airportBtn').addEventListener('click',function(){
  const v=this.classList.toggle('active');
  airportMarkers.forEach(m=>v?m.addTo(map):map.removeLayer(m));
  const chk=document.getElementById('chkAirports');if(chk)chk.checked=v;
  runwaysVisible=v;
  runwayLayers.forEach(l=>{try{v?l.addTo(map):map.removeLayer(l);}catch(e){}});
  const chkR=document.getElementById('chkRunways');if(chkR)chkR.checked=v;
});
// chkAirports: géré uniquement via le bouton toolbar airportBtn

document.getElementById('uploadBtn').addEventListener('click',()=>document.getElementById('fileInput').click());
document.getElementById('fileInput').addEventListener('change',async e=>{
  const file=e.target.files[0];if(!file)return;
  const fd=new FormData();fd.append('file',file);
  const r=await fetch('/api/upload',{method:'POST',body:fd});
  if(r.ok)loadMission();
});

let _lastIniFile=null;
setInterval(async()=>{
  try{
    const s=await(await fetch('/api/ini/status')).json();
    if(s.loaded&&s.file!==_lastIniFile){
      _lastIniFile=s.file;loadMission();
      const n=document.createElement('div');n.className='bms-toast';
      n.textContent='✦ MISSION CHARGÉE — '+s.file;
      document.body.appendChild(n);setTimeout(()=>n.remove(),3000);
    }
  }catch(e){}
},5000);

function loadMission(){
  missionMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});missionMarkers=[];
  pptCircles.forEach(p=>{try{map.removeLayer(p)}catch(e){}});pptCircles=[];
  fetch('/api/mission').then(r=>r.json()).then(d=>{
    if(d.flightplan?.length){
      const c='#f59e0b';
      missionMarkers.push(L.polyline(d.flightplan.map(p=>[p.lat,p.lon]),{color:c,weight:2,opacity:.8}).addTo(map));
      d.flightplan.forEach((p,i)=>{
        missionMarkers.push(L.circleMarker([p.lat,p.lon],{radius:4,color:c,fillColor:c,fillOpacity:.85,weight:2}).addTo(map));
        missionMarkers.push(L.marker([p.lat,p.lon],{icon:L.divIcon({
          html:`<div style="font-family:'Consolas','Courier New',monospace;color:${c};font-size:9px;font-weight:700;text-shadow:0 1px 4px #000">${i+1}</div>`,
          className:'',iconSize:[16,12],iconAnchor:[-5,6]
        })}).addTo(map));
      });
    }
    if(d.route?.length){
      const c='#e2e8f0';
      for(let i=0;i<d.route.length-1;i++)
        missionMarkers.push(L.polyline([[d.route[i].lat,d.route[i].lon],[d.route[i+1].lat,d.route[i+1].lon]],{color:c,weight:2}).addTo(map));
      d.route.forEach((p,i)=>{
        missionMarkers.push(L.circleMarker([p.lat,p.lon],{radius:5,color:c,fillColor:c,fillOpacity:.9,weight:2}).addTo(map));
        missionMarkers.push(L.marker([p.lat,p.lon],{icon:L.divIcon({
          html:`<div style="font-family:'Consolas','Courier New',monospace;color:#e2e8f0;font-size:9px;font-weight:700;text-shadow:0 1px 4px #000">${i+1}</div>`,
          className:'',iconSize:[16,12],iconAnchor:[-5,6]
        })}).addTo(map));
      });
      map.setView([d.route[0].lat,d.route[0].lon],9);
    }
    if(d.threats?.length){
      const c='#ef4444';
      d.threats.forEach(t=>{
        const circ=L.circle([t.lat,t.lon],{radius:(t.range_m||t.range_nm*1852),color:c,fillColor:c,fillOpacity:.05,weight:1.2,dashArray:'5 4'});
        if(document.getElementById('pptBtn')?.classList.contains('active'))circ.addTo(map);
        pptCircles.push(circ);
        missionMarkers.push(L.circleMarker([t.lat,t.lon],{radius:5,color:'#fff',fillColor:c,fillOpacity:1,weight:2}).addTo(map));
        const nm=t.name?t.name.trim():'';
        const rng=t.range_nm>0?t.range_nm+'NM':'';
        const pptNum=(t.num!==undefined)?t.num:t.index;
        const parts2=[
          `<span style="color:#f87171;font-size:9px;letter-spacing:1px;font-weight:700">PPT\u00a0${pptNum}</span>`,
          nm?`<span style="color:#fca5a5;font-size:10px;font-weight:700;letter-spacing:.3px">${nm}</span>`:'',
          rng?`<span style="color:#ef4444;font-size:9px;font-family:'Consolas','Courier New',monospace">${rng}</span>`:'',
        ].filter(Boolean).join('<span style="color:rgba(239,68,68,.25);margin:0 3px;font-size:7px">▸</span>');
        missionMarkers.push(L.marker([t.lat,t.lon],{icon:L.divIcon({
          html:`<div style="background:rgba(8,2,2,.9);border:1px solid rgba(239,68,68,.22);border-left:2px solid rgba(239,68,68,.65);border-radius:2px;padding:2px 7px;white-space:nowrap;pointer-events:none;font-family:system-ui,sans-serif;display:inline-flex;align-items:center;gap:0;box-shadow:0 2px 8px rgba(0,0,0,.5)">${parts2}</div>`,
          className:'',iconSize:[110,16],iconAnchor:[-6,8]
        }),zIndexOffset:50}).addTo(map));
      });
    }
  });
}

let apData = [];        // cache des données
let apNameMarkers = []; // markers "nom complet" séparés
let apLabelMarkers= []; // markers TACAN/ICAO
let apIconMarkers = []; // markers losange

function buildApPopup(ap) {
  const isNK = ap.icao.startsWith('KP-') || ap.icao.startsWith('ZK');
  const col  = isNK ? '#f87171' : '#60a5fa';

  // Ligne 1 : ICAO · TACAN · TOUR
  const parts = [`<span class="ap-l1-icao" style="color:${col}">${ap.icao}</span>`];
  if (ap.tacan) {
    parts.push(`<span class="ap-l1-dot">·</span>`);
    parts.push(`<span class="ap-l1-tacan">${ap.tacan}</span>`);
  }
  if (ap.freq) {
    parts.push(`<span class="ap-l1-dot">·</span>`);
    parts.push(`<span class="ap-l1-freq">${ap.freq}</span>`);
  }
  const line1 = `<div class="ap-l1">${parts.join('')}</div>`;

  // Ligne 2 : chips ILS (RWY · freq · CRS)
  let line2 = '';
  if (ap.ils && ap.ils.length) {
    const chips = ap.ils.map(i =>
      `<div class="ap-ils-chip">
        <span class="ap-ils-rwy">RWY ${i.rwy}</span>
        <span class="ap-ils-freq">${i.freq}</span>
        <span class="ap-ils-crs">${i.crs}°</span>
      </div>`
    ).join('');
    line2 = `<div class="ap-l2">${chips}</div>`;
  }

  return `<div class="ap-popup">${line1}${line2}</div>`;
}

fetch('/api/airports').then(r=>r.json()).then(aps=>{
  apData = aps;
  aps.forEach(ap=>{
    const isNK=ap.icao.startsWith('KP-')||ap.icao.startsWith('ZK');
    const col=isNK?'rgba(248,113,113,.85)':'rgba(96,165,250,.85)';
    const sz = 13;
    const sym=`<svg width="${sz}" height="${sz}" viewBox="0 0 13 13" style="cursor:pointer">
      <polygon points="6.5,1 12,6.5 6.5,12 1,6.5" fill="${col}" stroke="rgba(0,0,0,.7)" stroke-width="1.5"/>
    </svg>`;
    const mIcon=L.marker([ap.lat,ap.lon],{
      icon:L.divIcon({html:sym,className:'',iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]}),
      zIndexOffset:10
    }).addTo(map);
    mIcon.bindPopup(buildApPopup(ap),{
      className:'',maxWidth:320,closeButton:true,
      offset:L.point(0,-6)
    });
    apIconMarkers.push(mIcon);

    const apIcao = ap.icao.startsWith('KP-') ? ap.name : ap.icao;
    const labelHtml = `<div style="pointer-events:none;line-height:1.2">
      <div style="font-family:'Consolas','Courier New',monospace;font-size:11px;font-weight:700;
        color:${col};letter-spacing:.8px;text-shadow:0 1px 4px #000,0 0 8px rgba(0,0,0,.9);
        white-space:nowrap">${apIcao}</div>
    </div>`;
    const mLabel=L.marker([ap.lat,ap.lon],{
      icon:L.divIcon({html:labelHtml,className:'',iconSize:[160,26],iconAnchor:[-8,6]}),
      zIndexOffset:-100,interactive:true
    }).addTo(map);
    mLabel.on('click',e=>{
      if(rulerActive){
        L.DomEvent.stopPropagation(e);
        if(!rStart){
          rStart=L.latLng(ap.lat,ap.lon);
          rDot=L.circleMarker(rStart,{radius:4,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);
        } else { clearRuler(); }
      } else { mIcon.openPopup(); }
    });
    mIcon.on('click',e=>{
      if(rulerActive){
        L.DomEvent.stopPropagation(e);
        if(!rStart){
          rStart=L.latLng(ap.lat,ap.lon);
          rDot=L.circleMarker(rStart,{radius:4,color:'#fff',fillColor:activeColor,fillOpacity:1,weight:2}).addTo(map);
        } else { clearRuler(); }
      } else { mIcon.openPopup(); }
    });
    apLabelMarkers.push(mLabel);
    airportMarkers.push(mIcon,mLabel);
    apNameMarkers.push(mLabel);
  });

  document.getElementById('chkRunways').addEventListener('change',function(){
    runwaysVisible=this.checked;
    runwayLayers.forEach(l=>{try{runwaysVisible?l.addTo(map):map.removeLayer(l);}catch(e){}});
  });

  // chkApName — afficher/masquer les labels ICAO des aéroports
  document.getElementById('chkApName').addEventListener('change',function(){
    apLabelMarkers.forEach(m=>{
      try{ this.checked ? m.addTo(map) : map.removeLayer(m); }catch(e){}
    });
  });
  // Etat initial : labels visibles si coché
  if(!document.getElementById('chkApName').checked){
    apLabelMarkers.forEach(m=>{try{map.removeLayer(m);}catch(e){}});
  }
});

const RUNWAY_DATA = [
  {icao:'RKTN',name:'Daegu AB',rwy:0,hdg:327.5,len:2743,c:[[35.883663,128.667015],[35.883885,128.66744],[35.904457,128.650634],[35.904229,128.650212]]},
  {icao:'RKTN',name:'Daegu AB',rwy:1,hdg:327.5,len:2754,c:[[35.882936,128.66592],[35.883162,128.666342],[35.903814,128.64947],[35.903585,128.649048]]},
  {icao:'RKJB',name:'Muan Apt',rwy:0,hdg:90.8,len:2794,c:[[34.988282,126.355991],[34.987878,126.355991],[34.987922,126.38666],[34.988327,126.386664]]},
  {icao:'RKSO',name:'Osan AB',rwy:0,hdg:186.6,len:2745,c:[[37.107717,127.046449],[37.107756,127.045939],[37.083195,127.042867],[37.08316,127.043375]]},
  {icao:'RKSO',name:'Osan AB',rwy:1,hdg:186.6,len:2745,c:[[37.107918,127.04392],[37.107955,127.043411],[37.083402,127.040337],[37.083361,127.040848]]},
  {icao:'RKTY',name:'Yecheon AB',rwy:0,hdg:182.6,len:2746,c:[[36.655298,128.355143],[36.655313,128.354636],[36.630626,128.353722],[36.630617,128.354233]]},
  {icao:'ZKTS',name:'Toksan AB',rwy:0,hdg:52.1,len:2484,c:[[39.27708,127.346012],[39.276736,127.34637],[39.290795,127.3688],[39.291138,127.368442]]},
  {icao:'RKPS',name:'Sacheon AB',rwy:0,hdg:215.6,len:2750,c:[[35.100714,128.087058],[35.100941,128.086671],[35.080615,128.069441],[35.080387,128.069827]]},
  {icao:'RKPS',name:'Sacheon AB',rwy:1,hdg:215.7,len:2751,c:[[35.102998,128.085936],[35.10322,128.085545],[35.082896,128.068315],[35.082675,128.068707]]},
  {icao:'ZKUJ',name:'Uiju AB',rwy:0,hdg:49.0,len:2493,c:[[40.040129,124.517393],[40.039743,124.517854],[40.054846,124.539484],[40.055233,124.539023]]},
  {icao:'RKSM',name:'Seoul AB',rwy:0,hdg:82.8,len:2957,c:[[37.446373,127.093555],[37.445966,127.093628],[37.449713,127.126783],[37.45012,127.12671]]},
  {icao:'RKSM',name:'Seoul AB',rwy:1,hdg:89.2,len:2744,c:[[37.449879,127.095767],[37.449469,127.095784],[37.450244,127.126841],[37.450655,127.126825]]},
  {icao:'RKTI',name:'Jungwon AB',rwy:0,hdg:275.6,len:2750,c:[[36.634671,127.516339],[36.635081,127.51638],[36.637084,127.485666],[36.636674,127.485625]]},
  {icao:'RKTI',name:'Jungwon AB',rwy:1,hdg:275.4,len:2852,c:[[36.632599,127.516742],[36.632916,127.516774],[36.634993,127.484914],[36.634675,127.484881]]},
  {icao:'RJOI',name:'Iwakuni AB',rwy:0,hdg:265.0,len:2441,c:[[34.15313,132.248972],[34.153664,132.248894],[34.151218,132.222548],[34.150685,132.22262]]},
  {icao:'RKPK',name:'Gimhae Apt',rwy:0,hdg:277.7,len:2749,c:[[35.182237,128.951059],[35.182636,128.951114],[35.185564,128.921087],[35.185165,128.921027]]},
  {icao:'RKPK',name:'Gimhae Apt',rwy:1,hdg:277.9,len:3206,c:[[35.180288,128.950746],[35.180819,128.950825],[35.184232,128.915799],[35.183701,128.915723]]},
  {icao:'RKJJ',name:'Gwangju AB',rwy:0,hdg:240.6,len:2835,c:[[35.134226,126.816195],[35.134576,126.815945],[35.121713,126.789037],[35.121362,126.789277]]},
  {icao:'RKJJ',name:'Gwangju AB',rwy:1,hdg:240.6,len:2835,c:[[35.135725,126.815124],[35.136075,126.814874],[35.123212,126.78796],[35.122862,126.78821]]},
  {icao:'KP-0005',name:'Taetan AB (G)',rwy:0,hdg:357.4,len:2503,c:[[38.238811,126.650634],[38.238835,126.651157],[38.261302,126.649337],[38.261276,126.648815]]},
  {icao:'KP-0030',name:'Panghyon AB',rwy:0,hdg:147.6,len:2597,c:[[39.910465,124.924693],[39.910198,124.924173],[39.890739,124.940999],[39.891009,124.941506]]},
  {icao:'RJOW',name:'Iwami Apt',rwy:0,hdg:168.6,len:2001,c:[[34.684957,131.787578],[34.684868,131.787097],[34.667321,131.791906],[34.66741,131.792387]]},
  {icao:'RKNY',name:'Yangyang Apt',rwy:0,hdg:310.8,len:2500,c:[[38.055058,128.676352],[38.05537,128.67668],[38.069756,128.654739],[38.069444,128.65441]]},
  {icao:'RKSI',name:'Incheon Apt *',rwy:0,hdg:305.8,len:3750,c:[[37.460193,126.463405],[37.460637,126.463789],[37.479929,126.428947],[37.479487,126.428556]]},
  {icao:'RKSI',name:'Incheon Apt *',rwy:1,hdg:305.8,len:3751,c:[[37.457142,126.460724],[37.457584,126.461112],[37.476881,126.426262],[37.476438,126.425875]]},
  {icao:'KP-0023',name:'Onchon AB',rwy:0,hdg:83.7,len:2502,c:[[39.815001,124.919894],[39.815409,124.919843],[39.817488,124.949006],[39.817083,124.949046]]},
  {icao:'RJOA',name:'Hiroshima Apt',rwy:0,hdg:1.2,len:3000,c:[[34.432547,132.910191],[34.432548,132.910845],[34.459516,132.910858],[34.459517,132.910204]]},
  {icao:'KP-0008',name:'Sondok AB',rwy:0,hdg:263.4,len:2502,c:[[39.750682,127.48869],[39.751087,127.488621],[39.748112,127.459616],[39.747707,127.459685]]},
  {icao:'RKSS',name:'Gimpo Apt',rwy:0,hdg:315.6,len:3573,c:[[37.545249,126.811295],[37.545627,126.811769],[37.568189,126.782909],[37.567809,126.782435]]},
  {icao:'RKSS',name:'Gimpo Apt',rwy:1,hdg:315.7,len:3172,c:[[37.542991,126.808384],[37.543371,126.808858],[37.563396,126.783243],[37.563015,126.782768]]},
  {icao:'KP-0020',name:'Hwangju AB',rwy:0,hdg:152.5,len:2504,c:[[38.682744,125.777293],[38.682925,125.77776],[38.662777,125.790628],[38.662601,125.790156]]},
  {icao:'RKSW',name:'Suwon AB',rwy:0,hdg:306.3,len:2743,c:[[37.22823,127.028906],[37.228566,127.029207],[37.242818,127.003916],[37.242484,127.00362]]},
  {icao:'RKSW',name:'Suwon AB',rwy:1,hdg:306.3,len:2743,c:[[37.227119,127.027862],[37.227454,127.028163],[37.241708,127.002872],[37.241373,127.002572]]},
  {icao:'KP-0011',name:'Mirim Airport',rwy:0,hdg:5.5,len:1251,c:[[39.06162,125.599413],[39.061595,125.59994],[39.072823,125.600799],[39.072847,125.600273]]},
  {icao:'RKJK',name:'Gunsan AB',rwy:0,hdg:101.3,len:2749,c:[[35.90714,126.599591],[35.906742,126.599495],[35.902279,126.629517],[35.902678,126.629607]]},
  {icao:'RKNN',name:'Gangneung AB',rwy:0,hdg:203.3,len:2761,c:[[37.765804,128.949017],[37.765963,128.948534],[37.743008,128.93657],[37.742853,128.937048]]},
  {icao:'RKNW',name:'Wonju AB',rwy:0,hdg:64.6,len:2738,c:[[37.427754,127.941412],[37.427386,127.941644],[37.438331,127.969412],[37.438699,127.969181]]},
  {icao:'RKSG',name:'Pyeongtaek AB',rwy:0,hdg:319.2,len:2309,c:[[36.952564,127.038492],[36.952839,127.038876],[36.968295,127.021521],[36.968019,127.021136]]},
  {icao:'RKTH',name:'Pohang AB',rwy:0,hdg:183.2,len:2133,c:[[35.997509,129.423488],[35.997524,129.422978],[35.978354,129.422152],[35.978339,129.42266]]},
  {icao:'RKTP',name:'Seosan AB',rwy:0,hdg:245.6,len:2744,c:[[36.706605,126.49829],[36.706977,126.49807],[36.696412,126.470264],[36.69604,126.470483]]},
  {icao:'RKTP',name:'Seosan AB',rwy:1,hdg:245.6,len:2744,c:[[36.708337,126.49727],[36.708708,126.497051],[36.698143,126.469244],[36.697771,126.469464]]},
  {icao:'RKTU',name:'Cheongju Apt',rwy:0,hdg:218.9,len:2744,c:[[36.732248,127.513095],[36.732577,127.512563],[36.713041,127.493765],[36.712711,127.494298]]},
  {icao:'RKTU',name:'Cheongju Apt',rwy:1,hdg:218.6,len:2744,c:[[36.732914,127.510383],[36.733161,127.509982],[36.713625,127.491185],[36.713378,127.491585]]},
  {icao:'KP-0035',name:'Hwangsuwon AB',rwy:0,hdg:325.0,len:2901,c:[[38.672715,125.376188],[38.672957,125.376617],[38.694085,125.357024],[38.693842,125.356594]]},
  {icao:'KP-0019',name:'Hyon-ni AB',rwy:0,hdg:79.4,len:2702,c:[[39.147695,125.867532],[39.147337,125.867634],[39.152173,125.898328],[39.152534,125.898236]]},
  {icao:'KP-0059',name:'Iwon AB',rwy:0,hdg:171.2,len:2509,c:[[40.327783,128.631085],[40.327712,128.630548],[40.305483,128.635634],[40.305556,128.636167]]},
  {icao:'KP-0018',name:'Kaechon AB',rwy:0,hdg:46.3,len:2503,c:[[39.79407,125.893871],[39.79378,125.894246],[39.809632,125.915044],[39.809923,125.914672]]},
  {icao:'KP-0015',name:'Koksan AB',rwy:0,hdg:32.3,len:2503,c:[[38.807253,126.392391],[38.807041,126.392836],[38.826276,126.407847],[38.826488,126.407401]]},
  {icao:'KP-0039',name:'Kwail AB',rwy:0,hdg:125.4,len:2499,c:[[38.70657,125.538208],[38.706245,125.53793],[38.69355,125.561675],[38.693864,125.561955]]},
  {icao:'KP-0053',name:'Manpo AB',rwy:0,hdg:72.4,len:1117,c:[[41.563091,126.252673],[41.562834,126.252808],[41.566123,126.265472],[41.566374,126.265345]]},
  {icao:'KP-0032',name:'Orang AB',rwy:0,hdg:58.8,len:2515,c:[[41.377494,129.437117],[41.377032,129.437509],[41.3892,129.462916],[41.389662,129.462523]]},
  {icao:'KP-0029',name:'Samjiyon AB',rwy:0,hdg:31.6,len:3308,c:[[42.053663,128.389224],[42.053384,128.389858],[42.079001,128.410225],[42.079278,128.40959]]},
  {icao:'KP-0021',name:'Sunchon AB',rwy:0,hdg:125.3,len:2504,c:[[39.440112,125.92096],[39.439773,125.920663],[39.427087,125.94474],[39.427426,125.945037]]},
  {icao:'KP-0006',name:'Taechon AB',rwy:0,hdg:164.1,len:2010,c:[[39.791475,124.713719],[39.79131,124.713039],[39.774091,124.720148],[39.774257,124.720826]]},
];

let runwayLayers = [], runwaysVisible = true;

let rwyOffsets = {};
try { rwyOffsets = JSON.parse(sessionStorage.getItem('bms_rwy_offsets')||'{}'); } catch(e){}

function saveRwyOffsets(){ sessionStorage.setItem('bms_rwy_offsets', JSON.stringify(rwyOffsets)); }

function applyOffset(latlon, icao) {
  const o = rwyOffsets[icao] || {dlat:0,dlon:0};
  return [latlon[0]+o.dlat, latlon[1]+o.dlon];
}

function renderRunways() {
  runwayLayers.forEach(l => { try { map.removeLayer(l); } catch(e){} });
  runwayLayers = [];

  RUNWAY_DATA.forEach(r => {
    const isNK = r.icao.startsWith('KP-') || r.icao.startsWith('ZK');
    const col     = isNK ? 'rgba(248,113,113,.75)' : 'rgba(148,185,220,.8)';
    const fillCol = isNK ? 'rgba(220,60,60,.18)'   : 'rgba(120,160,200,.15)';

    const corners = r.c.map(pt => applyOffset(pt, r.icao));

    const poly = L.polygon(corners, {
      color: col, fillColor: fillCol, fillOpacity: 1,
      weight: 2, interactive: false,
    });
    if (runwaysVisible) poly.addTo(map);
    runwayLayers.push(poly);

    const midA = [(corners[0][0]+corners[1][0])/2, (corners[0][1]+corners[1][1])/2];
    const midB = [(corners[2][0]+corners[3][0])/2, (corners[2][1]+corners[3][1])/2];
    const axis = L.polyline([midA, midB], {
      color: col, weight: 1.5, opacity: 0.6,
      dashArray: '8 5', interactive: false,
    });
    if (runwaysVisible) axis.addTo(map);
    runwayLayers.push(axis);
  });
}

let _calMode = false;
let _calIcao = null;
let _calAnchorPt = null;  // point théorique (avant offset) du premier coin

function openCalPanel() {
  document.getElementById('calPanel').style.display = 'block';
  const sel = document.getElementById('calIcaoSel');
  sel.innerHTML = '';
  const icaos = [...new Set(RUNWAY_DATA.map(r=>r.icao))].sort();
  icaos.forEach(ic => {
    const o = document.createElement('option');
    o.value = ic;
    const off = rwyOffsets[ic];
    o.textContent = ic + (off ? ` (${(off.dlat*111000).toFixed(0)}m N, ${(off.dlon*111000).toFixed(0)}m E)` : '');
    sel.appendChild(o);
  });
}

function startCalibration() {
  _calIcao = document.getElementById('calIcaoSel').value;
  if (!_calIcao) return;
  _calMode = true;
  document.getElementById('calPanel').style.display = 'none';
  document.getElementById('calStatus').textContent = `CALIB ${_calIcao} — Cliquez sur le seuil de piste réel`;
  document.getElementById('calStatus').style.display = 'block';
  map.getContainer().style.cursor = 'crosshair';

  const rwy0 = RUNWAY_DATA.find(r => r.icao === _calIcao);
  if (rwy0) {
    const cur = rwyOffsets[_calIcao] || {dlat:0,dlon:0};
    _calAnchorPt = [rwy0.c[0][0]+cur.dlat, rwy0.c[0][1]+cur.dlon];
    if (window._calTmpMarker) { try{map.removeLayer(window._calTmpMarker);}catch(e){} }
    window._calTmpMarker = L.circleMarker(_calAnchorPt, {
      radius:8, color:'#fbbf24', fillColor:'rgba(251,191,36,.3)',
      fillOpacity:1, weight:2, interactive:false
    }).addTo(map);
  }
}

map.on('click', function(e) {
  if (!_calMode) return;
  _calMode = false;
  map.getContainer().style.cursor = '';
  document.getElementById('calStatus').style.display = 'none';
  if (window._calTmpMarker) { try{map.removeLayer(window._calTmpMarker);}catch(e){} }

  if (!_calAnchorPt) return;
  const dlat = e.latlng.lat - _calAnchorPt[0];
  const dlon = e.latlng.lng - _calAnchorPt[1];

  const cur = rwyOffsets[_calIcao] || {dlat:0,dlon:0};
  rwyOffsets[_calIcao] = { dlat: cur.dlat+dlat, dlon: cur.dlon+dlon };
  saveRwyOffsets();
  renderRunways();

  const dn = ((cur.dlat+dlat)*111000).toFixed(0);
  const de = ((cur.dlon+dlon)*111000*Math.cos(_calAnchorPt[0]*Math.PI/180)).toFixed(0);
  showToast(`${_calIcao} recalé: ${dn>0?'+':''}${dn}m N, ${de>0?'+':''}${de}m E`);
});

function resetCalibration() {
  const ic = document.getElementById('calIcaoSel').value;
  if (ic) { delete rwyOffsets[ic]; saveRwyOffsets(); renderRunways(); openCalPanel(); }
}
function resetAllCalibration() {
  rwyOffsets = {}; saveRwyOffsets(); renderRunways(); openCalPanel();
}
renderRunways();

function connectWS(){
  const proto=location.protocol==='https:'?'wss:':'ws:';
  const ws=new WebSocket(`${proto}//${location.host}/ws`);
  ws.onmessage=e=>{
    const msg=JSON.parse(e.data);
    if(msg.type==='aircraft'){
      updateAircraft(msg.data);
      // Mettre à jour l'heure BMS si disponible
      if(msg.data.bms_time != null){
        _bmsTimeSec = msg.data.bms_time;
        _bmsTimeTs  = Date.now();
      }
    }
    if(msg.type==='radar')updateRadarContacts(msg.data);
    if(msg.type==='acmi'){_lastAcmiContacts=msg.data;updateAcmiContacts(msg.data);}
    if(msg.type==='status'){
      const on=msg.data.connected;
      document.getElementById('dot').className='dot '+(on?'on':'off');
      document.getElementById('statusText').textContent=on?'BMS 4.38 CONNECTÉ':'NON DÉTECTÉ';
    }
  };
  ws.onclose=()=>setTimeout(connectWS,2000);
}
connectWS();

// ── Touch listeners passifs — améliore le scroll sur mobile ──────
try {
  const _passiveTest = Object.defineProperty({}, 'passive', {get: function(){ return true; }});
  window.addEventListener('testPassive', null, _passiveTest);
  window.removeEventListener('testPassive', null, _passiveTest);
  // Appliquer le passive aux events tactiles de la carte
  const _mapEl = document.getElementById('map');
  if (_mapEl) {
    _mapEl.addEventListener('touchstart', function(){}, {passive:true});
    _mapEl.addEventListener('touchmove',  function(){}, {passive:true});
  }
} catch(e) {}


// Appliquer le thème sauvegardé au démarrage
(async function applyThemeOnLoad(){
  try {
    const d = await(await fetch('/api/settings')).json();
    if (d.theme && d.theme !== 'dark') selectTheme(d.theme, false);
  } catch(e) {}
})();

let dlMarkers=[],dlVisible=true;
// Datalink actif par défaut
document.getElementById('radarBtn').classList.add('active');
document.getElementById('radarBtn').addEventListener('click',()=>{
  dlVisible=!dlVisible;
  document.getElementById('radarBtn').classList.toggle('active',dlVisible);
  dlMarkers.forEach(m=>{try{if(dlVisible)m.addTo(map);else map.removeLayer(m);}catch(e){}});
});


function dlSym(camp,col,sz){
  sz=sz||22;
  const h=sz,cx=sz/2;
  if(camp===1){
    const r=cx-2;
    return `<svg width="${h}" height="${h}" viewBox="0 0 ${h} ${h}">
      <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${col}" stroke-width="2"/>
      <line x1="${cx}" y1="${2}" x2="${cx}" y2="${h-2}" stroke="${col}" stroke-width="1.5"/>
      <line x1="${2}" y1="${cx}" x2="${h-2}" y2="${cx}" stroke="${col}" stroke-width="1.5"/>
    </svg>`;
  }
  if(camp===2){
    const m=cx;
    return `<svg width="${h}" height="${h}" viewBox="0 0 ${h} ${h}">
      <polygon points="${m},2 ${h-2},${h-2} 2,${h-2}"
        fill="${col}" fill-opacity=".88" stroke="rgba(0,0,0,.5)" stroke-width="1.2"/>
    </svg>`;
  }
  return `<svg width="${h}" height="${h}" viewBox="0 0 ${h} ${h}">
    <rect x="2" y="2" width="${h-4}" height="${h-4}" fill="none" stroke="${col}" stroke-width="2"/>
    <line x1="${cx}" y1="${2}" x2="${cx}" y2="${h-2}" stroke="${col}" stroke-width="1" opacity=".4"/>
    <line x1="${2}" y1="${cx}" x2="${h-2}" y2="${cx}" stroke="${col}" stroke-width="1" opacity=".4"/>
  </svg>`;
}

function dlVec(hdg,col){
  const r=hdg*Math.PI/180,len=22;
  const dx=Math.sin(r)*len,dy=-Math.cos(r)*len;
  const sz=60,c=30;
  return `<svg width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}" style="overflow:visible">
    <line x1="${c}" y1="${c}" x2="${c+dx}" y2="${c+dy}"
      stroke="${col}" stroke-width="1.5" opacity=".6" stroke-dasharray="4 3"/>
    <circle cx="${c+dx}" cy="${c+dy}" r="1.5" fill="${col}" opacity=".7"/>
  </svg>`;
}

function updateRadarContacts(contacts){
  _lastDlContacts = contacts;
  dlMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});dlMarkers=[];
  if(!contacts||!contacts.length)return;
  if(!dlVisible){dlVisible=true;document.getElementById('radarBtn').classList.add('active');}
  // Taille adaptée au zoom (petite à zoom faible, plus grande en rapproché)
  const z = map.getZoom();
  const sz = z >= 10 ? 16 : z >= 8 ? 12 : 9;
  contacts.forEach(c=>{
    if(c.lat==null||c.lon==null)return;
    const camp=c.camp;
    const col=camp===1?'#4ade80':camp===2?'#f87171':'#fbbf24';
    const cls=camp===1?'friend':camp===2?'foe':'unknwn';

    const mS=L.marker([c.lat,c.lon],{icon:L.divIcon({
      html:dlSym(camp,col,sz),className:'',iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]
    }),zIndexOffset:camp===2?200:100});
    if(dlVisible)mS.addTo(map);dlMarkers.push(mS);

    // Vecteur cap uniquement si assez zoomé
    if(c.heading!=null && z>=8){
      const mV=L.marker([c.lat,c.lon],{icon:L.divIcon({
        html:dlVec(c.heading,col),className:'',iconSize:[40,40],iconAnchor:[20,20]
      }),zIndexOffset:50});
      if(dlVisible)mV.addTo(map);dlMarkers.push(mV);
    }

    // Label uniquement si assez zoomé
    if(z >= 7){
      const call=c.callsign||c.type_name||'';
      const altFL=c.alt!=null&&c.alt>0?'FL'+String(Math.round(c.alt/100)).padStart(3,'0'):'';
      const spdStr=c.speed!=null&&c.speed>10?Math.round(c.speed)+'kt':'';
      const hdgStr=c.heading!=null&&z>=9?String(Math.round(c.heading)).padStart(3,'0')+'°':'';
      const dataLine=[altFL,spdStr,hdgStr].filter(Boolean).join('\u00a0·\u00a0');
      const lH=`<div class="dl-block">
        ${call?`<div class="dl-callsign ${cls}" style="font-size:${z>=9?11:10}px">${call}</div>`:''}
        ${dataLine&&z>=8?`<div class="dl-data ${cls}">${dataLine}</div>`:''}
      </div>`;
      const mL=L.marker([c.lat,c.lon],{icon:L.divIcon({
        html:lH,className:'',iconSize:[110,30],iconAnchor:[-(sz/2+2),14]
      }),zIndexOffset:camp===2?201:101});
      if(dlVisible)mL.addTo(map);dlMarkers.push(mL);
    }
  });
}

// Redessiner les contacts quand le zoom change
map.on('zoomend', ()=>{
  if(_lastDlContacts) updateRadarContacts(_lastDlContacts);
  if(_lastAcmiContacts) updateAcmiContacts(_lastAcmiContacts);
});
let _lastDlContacts=[];
let _lastAcmiContacts=null;

// ── Contacts ACMI coalition (TRTT — mode dieu) ───────────────────
// Séparé du datalink L16 : bouton propre, toggle indépendant
let acmiMarkers=[], acmiVisible=true;

function updateAcmiContacts(contacts){
  _lastAcmiContacts = contacts;
  acmiMarkers.forEach(m=>{try{map.removeLayer(m)}catch(e){}});acmiMarkers=[];
  if(!contacts||!contacts.length||!acmiVisible)return;
  const z = map.getZoom();
  const sz = z >= 10 ? 14 : z >= 8 ? 10 : 7;
  contacts.forEach(c=>{
    if(c.lat==null||c.lon==null)return;
    // camp=3 (unknown) traité comme allié en solo — BMS injecte les couleurs tardivement
    const camp = c.camp === 2 ? 2 : 1;
    const col = '#4ade80'; // vert allié (ennemis exclus côté serveur)
    const mS=L.marker([c.lat,c.lon],{icon:L.divIcon({
      html:dlSym(1,col,sz),className:'',iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]
    }),zIndexOffset:80,interactive:false});
    mS.addTo(map);acmiMarkers.push(mS);
    // Vecteur cap si assez zoomé
    if(c.heading!=null && z>=9){
      const mV=L.marker([c.lat,c.lon],{icon:L.divIcon({
        html:dlVec(c.heading,col),className:'',iconSize:[36,36],iconAnchor:[18,18]
      }),zIndexOffset:40,interactive:false});
      mV.addTo(map);acmiMarkers.push(mV);
    }
    // Label : callsign court + altitude — seulement si zoom >= 9
    if(z >= 9){
      const raw = c.callsign || c.type_name || '';
      // Garder le type avion : "F-16CM-52" → "F-16", "Su-27" → "Su-27"
      const call = raw.replace(/-\d+$/, '').trim();
      const altFL = c.alt!=null&&c.alt>0 ? 'FL'+String(Math.round(c.alt/100)).padStart(3,'0') : '';
      const lH=`<div class="dl-block">
        ${call?`<div class="dl-callsign friend" style="font-size:10px;opacity:.8">${call}</div>`:''}
        ${altFL?`<div class="dl-data friend">${altFL}</div>`:''}
      </div>`;
      const mL=L.marker([c.lat,c.lon],{icon:L.divIcon({
        html:lH,className:'',iconSize:[80,24],iconAnchor:[-(sz/2+2),10]
      }),zIndexOffset:81,interactive:false});
      mL.addTo(map);acmiMarkers.push(mL);
    }
  });
}

function toggleTRTTPanel(){
  const p=document.getElementById('trttPanel');
  const visible=p.style.display==='none';
  p.style.display=visible?'block':'none';
  if(visible){
    fetch('/api/acmi/status').then(r=>r.json()).then(d=>{
      const parts=(d.trtt_host||'127.0.0.1:42674').split(':');
      document.getElementById('trttHostInput').value=parts[0];
      document.getElementById('trttPortInput').value=parts[1]||'42674';
      document.getElementById('trttPanelStatus').textContent=
        d.connected?'● Connecté — '+d.nb_contacts+' contacts':'○ Non connecté';
    }).catch(()=>{});
  }
}
async function applyTRTTConfig(){
  const host=document.getElementById('trttHostInput').value.trim();
  const port=parseInt(document.getElementById('trttPortInput').value)||42674;
  if(!host){document.getElementById('trttPanelStatus').textContent='Entrez une IP';return;}
  document.getElementById('trttPanelStatus').textContent='Connexion…';
  try{
    const r=await fetch('/api/trtt/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({host,port})});
    const d=await r.json();
    document.getElementById('trttPanelStatus').textContent=d.status==='ok'?'✓ '+d.trtt_host:'Erreur';
    setTimeout(()=>document.getElementById('trttPanel').style.display='none',1500);
  }catch(e){document.getElementById('trttPanelStatus').textContent='Erreur: '+e.message;}
}
document.addEventListener('click',e=>{
  if(!e.target.closest('#trttPanel')&&!e.target.closest('#trttConfigBtn'))
    document.getElementById('trttPanel').style.display='none';
});

// ══════════════════════════════════════════════════════════════════
//  SETTINGS
// ══════════════════════════════════════════════════════════════════
let _settingsOpen = false;
let _currentTheme = 'dark';

async function loadSettings() {
  try {
    const d = await(await fetch('/api/settings')).json();
    document.getElementById('sp-port').value    = d.port         || 8000;
    document.getElementById('sp-briefdir').value= d.briefing_dir || '';
    document.getElementById('sp-bcast').value   = d.broadcast_ms || 200;
    _currentTheme = d.theme || 'dark';
    selectTheme(_currentTheme, false);
  } catch(e) {}
}

function toggleSettings() {
  _settingsOpen = !_settingsOpen;
  document.getElementById('settingsPanel').classList.toggle('open', _settingsOpen);
  if (_settingsOpen) loadSettings();
}

function selectTheme(t, save=false) {
  _currentTheme = t;
  document.getElementById('sp-theme-dark').classList.toggle('sel',  t==='dark');
  document.getElementById('sp-theme-light').classList.toggle('sel', t==='light');
  // Appliquer le thème sur le document
  if (t === 'light') {
    document.documentElement.style.setProperty('--map-bg',   '#e8ecf0');
    document.documentElement.style.setProperty('--ui-bg',    'rgba(240,244,248,.98)');
    document.documentElement.style.setProperty('--ui-text',  '#1e293b');
    document.documentElement.style.setProperty('--acc-green','#166534');
    document.body.style.filter = 'invert(1) hue-rotate(180deg)';
  } else {
    document.documentElement.style.removeProperty('--map-bg');
    document.documentElement.style.removeProperty('--ui-bg');
    document.documentElement.style.removeProperty('--ui-text');
    document.documentElement.style.removeProperty('--acc-green');
    document.body.style.filter = '';
  }
}

async function saveSettings() {
  const port     = parseInt(document.getElementById('sp-port').value);
  const bdir     = document.getElementById('sp-briefdir').value.trim();
  const bcast    = parseInt(document.getElementById('sp-bcast').value);
  const theme    = _currentTheme;
  const status   = document.getElementById('sp-status');
  const portWarn = document.getElementById('sp-port-warn');

  status.textContent = '⏳ Sauvegarde…';
  status.classList.add('show');

  try {
    const r = await fetch('/api/settings', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        port:         isNaN(port)  ? null : port,
        briefing_dir: bdir         || null,
        broadcast_ms: isNaN(bcast) ? null : bcast,
        theme:        theme,
      })
    });
    const d = await r.json();
    if (d.ok) {
      status.textContent = '✓ Sauvegardé — ' + d.changed.join(', ');
      status.style.color = '#4ade80';
      if (d.needs_restart) {
        portWarn.classList.add('show');
        status.textContent += ' — RELANCER LE SCRIPT';
        status.style.color = '#fbbf24';
      }
      setTimeout(() => {
        status.classList.remove('show');
        if (!d.needs_restart) toggleSettings();
      }, 2200);
    } else {
      status.textContent = '✗ Erreur';
      status.style.color = '#ef4444';
    }
  } catch(e) {
    status.textContent = '✗ ' + e;
    status.style.color = '#ef4444';
  }
}

// Fermer settings si clic sur la carte
document.getElementById('map').addEventListener('click', () => {
  if (_settingsOpen) toggleSettings();
});

// ── Horloge — BMS time prioritaire, fallback UTC ─────────────────
let _bmsTimeSec = null;   // secondes depuis minuit reçues de BMS
let _bmsTimeTs  = 0;      // timestamp JS de la dernière réception

function updateZulu(){
  const el = document.getElementById('zuluClock');
  if (!el) return;
  let secs = null;
  // Si BMS time reçu récemment (< 5s), interpoler depuis le timestamp
  if (_bmsTimeSec !== null && (Date.now() - _bmsTimeTs) < 5000) {
    const elapsed = Math.floor((Date.now() - _bmsTimeTs) / 1000);
    secs = (_bmsTimeSec + elapsed) % 86400;
    el.title = 'Heure BMS';
    el.style.color = 'rgba(74,222,128,.55)';
  } else {
    // Fallback UTC
    const n = new Date();
    secs = n.getUTCHours()*3600 + n.getUTCMinutes()*60 + n.getUTCSeconds();
    el.title = 'Heure UTC (BMS non connecté)';
    el.style.color = 'rgba(74,222,128,.35)';
  }
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  el.textContent = String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')+'Z';
}
updateZulu(); setInterval(updateZulu, 1000);

// ── Affichage IP serveur ─────────────────────────────────────────
(async function loadServerIp(){
  try{
    const d = await(await fetch('/api/server/info')).json();
    const el = document.getElementById('sysServerIp');
    if(el && d.ip){
      el.textContent = d.ip + ':' + d.port;
      el.title = 'Tablette → ' + d.url;
    }
  } catch(e){ /* silencieux */ }
})();

document.addEventListener('click',e=>{
  if(!e.target.closest('#colorPanel')&&!e.target.closest('#colorBtn'))
    document.getElementById('colorPanel').classList.remove('open');
  if(!e.target.closest('#layerPanel')&&!e.target.closest('#layerBtn'))
    document.getElementById('layerPanel').classList.remove('open');

  if(!e.target.closest('#calPanel')&&!_calMode)
    document.getElementById('calPanel').style.display='none';
});
</script>

<!-- CALIBRATION PANEL -->
<div id="calPanel" style="display:none;position:fixed;top:80px;left:60px;
  background:rgba(4,8,18,.97);border:1px solid rgba(251,191,36,.25);
  border-top:2px solid rgba(251,191,36,.4);border-radius:3px;
  padding:12px 14px;z-index:2000;min-width:240px;backdrop-filter:blur(16px)">
  <div style="font-family:system-ui,sans-serif;font-size:9px;font-weight:700;
    color:#fbbf24;letter-spacing:2px;text-transform:uppercase;margin-bottom:10px">
    ✎ Calibration pistes</div>
  <div style="font-family:'Consolas','Courier New',monospace;font-size:10px;color:#64748b;
    margin-bottom:8px;line-height:1.5">
    1. Sélectionner la base<br>
    2. Cliquer "Calibrer"<br>
    3. Cliquer sur le <span style="color:#fbbf24">seuil réel</span> de la piste</div>
  <select id="calIcaoSel" style="width:100%;background:rgba(255,255,255,.04);
    border:1px solid rgba(255,255,255,.1);border-radius:2px;padding:5px 8px;
    color:#e2e8f0;font-family:'Consolas','Courier New',monospace;font-size:11px;
    margin-bottom:8px;outline:none"></select>
  <div style="display:flex;gap:6px;flex-wrap:wrap">
    <button onclick="startCalibration()"
      style="flex:1;background:rgba(251,191,36,.12);border:1px solid rgba(251,191,36,.3);
      border-radius:2px;padding:5px;color:#fbbf24;font-family:system-ui,sans-serif;
      font-size:11px;font-weight:700;cursor:pointer;letter-spacing:1px">CALIBRER</button>
    <button onclick="resetCalibration()"
      style="background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);
      border-radius:2px;padding:5px 8px;color:#f87171;font-family:system-ui,sans-serif;
      font-size:11px;cursor:pointer">RESET</button>
    <button onclick="document.getElementById('calPanel').style.display='none'"
      style="background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);
      border-radius:2px;padding:5px 8px;color:#64748b;font-family:system-ui,sans-serif;
      font-size:11px;cursor:pointer">✕</button>
  </div>
  <div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,.05)">
    <button onclick="resetAllCalibration()"
      style="width:100%;background:transparent;border:1px solid rgba(239,68,68,.15);
      border-radius:2px;padding:3px;color:#64748b;font-family:system-ui,sans-serif;
      font-size:10px;cursor:pointer">Reset toutes les bases</button>
  </div>
</div>
<!-- STATUS CALIBRATION -->
<div id="calStatus" style="display:none;position:fixed;top:40px;left:50%;
  transform:translateX(-50%);background:rgba(251,191,36,.15);
  border:1px solid rgba(251,191,36,.4);border-radius:3px;
  padding:6px 16px;z-index:3000;font-family:system-ui,sans-serif;
  font-size:13px;font-weight:700;color:#fbbf24;letter-spacing:1px;
  pointer-events:none"></div>

<!-- ═══════════════════════════════════════════════════════════════
     TAB PANELS
════════════════════════════════════════════════════════════════ -->

<!-- GPS PANEL -->
<div class="tab-panel" id="panel-gps">
  <div class="gps-row">
    <div class="gps-field">
      <span class="gps-lbl">LAT</span>
      <span class="gps-val green" id="gps-lat">—</span>
    </div>
    <div class="gps-field">
      <span class="gps-lbl">LON</span>
      <span class="gps-val green" id="gps-lon">—</span>
    </div>
    <div class="gps-field">
      <span class="gps-lbl">HDG</span>
      <span class="gps-val amber" id="gps-hdg">—</span>
    </div>
    <div class="gps-field">
      <span class="gps-lbl">ALT</span>
      <span class="gps-val white" id="gps-alt">—</span>
    </div>
    <div class="gps-field">
      <span class="gps-lbl">KIAS</span>
      <span class="gps-val white" id="gps-kias">—</span>
    </div>
    <div class="gps-field">
      <span class="gps-lbl">DIST ↗ STPT</span>
      <span class="gps-val amber" id="gps-dist">—</span>
    </div>
    <div class="gps-field">
      <span class="gps-lbl">BULL</span>
      <span class="gps-val" style="color:#f97316" id="gps-bull">—</span>
    </div>
  </div>
  <div style="padding:4px 18px 4px;display:flex;align-items:center;gap:8px">
    <span style="font-family:system-ui,sans-serif;font-size:9px;font-weight:700;color:#3d6b52;letter-spacing:1.5px;text-transform:uppercase">STEERPOINTS</span>
    <span id="gps-steer-count" style="font-family:'Consolas','Courier New',monospace;font-size:9px;color:#3d6b52">0 WPT</span>
  </div>
  <div class="gps-steer-list" id="gps-steer-list">
    <span style="font-family:system-ui,sans-serif;font-size:11px;color:#3d6b52;padding:4px 0">Aucun plan de vol chargé</span>
  </div>
</div>

<!-- CHARTS PANEL -->
<div class="tab-panel" id="panel-charts">
  <div class="charts-header">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 3v18h18"/><polyline points="18 9 13 14 9 10 3 16"/>
    </svg>
    <span>FALCON CHARTS</span>
    <span class="ext-badge">FALCONCHARTS.COM</span>
    <button onclick="document.getElementById('panel-charts').classList.remove('open');document.querySelector('[data-tab=charts]').classList.remove('active')" style="margin-left:8px;background:transparent;border:none;cursor:pointer;color:#546e82;font-size:16px;line-height:1;padding:0 4px" title="Fermer">✕</button>
  </div>
  <iframe id="charts-frame" src="about:blank" allowfullscreen></iframe>
</div>

<!-- KNEEBOARD PANEL -->
<div class="tab-panel" id="panel-kneeboard">
  <div class="kb-header">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
    </svg>
    <span class="kb-header-title">KNEEBOARD</span>
    <div class="kb-tabs">
      <div class="kb-tab active" data-kbtab="comms"    style="--kt:#4ade80" onclick="switchKbTab('comms',this)">COMMS</div>
      <div class="kb-tab"        data-kbtab="fplan"    style="--kt:#60a5fa" onclick="switchKbTab('fplan',this)">PLAN DE VOL</div>
      <div class="kb-tab"        data-kbtab="notes"    style="--kt:#fbbf24" onclick="switchKbTab('notes',this)">NOTES</div>
      <div class="kb-tab"        data-kbtab="cas"      style="--kt:#f97316" onclick="switchKbTab('cas',this)">9-LINE</div>
      <div class="kb-tab"        data-kbtab="brevity"  style="--kt:#94a3b8" onclick="switchKbTab('brevity',this)">BREVITY</div>
    </div>
  </div>
  <div class="kb-body">

    <!-- ── COMMS LADDER ── -->
    <div class="kb-page active" id="kb-comms">
      <table class="freq-table">
        <thead><tr><th>RÔLE</th><th>UHF (MHz)</th><th>VHF / REMARQUE</th></tr></thead>
        <tbody>
          <tr><td>GUARD</td><td class="hi" style="color:#ef4444">243.000</td><td style="color:#ef4444">Urgence UHF</td></tr>
          <tr><td>GUARD VHF</td><td class="hi" style="color:#ef4444">121.500</td><td style="color:#ef4444">Urgence VHF</td></tr>
          <tr style="background:rgba(74,222,128,.04)"><td><b>AWACS</b></td><td class="hi">268.800</td><td>Alpha — Corée BMS</td></tr>
          <tr style="background:rgba(74,222,128,.04)"><td><b>AWACS Bravo</b></td><td class="hi">265.400</td><td>Secondary</td></tr>
          <tr><td>Tanker CH11</td><td class="hi">317.175</td><td>A/R standard</td></tr>
          <tr><td>Tanker CH12</td><td class="hi">340.200</td><td>Backup</td></tr>
          <tr style="background:rgba(96,165,250,.04)"><td>Osan Tower</td><td class="hi">126.200</td><td>RKSO</td></tr>
          <tr style="background:rgba(96,165,250,.04)"><td>Osan Appr.</td><td class="hi">119.300</td><td>RKSO</td></tr>
          <tr style="background:rgba(96,165,250,.04)"><td>Gunsan Tower</td><td class="hi">122.100</td><td>RKJK</td></tr>
          <tr style="background:rgba(96,165,250,.04)"><td>Daegu Tower</td><td class="hi">126.200</td><td>RKTN</td></tr>
          <tr style="background:rgba(96,165,250,.04)"><td>Seoul AB</td><td class="hi">126.200</td><td>RKSM</td></tr>
          <tr style="background:rgba(96,165,250,.04)"><td>Incheon Tower</td><td class="hi">119.100</td><td>RKSI</td></tr>
          <tr><td>ATC Centre</td><td class="hi">127.900</td><td>Seoul Centre</td></tr>
          <tr><td>SAR / CSAR</td><td class="hi">282.800</td><td>Combat SAR</td></tr>
          <tr><td>JTAC (def.)</td><td class="hi">305.000</td><td>Interop CAS</td></tr>
        </tbody>
      </table>
    </div>

    <!-- ── PLAN DE VOL ── -->
    <div class="kb-page" id="kb-fplan">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px">
        <div class="kb-field-group">
          <div class="kb-field-lbl">CALLSIGN / FLIGHT</div>
          <input class="kb-input" id="kb-callsign" placeholder="VIPER 1-1" autocomplete="off">
        </div>
        <div class="kb-field-group">
          <div class="kb-field-lbl">PACKAGE</div>
          <input class="kb-input" id="kb-package" placeholder="ALPHA BRAVO" autocomplete="off">
        </div>
        <div class="kb-field-group">
          <div class="kb-field-lbl">TOT</div>
          <input class="kb-input" id="kb-tot" placeholder="14:30Z" autocomplete="off">
        </div>
        <div class="kb-field-group">
          <div class="kb-field-lbl">TANKER / FREQ</div>
          <input class="kb-input" id="kb-tanker" placeholder="SHELL 1 / 317.175" autocomplete="off">
        </div>
        <div class="kb-field-group">
          <div class="kb-field-lbl">BULLSEYE</div>
          <input class="kb-input" id="kb-bull-val" placeholder="270/45 NM" autocomplete="off">
        </div>
        <div class="kb-field-group">
          <div class="kb-field-lbl">BINGO FUEL</div>
          <input class="kb-input" id="kb-bingo" placeholder="3500 lbs" autocomplete="off">
        </div>
      </div>
      <div class="kb-field-lbl" style="margin-bottom:6px">NOTES DE MISSION</div>
      <textarea class="kb-notes" id="kb-fplan-ta" placeholder="Objectif, menaces, règles d'engagement…" style="height:120px"></textarea>
    </div>

    <!-- ── NOTES LIBRES ── -->
    <div class="kb-page" id="kb-notes">
      <textarea class="kb-notes" id="kb-notes-ta" placeholder="Notes libres…"></textarea>
    </div>

    <!-- ── 9-LINE CAS ── -->
    <div class="kb-page" id="kb-cas">
      <div style="display:grid;grid-template-columns:auto 1fr;gap:6px 12px;align-items:center">
        <span class="kb-9l-num">1</span><div class="kb-field-group"><div class="kb-field-lbl">IP / HEADING TO TARGET</div><input class="kb-input kb-9l" id="kb-9l-1" placeholder="IP ALPHA / HDG 090" autocomplete="off"></div>
        <span class="kb-9l-num">2</span><div class="kb-field-group"><div class="kb-field-lbl">ELEVATION</div><input class="kb-input kb-9l" id="kb-9l-2" placeholder="1250 ft MSL" autocomplete="off"></div>
        <span class="kb-9l-num">3</span><div class="kb-field-group"><div class="kb-field-lbl">DESCRIPTION TARGET</div><input class="kb-input kb-9l" id="kb-9l-3" placeholder="T-72 en position, 3 véhicules" autocomplete="off"></div>
        <span class="kb-9l-num">4</span><div class="kb-field-group"><div class="kb-field-lbl">LOCALISATION TARGET</div><input class="kb-input kb-9l" id="kb-9l-4" placeholder="Grid / MGRS / BRAA" autocomplete="off"></div>
        <span class="kb-9l-num">5</span><div class="kb-field-group"><div class="kb-field-lbl">MARQUAGE TARGET</div><input class="kb-input kb-9l" id="kb-9l-5" placeholder="Laze / Smoke / IR" autocomplete="off"></div>
        <span class="kb-9l-num">6</span><div class="kb-field-group"><div class="kb-field-lbl">FRIENDLY LOCATION</div><input class="kb-input kb-9l" id="kb-9l-6" placeholder="500m North of target" autocomplete="off"></div>
        <span class="kb-9l-num">7</span><div class="kb-field-group"><div class="kb-field-lbl">EGRESS</div><input class="kb-input kb-9l" id="kb-9l-7" placeholder="West / RTB RKSO" autocomplete="off"></div>
        <span class="kb-9l-num">8</span><div class="kb-field-group"><div class="kb-field-lbl">REMARQUES / THREATS</div><input class="kb-input kb-9l" id="kb-9l-8" placeholder="SA-13 au Nord, MANPADS" autocomplete="off"></div>
        <span class="kb-9l-num">9</span><div class="kb-field-group"><div class="kb-field-lbl">JTAC CALL / FREQ</div><input class="kb-input kb-9l" id="kb-9l-9" placeholder="DARKSTAR 1 / 305.000" autocomplete="off"></div>
      </div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <button onclick="clearNineLines()" style="background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);border-radius:2px;padding:5px 14px;color:#f87171;font-size:11px;font-weight:700;cursor:pointer;letter-spacing:1px">EFFACER</button>
        <button onclick="copyNineLines()" style="background:rgba(96,165,250,.08);border:1px solid rgba(96,165,250,.2);border-radius:2px;padding:5px 14px;color:#60a5fa;font-size:11px;font-weight:700;cursor:pointer;letter-spacing:1px">COPIER</button>
      </div>
    </div>

    <!-- ── BREVITY ── -->
    <div class="kb-page" id="kb-brevity">
      <div class="brev-grid">
        <div class="brev-item"><div class="brev-word">BOGEY</div><div class="brev-def">Contact aérien non identifié</div></div>
        <div class="brev-item"><div class="brev-word">BANDIT</div><div class="brev-def">Contact aérien ennemi confirmé</div></div>
        <div class="brev-item"><div class="brev-word">FRIENDLY</div><div class="brev-def">Contact aérien ami confirmé</div></div>
        <div class="brev-item"><div class="brev-word">SPIKE</div><div class="brev-def">Missile SAM en vol / radar lock ennemi</div></div>
        <div class="brev-item"><div class="brev-word">BLIND</div><div class="brev-def">Pas de contact visuel avec wingman</div></div>
        <div class="brev-item"><div class="brev-word">VISUAL</div><div class="brev-def">Contact visuel confirmé</div></div>
        <div class="brev-item"><div class="brev-word">BINGO</div><div class="brev-def">Carburant minimum pour RTB</div></div>
        <div class="brev-item"><div class="brev-word">WINCHESTER</div><div class="brev-def">Toutes munitions épuisées</div></div>
        <div class="brev-item"><div class="brev-word">FOX 1</div><div class="brev-def">Tir missile semi-actif (AIM-7)</div></div>
        <div class="brev-item"><div class="brev-word">FOX 2</div><div class="brev-def">Tir missile IR (AIM-9)</div></div>
        <div class="brev-item"><div class="brev-word">FOX 3</div><div class="brev-def">Tir missile actif (AIM-120)</div></div>
        <div class="brev-item"><div class="brev-word">GUNS</div><div class="brev-def">Tir canon</div></div>
        <div class="brev-item"><div class="brev-word">MERGE</div><div class="brev-def">Engagement WVR</div></div>
        <div class="brev-item"><div class="brev-word">DEFENSIVE</div><div class="brev-def">Sous attaque — appui immédiat</div></div>
        <div class="brev-item"><div class="brev-word">PITBULL</div><div class="brev-def">AMRAAM auto-guidage actif</div></div>
        <div class="brev-item"><div class="brev-word">SKOSH</div><div class="brev-def">AIM-120 portée limite</div></div>
        <div class="brev-item"><div class="brev-word">BRAA</div><div class="brev-def">Bearing / Range / Altitude / Aspect</div></div>
        <div class="brev-item"><div class="brev-word">BULLSEYE</div><div class="brev-def">Référence navigation partagée</div></div>
        <div class="brev-item"><div class="brev-word">ANGELS</div><div class="brev-def">Altitude × 1000 ft</div></div>
        <div class="brev-item"><div class="brev-word">CHERUBS</div><div class="brev-def">Altitude × 100 ft (&lt;1000)</div></div>
        <div class="brev-item"><div class="brev-word">DECLARE</div><div class="brev-def">Demande ID contact au GCI</div></div>
        <div class="brev-item"><div class="brev-word">TALLY</div><div class="brev-def">Contact visuel bogey confirmé</div></div>
        <div class="brev-item"><div class="brev-word">NO JOY</div><div class="brev-def">Pas de contact visuel bogey</div></div>
        <div class="brev-item"><div class="brev-word">SNAP</div><div class="brev-def">Vecteur interception immédiat</div></div>
      </div>
    </div>

  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════
     TAB BAR — 3 groupes : NAV / DOCS / CREW
════════════════════════════════════════════════════════════════ -->
<div id="tabBar">

  <!-- ── GROUPE NAV ── -->
  <div class="tab-group" style="flex:1">
    <span class="tab-group-label">NAV</span>
    <button class="tab-btn" data-tab="gps" onclick="switchTab('gps',this)">
      <div class="tab-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="1.8">
          <circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8" stroke-dasharray="3 2"/>
          <line x1="12" y1="2" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22"/>
          <line x1="2" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="22" y2="12"/>
        </svg>
      </div>
      <span class="tab-label">GPS</span>
    </button>
  </div>

  <div class="tab-group-sep" data-label="·"></div>

  <!-- ── GROUPE DOCS ── -->
  <div class="tab-group" style="flex:2">
    <span class="tab-group-label">DOCS</span>
    <button class="tab-btn" data-tab="charts" onclick="switchTab('charts',this)">
      <div class="tab-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="1.8">
          <rect x="3" y="3" width="18" height="14" rx="2"/>
          <line x1="3" y1="9" x2="21" y2="9"/>
          <line x1="9" y1="3" x2="9" y2="17"/>
          <path d="M12 20l2 2 2-2" stroke-width="1.5"/>
        </svg>
      </div>
      <span class="tab-label">CHARTS</span>
    </button>
    <button class="tab-btn" data-tab="briefing" onclick="switchTab('briefing',this)">
      <div class="tab-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="1.8">
          <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
          <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
        </svg>
      </div>
      <span class="tab-label">BRIEFING</span>
    </button>
  </div>

  <div class="tab-group-sep" data-label="·"></div>

  <!-- ── GROUPE CREW ── -->
  <div class="tab-group" style="flex:1">
    <span class="tab-group-label">CREW</span>
    <button class="tab-btn" data-tab="kneeboard" onclick="switchTab('kneeboard',this)">
      <div class="tab-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" stroke-width="1.8">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="12" y2="17"/>
        </svg>
      </div>
      <span class="tab-label">KNEEBOARD</span>
    </button>
  </div>

</div>

<!-- BRIEFING PANEL -->
<div class="tab-panel" id="panel-briefing">
  <div class="brief-header">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
    </svg>
    <span class="brief-header-title">BRIEFING</span>
    <span id="briefFileCount" style="font-family:'Consolas','Courier New',monospace;font-size:9px;color:#3d6b52;letter-spacing:1px">0 DOC</span>
    <div style="margin-left:auto;display:flex;align-items:center;gap:8px">
      <div class="brief-upload-btn" onclick="document.getElementById('briefingFileInput').click()">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        IMPORTER
      </div>
      <button onclick="document.getElementById('panel-briefing').classList.remove('open');document.querySelector('[data-tab=briefing]').classList.remove('active')" style="background:transparent;border:none;cursor:pointer;color:#546e82;font-size:16px;padding:0 4px">✕</button>
    </div>
  </div>
  <input type="file" id="briefingFileInput" accept=".pdf,.png,.jpg,.jpeg,.docx" multiple onchange="briefingUpload(this.files)">
  <div class="brief-body">
    <!-- Sidebar -->
    <div class="brief-sidebar">
      <div class="brief-sidebar-hdr">DOCUMENTS</div>
      <div class="brief-file-list" id="briefFileList">
        <div class="brief-empty">Aucun document<br>Importer PDF, image<br>ou Word (.docx)</div>
      </div>
    </div>
    <!-- Viewer -->
    <div class="brief-viewer" id="briefViewer">
      <div class="brief-placeholder" id="briefPlaceholder">
        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="1">
          <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
          <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
        </svg>
        <span class="brief-placeholder-txt">Sélectionner un document</span>
      </div>
      <iframe id="briefIframe" src="about:blank" style="display:none"></iframe>
    </div>
  </div>
</div>

<script>
// ── Tab switching ────────────────────────────────────────────────
const PANELS = {
  gps:       document.getElementById('panel-gps'),
  charts:    document.getElementById('panel-charts'),
  kneeboard: document.getElementById('panel-kneeboard'),
  briefing:  document.getElementById('panel-briefing'),
};
let _activeTab = null;
let _chartsLoaded = false;

function switchTab(name, btn) {
  const panel = PANELS[name];
  if (!panel) return;

  // Toggle: cliquer sur l'onglet actif le ferme
  if (_activeTab === name) {
    panel.classList.remove('open');
    btn.classList.remove('active');
    _activeTab = null;
    return;
  }

  // Fermer tous les autres
  Object.entries(PANELS).forEach(([k, p]) => {
    p.classList.remove('open');
  });
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));

  panel.classList.add('open');
  btn.classList.add('active');
  _activeTab = name;

  // Charger la Charts iframe au premier clic
  if (name === 'charts' && !_chartsLoaded) {
    _chartsLoaded = true;
    document.getElementById('charts-frame').src = 'https://www.falcon-charts.com';
  }

  // Refresh GPS data immédiatement
  if (name === 'gps') refreshGpsPanel();

  // Charger la liste briefing à chaque ouverture
  if (name === 'briefing') briefingLoadList();
}

// ══════════════════════════════════════════════════════════════════
//  BRIEFING
// ══════════════════════════════════════════════════════════════════
let _briefActive = null;

function briefingLoadList() {
  fetch('/api/briefing/list')
    .then(r => r.json())
    .then(d => briefingRenderList(d.files))
    .catch(() => {});
}

function briefingRenderList(files) {
  const list  = document.getElementById('briefFileList');
  const count = document.getElementById('briefFileCount');
  count.textContent = files.length + ' DOC';
  if (!files.length) {
    list.innerHTML = '<div class="brief-empty">Aucun document<br>Importer PDF, image<br>ou Word (.docx)</div>';
    return;
  }
  list.innerHTML = files.map(f => {
    const iconCls = f.ext === 'pdf' ? 'pdf' : (f.ext === 'docx' ? 'docx' : 'img');
    const label   = f.ext.toUpperCase();
    const isActive = _briefActive === f.name ? ' active' : '';
    return `<div class="brief-file-item${isActive}" onclick="briefingOpen('${f.name}','${f.ext}')" data-name="${f.name}">
      <div class="brief-file-icon ${iconCls}">${label}</div>
      <div class="brief-file-info">
        <div class="brief-file-name">${f.name}</div>
        <div class="brief-file-meta">${f.size_kb} KB · ${f.modified}</div>
      </div>
      <span class="brief-file-del" onclick="event.stopPropagation();briefingDelete('${f.name}')" title="Supprimer">✕</span>
    </div>`;
  }).join('');
}

function briefingOpen(name, ext) {
  _briefActive = name;
  // Mettre à jour sélection visuelle
  document.querySelectorAll('.brief-file-item').forEach(el => {
    el.classList.toggle('active', el.dataset.name === name);
  });
  const iframe = document.getElementById('briefIframe');
  const ph     = document.getElementById('briefPlaceholder');
  const url    = '/api/briefing/file/' + encodeURIComponent(name);
  iframe.src   = url;
  iframe.style.display = 'block';
  ph.style.display     = 'none';
}

async function briefingUpload(files) {
  if (!files || !files.length) return;
  const btn = document.querySelector('.brief-upload-btn');
  const origTxt = btn.innerHTML;
  btn.innerHTML = '⏳ ENVOI…';
  btn.style.pointerEvents = 'none';
  let lastFiles = [];
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch('/api/briefing/upload', {method:'POST', body:fd});
      const d = await r.json();
      if (d.files) lastFiles = d.files;
    } catch(e) { console.error('Upload erreur:', e); }
  }
  briefingRenderList(lastFiles);
  btn.innerHTML = origTxt;
  btn.style.pointerEvents = '';
  // Reset input
  document.getElementById('briefingFileInput').value = '';
}

async function briefingDelete(name) {
  if (!confirm('Supprimer "' + name + '" ?')) return;
  try {
    const r = await fetch('/api/briefing/delete/' + encodeURIComponent(name), {method:'DELETE'});
    const d = await r.json();
    if (_briefActive === name) {
      _briefActive = null;
      document.getElementById('briefIframe').style.display = 'none';
      document.getElementById('briefPlaceholder').style.display = 'flex';
    }
    briefingRenderList(d.files);
  } catch(e) { console.error('Delete erreur:', e); }
}

// ── Kneeboard subtabs ────────────────────────────────────────────
function switchKbTab(name, el) {
  document.querySelectorAll('.kb-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.kb-page').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  const page = document.getElementById('kb-' + name);
  if (page) page.classList.add('active');
}

// Persister kneeboard (notes, plan de vol, 9-line)
const _kbPersist = {
  'kb-notes-ta':'bms_kb_notes',
  'kb-fplan-ta':'bms_kb_fplan',
  'kb-callsign':'bms_kb_callsign','kb-package':'bms_kb_package',
  'kb-tot':'bms_kb_tot','kb-tanker':'bms_kb_tanker',
  'kb-bull-val':'bms_kb_bull','kb-bingo':'bms_kb_bingo',
  'kb-9l-1':'bms_9l_1','kb-9l-2':'bms_9l_2','kb-9l-3':'bms_9l_3',
  'kb-9l-4':'bms_9l_4','kb-9l-5':'bms_9l_5','kb-9l-6':'bms_9l_6',
  'kb-9l-7':'bms_9l_7','kb-9l-8':'bms_9l_8','kb-9l-9':'bms_9l_9',
};
Object.entries(_kbPersist).forEach(([id,key])=>{
  const el=document.getElementById(id);
  if(!el)return;
  try{el.value=localStorage.getItem(key)||'';}catch(e){}
  el.addEventListener('input',()=>{try{localStorage.setItem(key,el.value);}catch(e){}});
});
function clearNineLines(){
  for(let i=1;i<=9;i++){const el=document.getElementById('kb-9l-'+i);if(el){el.value='';try{localStorage.removeItem('bms_9l_'+i);}catch(e){}}}
}
function copyNineLines(){
  const lines=[];
  for(let i=1;i<=9;i++){const el=document.getElementById('kb-9l-'+i);if(el&&el.value)lines.push(i+'. '+el.value);}
  if(lines.length){try{navigator.clipboard.writeText(lines.join('\n'));}catch(e){}}
  showToast('9-LINE COPIÉ');
}

// ── GPS Panel data ───────────────────────────────────────────────
let _lastAircraftData = null;
let _activeSteerIdx = 0;

function fmtLL(v, isLon) {
  if (v === undefined || v === null) return '—';
  const dir = isLon ? (v >= 0 ? 'E' : 'W') : (v >= 0 ? 'N' : 'S');
  const abs = Math.abs(v);
  const deg = Math.floor(abs);
  const min = ((abs - deg) * 60).toFixed(3);
  return `${dir} ${String(deg).padStart(isLon?3:2,'0')}° ${min}'`;
}

function haversineNm(lat1, lon1, lat2, lon2) {
  const R = 3440.065; // NM
  const φ1 = lat1*Math.PI/180, φ2 = lat2*Math.PI/180;
  const dφ = (lat2-lat1)*Math.PI/180;
  const dλ = (lon2-lon1)*Math.PI/180;
  const a = Math.sin(dφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(dλ/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

function bearingTo(lat1, lon1, lat2, lon2) {
  const φ1 = lat1*Math.PI/180, φ2 = lat2*Math.PI/180;
  const dλ = (lon2-lon1)*Math.PI/180;
  const y = Math.sin(dλ)*Math.cos(φ2);
  const x = Math.cos(φ1)*Math.sin(φ2) - Math.sin(φ1)*Math.cos(φ2)*Math.cos(dλ);
  return ((Math.atan2(y,x)*180/Math.PI) + 360) % 360;
}

function refreshGpsPanel() {
  const d = _lastAircraftData;
  if (!d) return;
  document.getElementById('gps-lat').textContent  = fmtLL(d.lat, false);
  document.getElementById('gps-lon').textContent  = fmtLL(d.lon, true);
  document.getElementById('gps-hdg').textContent  = d.heading  != null ? String(Math.round(d.heading)).padStart(3,'0') + '°' : '—';
  document.getElementById('gps-alt').textContent  = d.altitude != null ? 'FL' + String(Math.round(Math.abs(d.altitude)/100)).padStart(3,'0') : '—';
  document.getElementById('gps-kias').textContent = d.kias     != null && d.kias > 5 ? Math.round(d.kias) + ' kt' : '—';

  // Distance au steerpoint actif
  let distText = '—';
  const steerChips = document.querySelectorAll('.steer-chip');
  if (steerChips.length && _lastMissionRoute && _lastMissionRoute[_activeSteerIdx]) {
    const sp = _lastMissionRoute[_activeSteerIdx];
    const nm = haversineNm(d.lat, d.lon, sp.lat, sp.lon);
    const brg = bearingTo(d.lat, d.lon, sp.lat, sp.lon);
    distText = String(Math.round(brg)).padStart(3,'0') + '° / ' + nm.toFixed(1) + ' NM';
  }
  document.getElementById('gps-dist').textContent = distText;

  // Bullseye bearing/distance
  const bullEl = document.getElementById('gps-bull');
  if (bullEl) {
    if (_bullLat != null && _bullLon != null && d.lat && d.lon) {
      const bBrg = bearingTo(d.lat, d.lon, _bullLat, _bullLon);
      const bNm  = haversineNm(d.lat, d.lon, _bullLat, _bullLon);
      bullEl.textContent = String(Math.round(bBrg)).padStart(3,'0') + '° / ' + bNm.toFixed(1) + ' NM';
    } else {
      bullEl.textContent = '—';
    }
  }
}

let _lastMissionRoute = [];
function buildGpsSteers(route) {
  _lastMissionRoute = route;
  const list = document.getElementById('gps-steer-list');
  const count = document.getElementById('gps-steer-count');
  list.innerHTML = '';
  if (!route || !route.length) {
    list.innerHTML = '<span style="font-family:system-ui,sans-serif;font-size:11px;color:#3d6b52;padding:4px 0">Aucun plan de vol chargé</span>';
    count.textContent = '0 WPT';
    return;
  }
  count.textContent = route.length + ' WPT';
  route.forEach((sp, i) => {
    const chip = document.createElement('div');
    chip.className = 'steer-chip' + (i === _activeSteerIdx ? ' active' : '');
    chip.innerHTML = `<span class="steer-num">STPT ${i+1}</span>
      <span class="steer-fl">FL${String(Math.round(Math.abs(sp.alt)/100)).padStart(3,'0')}</span>`;
    chip.onclick = () => {
      _activeSteerIdx = i;
      document.querySelectorAll('.steer-chip').forEach((c,j) => c.classList.toggle('active', j===i));
      refreshGpsPanel();
    };
    list.appendChild(chip);
  });
}

// Hook into existing updateAircraft and loadMission
const _origUpdateAircraft = updateAircraft;
window.updateAircraft = function(d) {
  _origUpdateAircraft(d);
  _lastAircraftData = d;
  if (_activeTab === 'gps') refreshGpsPanel();
};

const _origLoadMission = loadMission;
window.loadMission = function() {
  _origLoadMission();
  // Rebuild steerpoints after data loads
  setTimeout(() => {
    fetch('/api/mission').then(r=>r.json()).then(md => {
      const route = md.route && md.route.length ? md.route : (md.flightplan || []);
      buildGpsSteers(route);
    });
  }, 300);
};

// Close panels when clicking on map
map.on('click', () => {
  if (_activeTab && _activeTab !== 'gps') {
    // Ne ferme pas sur clic map pour GPS (utile en vol)
    PANELS[_activeTab].classList.remove('open');
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    _activeTab = null;
  }
});
</script>
</body></html>
"""

# ══════════════════════════════════════════════════════════════════
#  SETTINGS API
# ══════════════════════════════════════════════════════════════════
class SettingsModel(BaseModel):
    port:         Optional[int] = None
    briefing_dir: Optional[str] = None
    broadcast_ms: Optional[int] = None
    theme:        Optional[str] = None

@app.get("/api/settings")
async def settings_get():
    return {**APP_CONFIG, "current_port": SERVER_PORT, "current_ip": SERVER_IP}

@app.post("/api/settings")
async def settings_save(s: SettingsModel):
    global APP_CONFIG, BRIEFING_DIR
    changed: list = []
    if s.port is not None and 1024 <= s.port <= 65535:
        APP_CONFIG["port"] = s.port; changed.append("port")
    if s.briefing_dir is not None and s.briefing_dir.strip():
        nd = s.briefing_dir.strip()
        try:
            os.makedirs(nd, exist_ok=True)
            APP_CONFIG["briefing_dir"] = nd; BRIEFING_DIR = nd; changed.append("briefing_dir")
        except Exception as e:
            raise HTTPException(400, f"Dossier invalide: {e}")
    if s.broadcast_ms is not None and 50 <= s.broadcast_ms <= 2000:
        APP_CONFIG["broadcast_ms"] = s.broadcast_ms; changed.append("broadcast_ms")
    if s.theme is not None and s.theme in ("dark", "light"):
        APP_CONFIG["theme"] = s.theme; changed.append("theme")
    _save_config(APP_CONFIG)
    needs_restart = "port" in changed
    logger.info(f"Settings: {changed}" + (" — RESTART requis (port)" if needs_restart else ""))
    return {"ok": True, "changed": changed, "needs_restart": needs_restart, "config": APP_CONFIG}

@app.get("/api/server/info")
async def server_info():
    return {"ip": SERVER_IP, "port": SERVER_PORT, "url": f"http://{SERVER_IP}:{SERVER_PORT}"}

@app.get("/api/acmi/status")
async def acmi_status():
    """Statut du client TRTT et contacts en cours."""
    with _acmi_lock:
        nb = len(_acmi_contacts)
        sample = list(_acmi_contacts.values())[:5]
    return {
        "trtt_host": f"{TRTT_HOST}:{TRTT_PORT}",
        "connected": _acmi_connected,
        "thread_alive": _acmi_thread.is_alive() if _acmi_thread else False,
        "nb_contacts": nb,
        "sample": [{k:v for k,v in c.items() if k != '_ts'} for c in sample],
        "config_bms": "set g_bTacviewRealTime 1  (dans User/config/Falcon BMS User.cfg)"
    }

# ══════════════════════════════════════════════════════════════════
#  BRIEFING API
# ══════════════════════════════════════════════════════════════════

BRIEFING_ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".docx"}
BRIEFING_MAX_MB  = 50

def _briefing_meta() -> list:
    """Retourne la liste des fichiers briefing avec métadonnées."""
    files = []
    for fn in sorted(os.listdir(BRIEFING_DIR)):
        ext = os.path.splitext(fn)[1].lower()
        if ext not in BRIEFING_ALLOWED:
            continue
        fp = os.path.join(BRIEFING_DIR, fn)
        stat = os.stat(fp)
        files.append({
            "name":     fn,
            "ext":      ext.lstrip("."),
            "size_kb":  round(stat.st_size / 1024, 1),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m %H:%M"),
        })
    return files

@app.get("/api/briefing/list")
async def briefing_list():
    return {"files": _briefing_meta()}

@app.post("/api/briefing/upload")
async def briefing_upload(file: UploadFile = File(...)):
    filename: str = file.filename or "unnamed"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in BRIEFING_ALLOWED:
        raise HTTPException(400, f"Type non supporté: {ext}. Acceptés: {', '.join(BRIEFING_ALLOWED)}")
    data = await file.read()
    if len(data) > BRIEFING_MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"Fichier trop lourd (max {BRIEFING_MAX_MB} MB)")
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
    dest = os.path.join(BRIEFING_DIR, safe_name)
    with open(dest, "wb") as f:
        f.write(data)
    logger.info(f"Briefing uploadé: {safe_name} ({len(data)//1024} KB)")
    return {"ok": True, "name": safe_name, "files": _briefing_meta()}

@app.delete("/api/briefing/delete/{filename}")
async def briefing_delete(filename: str):
    safe = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
    fp = os.path.join(BRIEFING_DIR, safe)
    if not os.path.exists(fp):
        raise HTTPException(404, "Fichier introuvable")
    os.remove(fp)
    logger.info(f"Briefing supprimé: {safe}")
    return {"ok": True, "files": _briefing_meta()}

@app.get("/api/briefing/file/{filename}")
async def briefing_serve(filename: str):
    """Sert le fichier brut (PDF, image). Le .docx est converti en HTML."""
    safe = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
    fp = os.path.join(BRIEFING_DIR, safe)
    if not os.path.exists(fp):
        raise HTTPException(404, "Fichier introuvable")
    ext = os.path.splitext(safe)[1].lower()
    if ext == ".docx":
        return await _docx_to_html_response(fp)
    mime = {".pdf":"application/pdf", ".png":"image/png",
            ".jpg":"image/jpeg", ".jpeg":"image/jpeg"}.get(ext, "application/octet-stream")
    return FileResponse(fp, media_type=mime, headers={"Content-Disposition": "inline"})

async def _docx_to_html_response(fp: str):
    """Convertit un .docx en page HTML tactique."""
    try:
        from docx import Document as _DocxDoc  # type: ignore[import-untyped]
        doc = _DocxDoc(fp)
        paras = []
        for p in doc.paragraphs:
            if not p.text.strip():
                paras.append("<br>")
                continue
            style = (p.style.name.lower() if p.style and p.style.name else "")
            if "heading 1" in style:
                paras.append(f"<h1>{p.text}</h1>")
            elif "heading 2" in style:
                paras.append(f"<h2>{p.text}</h2>")
            elif "heading 3" in style:
                paras.append(f"<h3>{p.text}</h3>")
            else:
                runs_html = ""
                for r in p.runs:
                    t = r.text.replace("&","&amp;").replace("<","&lt;")
                    if r.bold:   t = f"<strong>{t}</strong>"
                    if r.italic: t = f"<em>{t}</em>"
                    runs_html += t
                paras.append(f"<p>{runs_html}</p>")
        body = "\n".join(paras)
        html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
  body{{background:#060a12;color:#cbd5e1;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
    max-width:860px;margin:0 auto;padding:32px 24px;font-size:15px;line-height:1.7}}
  h1{{font-size:22px;color:#fbbf24;letter-spacing:2px;text-transform:uppercase;
    border-bottom:1px solid rgba(251,191,36,.2);padding-bottom:8px;margin:24px 0 12px}}
  h2{{font-size:16px;color:#94a3b8;letter-spacing:1.5px;text-transform:uppercase;margin:20px 0 8px}}
  h3{{font-size:13px;color:#4ade80;letter-spacing:1px;text-transform:uppercase;margin:16px 0 6px}}
  p{{margin:4px 0;color:#94a3b8}} strong{{color:#e2e8f0}} em{{color:#fbbf24}}
  br{{display:block;margin:4px 0}}
</style></head><body>{body}</body></html>"""
        from fastapi.responses import HTMLResponse as _HR
        return _HR(content=html)
    except ImportError:
        from fastapi.responses import HTMLResponse as _HR
        return _HR(content="<html><body style='background:#060a12;color:#ef4444;font-family:monospace;padding:40px'>"
                   "<h2>⚠ python-docx non installé</h2>"
                   "<p>Installer avec: <code>pip install python-docx</code></p></body></html>", status_code=500)
    except Exception as e:
        from fastapi.responses import HTMLResponse as _HR
        return _HR(content=f"<html><body style='background:#060a12;color:#ef4444;padding:40px;font-family:monospace'>"
                   f"<h2>Erreur conversion DOCX</h2><pre>{e}</pre></body></html>", status_code=500)

@app.get("/")
async def index(): return HTMLResponse(content=HTML)

if __name__ == "__main__":
    import threading as _th_main

    def _run_server():
        uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="warning")

    _srv_thread = _th_main.Thread(target=_run_server, daemon=True)
    _srv_thread.start()

    try:
        from PySide6.QtWidgets import QApplication, QWidget  # type: ignore[import-untyped]
        from PySide6.QtCore    import Qt, QTimer             # type: ignore[import-untyped]
        from PySide6.QtGui     import (QPainter, QColor, QPen, QFont,  # type: ignore[import-untyped]
                                       QPixmap, QIcon, QBrush)
    except ImportError:
        logger.error("PySide6 absent — pip install PySide6")
        _srv_thread.join()
        raise SystemExit(0)

    class FalconPadWindow(QWidget):
        W, H = 420, 350
        BG         = QColor("#060a12")
        BG2        = QColor("#0b1220")
        ACCENT     = QColor("#4ade80")
        ACCENT_DIM = QColor("#1f4d35")
        RED        = QColor("#ef4444")
        RED_DIM    = QColor("#1a0808")
        RED_HOV    = QColor("#3d1010")
        RED_OUT    = QColor("#7f2222")
        BLUE       = QColor("#60a5fa")
        TXT_DIM    = QColor("#64748b")
        TXT_MID    = QColor("#94a3b8")

        def __init__(self):
            super().__init__()
            self.setFixedSize(self.W, self.H)
            # Window + Frameless = barre des tâches OK + showMinimized() OK
            self.setWindowFlags(
                Qt.WindowType.Window |
                Qt.WindowType.FramelessWindowHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.setWindowTitle("Falcon-Pad")
            _ico = os.path.join(ASSETS_DIR, "falcon_pad.ico")
            if os.path.exists(_ico):
                self.setWindowIcon(QIcon(_ico))
            screen = QApplication.primaryScreen().availableGeometry()
            self.move((screen.width()-self.W)//2, (screen.height()-self.H)//2)
            self._logo = None
            _lp = os.path.join(ASSETS_DIR, "logo_tk.png")
            if os.path.exists(_lp):
                px = QPixmap(_lp)
                if not px.isNull():
                    self._logo = px.scaled(64,64,Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
            self._drag_pos  = None
            self._btn_hover = False
            self._min_hover = False
            self._btn_rect  = None
            self._min_rect  = None
            self._bms_ok    = False
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._poll_bms)
            self._timer.start(3000)
            QTimer.singleShot(600, self._poll_bms)
            self.setMouseTracking(True)
            self.show()

        def _poll_bms(self):
            try:
                ok = bms.connected or bms.try_reconnect()
                if ok != self._bms_ok:
                    self._bms_ok = ok
                    self.update()
            except Exception:
                pass

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            W, H = self.W, self.H
            p.fillRect(0, 0, W, H, self.BG)
            p.fillRect(0, 0, W, 80, self.BG2)
            p.fillRect(0, 0, W, 3, self.ACCENT)
            p.setPen(QPen(self.ACCENT_DIM, 1))
            p.drawRect(0, 0, W-1, H-1)
            p.drawLine(20, 80, W-20, 80)
            p.drawLine(20, H-66, W-20, H-66)
            # Bouton réduire
            rx,ry,rw,rh = W-36,10,24,18
            self._min_rect=(rx,ry,rw,rh)
            mc = self.TXT_MID if self._min_hover else self.TXT_DIM
            p.setPen(QPen(mc,1)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rx,ry,rw,rh)
            p.setPen(QPen(mc,2))
            p.drawLine(rx+5, ry+rh//2, rx+rw-5, ry+rh//2)
            # Logo + titre
            tx = 20
            if self._logo:
                p.drawPixmap(12, 8, self._logo); tx = 88
            p.setPen(QPen(self.ACCENT))
            p.setFont(QFont("Consolas",15,QFont.Weight.Bold))
            p.drawText(tx,8,W-tx-44,40,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,"FALCON-PAD")
            p.setPen(QPen(self.TXT_DIM))
            p.setFont(QFont("Consolas",8))
            p.drawText(tx,48,W-tx-44,20,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,
                       f"v{APP_VERSION}  ·  by {APP_AUTHOR}")
            # URLs
            y=96
            p.setFont(QFont("Consolas",7,QFont.Weight.Bold)); p.setPen(QPen(self.TXT_DIM))
            p.drawText(22,y,"LOCAL"); y+=17
            p.setFont(QFont("Consolas",11)); p.setPen(QPen(self.ACCENT))
            p.drawText(22,y,f"http://localhost:{SERVER_PORT}"); y+=25
            p.setFont(QFont("Consolas",7,QFont.Weight.Bold)); p.setPen(QPen(self.TXT_DIM))
            p.drawText(22,y,"RÉSEAU  —  Tablette / Mobile"); y+=17
            p.setFont(QFont("Consolas",11)); p.setPen(QPen(self.BLUE))
            p.drawText(22,y,f"http://{SERVER_IP}:{SERVER_PORT}"); y+=25
            # BMS
            p.setFont(QFont("Consolas",7,QFont.Weight.Bold)); p.setPen(QPen(self.TXT_DIM))
            p.drawText(22,y,"FALCON BMS 4.38"); y+=17
            dc = self.ACCENT if self._bms_ok else self.RED
            p.setBrush(QBrush(dc)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(22,y-9,10,10)
            p.setPen(QPen(dc))
            p.setFont(QFont("Consolas",10,QFont.Weight.Bold))
            p.drawText(38,y,"CONNECTÉ" if self._bms_ok else "NON DÉTECTÉ"); y+=25
            # Logs
            p.setPen(QPen(self.TXT_DIM))
            p.setFont(QFont("Consolas",7,QFont.Weight.Bold))
            p.drawText(22,y,"LOGS"); y+=15
            ls = LOG_DIR if len(LOG_DIR)<=54 else "…"+LOG_DIR[-52:]
            p.setFont(QFont("Consolas",8)); p.drawText(22,y,ls)
            # Bouton ARRÊT
            bx,by_,bw_,bh_ = W//2-72,H-52,144,28
            self._btn_rect=(bx,by_,bw_,bh_)
            p.setBrush(QBrush(self.RED_HOV if self._btn_hover else self.RED_DIM))
            p.setPen(QPen(self.RED if self._btn_hover else self.RED_OUT,1))
            p.drawRect(bx,by_,bw_,bh_)
            p.setPen(QPen(self.RED))
            p.setFont(QFont("Consolas",11,QFont.Weight.Bold))
            p.drawText(bx,by_,bw_,bh_,Qt.AlignmentFlag.AlignCenter,"■  ARRÊT")
            p.setPen(QPen(self.TXT_DIM)); p.setFont(QFont("Consolas",7))
            p.drawText(0,H-13,W,12,Qt.AlignmentFlag.AlignCenter,"Le serveur sera arrêté")
            p.end()

        def mousePressEvent(self, e):
            if e.button() != Qt.MouseButton.LeftButton: return
            mx,my = e.position().x(), e.position().y()
            if self._btn_rect:
                bx,by_,bw_,bh_ = self._btn_rect
                if bx<=mx<=bx+bw_ and by_<=my<=by_+bh_:
                    self._do_quit(); return
            if self._min_rect:
                rx,ry,rw,rh = self._min_rect
                if rx<=mx<=rx+rw and ry<=my<=ry+rh:
                    self.showMinimized(); return
            if my < 80:
                self._drag_pos = e.globalPosition().toPoint()

        def mouseMoveEvent(self, e):
            if self._drag_pos and e.buttons()==Qt.MouseButton.LeftButton:
                delta = e.globalPosition().toPoint()-self._drag_pos
                self.move(self.pos()+delta)
                self._drag_pos = e.globalPosition().toPoint()
            mx,my = e.position().x(), e.position().y()
            if self._btn_rect:
                bx,by_,bw_,bh_ = self._btn_rect
                h = bx<=mx<=bx+bw_ and by_<=my<=by_+bh_
                if h!=self._btn_hover: self._btn_hover=h; self.update()
            if self._min_rect:
                rx,ry,rw,rh = self._min_rect
                h2 = rx<=mx<=rx+rw and ry<=my<=ry+rh
                if h2!=self._min_hover: self._min_hover=h2; self.update()

        def mouseReleaseEvent(self, _e): self._drag_pos = None

        def leaveEvent(self, _e):
            if self._btn_hover or self._min_hover:
                self._btn_hover=False; self._min_hover=False; self.update()

        def keyPressEvent(self, e):
            if e.key()==Qt.Key.Key_F4 and e.modifiers()==Qt.KeyboardModifier.AltModifier:
                self._do_quit()

        def _do_quit(self):
            self._timer.stop(); self.close()
            os.kill(os.getpid(), 9)

    _app = QApplication(sys.argv)
    _app.setApplicationName("Falcon-Pad")
    _app.setApplicationVersion(APP_VERSION)
    _win = FalconPadWindow()
    _app.exec()

