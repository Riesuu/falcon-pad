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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
import uvicorn, asyncio, json, ctypes, configparser, math, struct, os, sys, shutil
from datetime import datetime
from typing import List, Optional, Dict
import logging

APP_NAME    = "Falcon-Pad"
APP_VERSION = "0.2"
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
_fh.setLevel(logging.DEBUG)
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_fh.setFormatter(_Fmt()); _ch.setFormatter(_Fmt())
logging.basicConfig(level=logging.DEBUG, handlers=[_fh, _ch])
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
PYPROJ_AVAILABLE = False

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
                                    except: pass
                                elif k == 'ReferenceLatitude':
                                    try: ref_lat = float(v)
                                    except: pass
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

                        # Mémoriser propriétés permanentes
                        if obj_id not in obj_props:
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

                        # Filtrer: on veut uniquement l'air (pas weapons, navaid, sol)
                        at = p.get('acmi_type', 'other')
                        if at in ('weapon', 'navaid', 'other'):
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
                    except Exception as ex:
                        logger.debug(f"TRTT parse: {ex} ({line[:80]!r})")

        except Exception as ex:
            _acmi_connected = False
            with _acmi_lock:
                _acmi_contacts.clear()
            logger.debug(f"TRTT déconnecté: {ex} — retry dans 5s")
            try:
                if sock is not None:
                    sock.close()
            except: pass
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

def get_acmi_contacts(own_lat=None, own_lon=None) -> list:
    now = _time.time()
    with _acmi_lock:
        contacts = list(_acmi_contacts.items())
    result = []
    for obj_id, c in contacts:
        # Ignorer stale (>30s sans update — objet détruit)
        if now - c.get('_ts', 0) > 30.0:
            continue
        if own_lat and own_lon:
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
        logger.info(f"SafeMemReader OK — hproc={_hproc}")
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
                        logger.info(f"  SHM {name} = 0x{p:X}")
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
                logger.debug("BMS non détecté — retry dans 5s")
        except Exception as e:
            self.shm_ptrs = {}
            self.ptr1 = self.ptr2 = None
            self.connected = False
            logger.error(f"Shared Memory error: {e}", exc_info=True)

    def try_reconnect(self):
        if not self.connected:
            self._connect()
            if self.connected:
                global _DD_CANDIDATES
                _DD_CANDIDATES = None  # forcer re-scan DrawingData
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
        # Assertions de type — Pylance ne narrowe pas via "None in tuple"
        assert hdg  is not None
        assert kias is not None
        assert z    is not None
        assert lat  is not None
        assert lon  is not None
        hdg_f  = float(hdg)
        kias_f = float(kias)
        z_f    = float(z)
        lat_f  = float(lat)
        lon_f  = float(lon)
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

        logger.debug(f"lat={lat_f:.4f} lon={lon_f:.4f} hdg={hdg_f:.1f} alt={alt:.0f}ft kias={kias_f:.0f}kt bms_t={bms_time} bull=({bull_lat},{bull_lon})")
        if -90 <= lat_f <= 90 and -180 <= lon_f <= 180 and not (lat_f == 0.0 and lon_f == 0.0):
            return {"lat": lat_f, "lon": lon_f, "heading": round(hdg_f, 1),
                    "altitude": round(alt), "kias": round(kias_f),
                    "bms_time": bms_time,
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
    start_acmi_reader()
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

# ── Frontend statique ─────────────────────────────────────────────
FRONTEND_DIR = os.path.join(app_info.BASE_DIR, "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    logger.info(f"StaticFiles monté : {FRONTEND_DIR}")
else:
    logger.warning(f"Dossier frontend introuvable : {FRONTEND_DIR}")

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
ws_clients: List[WebSocket] = []
mission_data = {"route": [], "threats": [], "flightplan": []}

# ── DrawingData constants (BMS 4.38 — FalconSharedMemoryArea) ───
DRAWING_ENTITY_SIZE: int = 40   # bytes per OSBEntity
DRAWING_ENTITY_MAX:  int = 150  # max entities in DrawingData array

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
                    except: dead.append(ws)
                for ws in dead:
                    if ws in ws_clients: ws_clients.remove(ws)

                # 2. Contacts radar/datalink BMS (DrawingData — no god mode)
                own_lat = pos.get("lat"); own_lon = pos.get("lon")
                radar_c = get_radar_contacts(
                    bms.ptr1, own_lat=own_lat, own_lon=own_lon,
                    ptr2=bms.ptr2 if bms.ptr2 else 0
                ) if bms.ptr1 else []
                msg_r = json.dumps({"type": "radar", "data": radar_c})
                for ws in list(ws_clients):
                    try:    await ws.send_text(msg_r)
                    except: pass

                # 3. Contacts ACMI/TRTT coalition
                acmi_c = get_acmi_contacts(own_lat=own_lat, own_lon=own_lon)
                if acmi_c:
                    msg_acmi = json.dumps({"type": "acmi", "data": acmi_c})
                    for ws in list(ws_clients):
                        try:    await ws.send_text(msg_acmi)
                        except: pass

            # 4. Statut connexion
            if ws_clients:
                status_msg = json.dumps({"type": "status", "data": {"connected": bms.connected}})
                for ws in list(ws_clients):
                    try:    await ws.send_text(status_msg)
                    except: pass

        except Exception as e:
            logger.debug(f"broadcast_loop: {e}")
        await asyncio.sleep(APP_CONFIG.get("broadcast_ms", 200) / 1000.0)


#  RADAR — OSBEntity (FalconSharedMemoryArea, BMS 4.38)
#  Offset 0x0C78 · 40 bytes/entité · max 150
import math as _math

_ENT_NAMES={1:"F-16",2:"F-15",3:"F/A-18",4:"A-10",5:"F-117",
            6:"MiG-29",7:"Su-27",8:"MiG-21",9:"MiG-23",10:"Su-25",
            20:"SA-2",21:"SA-3",22:"SA-6",23:"SA-8",24:"SA-10",25:"SA-11",30:"Helo",40:"Transport"}

def _find_drawing_data_base(ptr1: int, ptr2: int) -> tuple:
    """Cherche l'offset DrawingData dans toutes les zones SHM connues."""
    candidates = []
    # Toutes les zones ouvertes par BMS
    for name, ptr in bms.shm_ptrs.items():
        if not ptr: continue
        for off in [0x000, 0x100, 0x200, 0x300, 0x400, 0x500,
                    0x600, 0x700, 0x800, 0x900, 0xA00, 0xB00,
                    0xC00, 0xD00, 0xE00, 0xF00,
                    0x1000, 0x1200, 0x1500, 0x1800, 0x1E00,
                    0x2000, 0x2400, 0x2800, 0x2BD0]:
            candidates.append((ptr, off, f"{name}+0x{off:X}"))
    # Fallback ptr1/ptr2
    for ptr, off, lbl in [(ptr1, 0x2BD0, "ptr1+0x2BD0"), (ptr2, 0x000, "ptr2+0x000"),
                          (ptr2, 0x100, "ptr2+0x100"), (ptr2, 0x200, "ptr2+0x200")]:
        if ptr and (ptr, off, lbl) not in candidates:
            candidates.append((ptr, off, lbl))
    for base, off, label in candidates:
        if not base: continue
        b = safe_read(base + off, 4)
        if b is None: 
            logger.debug(f"  scan {label}: inaccessible")
            continue
        nb = struct.unpack('<i', b)[0]
        if 1 <= nb <= 50:  # nb entités plausible: entre 1 et 50
            # Vérifier que les coordonnées de la 1ère entité sont en Corée
            blob = safe_read(base + off + 4, 8)
            if blob:
                lr, lo = struct.unpack('<ff', blob)
                import math as _m
                if 0.4 < abs(lr) < 1.0 and 2.0 < abs(lo) < 2.5:
                    logger.info(f"DrawingData TROUVE: {label} nb={nb} lat={_m.degrees(lr):.2f} lon={_m.degrees(lo):.2f}")
                    return base, off
                else:
                    logger.debug(f"  scan {label}: nb={nb} mais coords hors Corée ({lr:.3f},{lo:.3f})")
            logger.debug(f"  scan {label}: nb={nb} mais blob illisible")
        else:
            logger.debug(f"  scan {label}: nb={nb} invalide")
    return None, None

def get_radar_contacts(ptr1: int, own_lat=None, own_lon=None, ptr2: int = 0) -> list:
    """Lit DrawingData via safe_read — cherche l'offset automatiquement."""
    global _DD_CANDIDATES
    if not ptr1: return []
    # Détermination automatique de l'offset au premier appel
    if _DD_CANDIDATES is None:
        logger.info("Scan DrawingData en cours...")
        found_base, found_off = _find_drawing_data_base(ptr1, ptr2)
        if found_base:
            _DD_CANDIDATES = (found_base, found_off)
            logger.info(f"DrawingData lock: base={hex(found_base)} off=0x{found_off:X}")
        else:
            _DD_CANDIDATES = False
            logger.warning("DrawingData: offset introuvable par scan — datalink désactivé")
    if not _DD_CANDIDATES:
        return []
    dd_base, dd_off = _DD_CANDIDATES
    b = safe_read(dd_base + dd_off, 4)
    if b is None:
        logger.warning(f"DrawingData nb inaccessible @ 0x{dd_base+dd_off:X} — reset scan")
        _DD_CANDIDATES = None
        return []
    nb_raw = struct.unpack('<i', b)[0]
    logger.debug(f"DrawingData nb_raw={nb_raw}")
    if nb_raw <= 0 or nb_raw > DRAWING_ENTITY_MAX: return []
    blob = safe_read(dd_base + dd_off + 4, nb_raw * DRAWING_ENTITY_SIZE)
    if blob is None:
        logger.warning("DrawingData blob: lecture impossible")
        return []
    assert isinstance(blob, (bytes, bytearray))  # narrow type for static analysis
    res: list = []
    for i in range(nb_raw):
        try:
            off = i * DRAWING_ENTITY_SIZE
            lat_r, lon_r, z, et, ca, hr, sp = struct.unpack_from('<fffiiif', blob, off)
            lb = blob[off+32:off+40].split(b'\x00')[0].decode('ascii', errors='replace').strip()
            if lat_r == 0.0 and lon_r == 0.0: continue
            if not 1 <= ca <= 4: continue
            lat = _math.degrees(lat_r); lon = _math.degrees(lon_r)
            if not (25 <= lat <= 50 and 110 <= lon <= 145): continue
            if own_lat and own_lon and abs(lat-own_lat)<0.002 and abs(lon-own_lon)<0.002: continue
            res.append({"lat": round(lat,5), "lon": round(lon,5),
                        "alt": round(abs(z)/100)*100, "camp": int(ca),
                        "type_name": _ENT_NAMES.get(int(et), f"T{et}"),
                        "callsign": lb,
                        "heading": round(_math.degrees(hr)%360, 1),
                        "speed": round(sp)})
        except Exception as ex:
            logger.debug(f"DrawingData[{i}]: {ex}")
    logger.debug(f"DrawingData: {len(res)}/{nb_raw} contacts valides")
    return res


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        await websocket.send_text(json.dumps({"type":"status","data":{"connected": bms.connected}}))
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in ws_clients: ws_clients.remove(websocket)


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
        content = (await file.read()).decode("latin-1")
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
                    except: pass
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
        except: pass
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
                    except: pass
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
    while True:
        try:
            path, mtime = _find_latest_ini()
            if path and (path != _ini_last_path or mtime > _ini_last_mtime + 1):
                _ini_last_path = path
                _ini_last_mtime = mtime
                _parse_ini_file(path)
        except Exception as e:
            logger.debug(f"INI watcher: {e}")
        await asyncio.sleep(3)  # vérifier toutes les 3s


#  HTML / CSS / JS

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
async def index():
    idx = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx, media_type="text/html")
    logger.error(f"index.html introuvable : {idx}")
    return HTMLResponse("<h1>Falcon-Pad — frontend/index.html manquant</h1>", status_code=500)

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

