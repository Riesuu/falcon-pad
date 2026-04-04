# -*- coding: utf-8 -*-
"""
falcon_pad.trtt — Tacview Real-Time Telemetry (TRTT) client for BMS 4.38.

Connects to BMS TRTT (TCP port 42674) and maintains a live dictionary of
ACMI contacts.  Runs in a background daemon thread.

BMS config required:
    set g_bTacviewRealTime 1
    set g_bTacviewRealTimeHost 1

Public API:
    start()                   — launch background thread
    stop()                    — request shutdown
    is_connected()            — True if TCP link is active
    get_contacts(...)         — filtered contact list for broadcast
    get_diagnostics()         — dict for /api/acmi/status + diag logging

Copyright (C) 2024  Riesu — GNU GPL v3
"""

from __future__ import annotations

import logging
import math
import socket
import threading
import time
from typing import Dict, List, Optional, Tuple

from theaters import in_theater_bbox

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

import app_info

HOST:        str = app_info.TRTT_HOST
PORT:        int = app_info.TRTT_PORT
CLIENT_NAME: str = f"{app_info.NAME}-{app_info.AUTHOR}"

# ═══════════════════════════════════════════════════════════════════════════
#  INTERNAL STATE
# ═══════════════════════════════════════════════════════════════════════════

_contacts: Dict[str, dict] = {}
_lock      = threading.Lock()
_thread:  Optional[threading.Thread] = None
_running:  bool = False
_connected: bool = False


# ═══════════════════════════════════════════════════════════════════════════
#  ACMI PARSERS
# ═══════════════════════════════════════════════════════════════════════════

def _parse_color(color_str: str) -> int:
    """Color field → camp integer: 1=blue/friendly, 2=red/enemy, 3=unknown."""
    c = color_str.lower()
    if 'blue' in c:  return 1
    if 'red' in c:   return 2
    return 3


def _parse_type(type_str: str) -> str:
    """Type field → simplified category string."""
    t = type_str.lower()
    if 'fixedwing' in t or 'rotorcraft' in t: return 'air'
    if 'ground' in t:  return 'ground'
    if 'weapon' in t or 'missile' in t or 'projectile' in t: return 'weapon'
    if 'sea' in t or 'ship' in t: return 'sea'
    if 'navaid' in t or 'bullseye' in t: return 'navaid'
    return 'other'


def _parse_props(rest: str) -> Dict[str, str]:
    """Parse comma-separated key=value pairs (handles escaped commas)."""
    props: Dict[str, str] = {}
    i = start_i = 0
    while i <= len(rest):
        if i == len(rest) or (rest[i] == ',' and (i == 0 or rest[i - 1] != '\\')):
            part = rest[start_i:i]
            if '=' in part:
                k, v = part.split('=', 1)
                props[k.strip()] = v.strip()
            start_i = i + 1
        i += 1
    return props


# ═══════════════════════════════════════════════════════════════════════════
#  TCP CLIENT LOOP (runs in background thread)
# ═══════════════════════════════════════════════════════════════════════════

def _client_loop() -> None:
    global _running, _connected

    obj_props: Dict[str, dict] = {}
    ref_lon = ref_lat = 0.0
    buf = ""
    sock: Optional[socket.socket] = None

    while _running:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(app_info.TRTT_HANDSHAKE_TIMEOUT)
            logger.debug(f"TRTT: connecting to {HOST}:{PORT}...")
            sock.connect((HOST, PORT))
            sock.settimeout(app_info.TRTT_INITIAL_TIMEOUT)

            # ── Handshake ────────────────────────────────────────
            hs = b""
            while b"\x00" not in hs:
                chunk = sock.recv(256)
                if not chunk:
                    raise ConnectionError("Handshake host incomplete")
                hs += chunk

            client_hs = (
                "XtraLib.Stream.0\n"
                "Tacview.RealTimeTelemetry.0\n"
                f"{CLIENT_NAME}\n"
                "0\x00"
            ).encode('utf-8')
            sock.sendall(client_hs)
            _connected = True
            sock.settimeout(app_info.TRTT_RECEIVE_TIMEOUT)
            buf = ""
            obj_props = {}
            ref_lon = ref_lat = 0.0

            # ── Stream ACMI ──────────────────────────────────────
            while _running:
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    logger.warning("TRTT: recv timeout — BMS still connected?")
                    continue
                if not data:
                    raise ConnectionError("BMS closed TRTT connection")
                buf += data.decode('utf-8', errors='replace')

                # Safety: cap buffer to prevent OOM
                if len(buf) > 2 * 1024 * 1024:
                    logger.warning("TRTT: buffer > 2MB, truncating")
                    nl = buf.rfind('\n')
                    buf = buf[nl + 1:] if nl >= 0 else ""

                # Process complete lines
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    line = line.strip()
                    if not line or line.startswith('//'):
                        continue
                    if line.startswith('FileType') or line.startswith('FileVersion'):
                        continue

                    # Global object (id=0): reference coords
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

                    # Deletion: -hexid
                    if line.startswith('-'):
                        obj_id = line[1:].strip()
                        with _lock:
                            _contacts.pop(obj_id, None)
                        obj_props.pop(obj_id, None)
                        continue

                    # Timestamp: #47.13
                    if line.startswith('#'):
                        continue

                    # Object update: hexid,prop=val,...
                    if ',' not in line:
                        continue

                    try:
                        obj_id, rest = line.split(',', 1)
                        obj_id = obj_id.strip()
                        if not obj_id or obj_id == '0':
                            continue

                        props = _parse_props(rest)

                        # Accumulate persistent properties (capped at 1000 objects)
                        if obj_id not in obj_props:
                            if len(obj_props) > 1000:
                                stale = [k for k in obj_props if k not in _contacts]
                                for k in stale[:200]:
                                    del obj_props[k]
                            obj_props[obj_id] = {
                                'name': '', 'color': 3, 'acmi_type': 'other', 'pilot': ''
                            }
                        p = obj_props[obj_id]

                        if 'Name'   in props: p['name']      = props['Name']
                        if 'Color'  in props: p['color']     = _parse_color(props['Color'])
                        # Coalition as fallback when Color absent
                        if 'Coalition' in props and p['color'] == 3:
                            co = props['Coalition'].lower()
                            if 'allies' in co:   p['color'] = 1
                            elif 'enemies' in co: p['color'] = 2
                        if 'Type'   in props: p['acmi_type'] = _parse_type(props['Type'])
                        if 'Pilot'  in props: p['pilot']     = props['Pilot']
                        if 'Group'  in props and not p['name']: p['name'] = props['Group']

                        # Filter: air only
                        at = p.get('acmi_type', 'other')
                        if at in ('weapon', 'navaid', 'ground', 'sea'):
                            continue
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

                        # Empty = no position change, just update timestamp
                        if not lon_s or not lat_s:
                            with _lock:
                                if obj_id in _contacts:
                                    _contacts[obj_id]['_ts'] = time.time()
                            continue

                        lon = float(lon_s) + ref_lon
                        lat = float(lat_s) + ref_lat
                        alt_m = float(alt_s) if alt_s else 0.0
                        hdg = float(yaw_s) % 360.0 if yaw_s else 0.0

                        # Theater-aware sanity check
                        if not in_theater_bbox(lat, lon):
                            continue

                        with _lock:
                            _contacts[obj_id] = {
                                'lat':       round(lat, 5),
                                'lon':       round(lon, 5),
                                'alt':       round(alt_m * app_info.M_TO_FT),   # m → ft
                                'camp':      p['color'],
                                'callsign':  p['name'] or p['pilot'] or obj_id,
                                'pilot':     p['pilot'],
                                'type_name': at,
                                'heading':   hdg,
                                'speed':     round(float(props['IAS']) * app_info.KT_PER_MS) if props.get('IAS') else 0,
                                '_ts':       time.time(),
                            }
                    except Exception as ex:
                        logger.debug(f"TRTT parse: {ex} ({line[:80]!r})")

        except Exception as ex:
            _connected = False
            with _lock:
                _contacts.clear()
            logger.debug(f"TRTT disconnected: {ex} — retry in {app_info.TRTT_RECONNECT_SLEEP}s")
            try:
                if sock is not None:
                    sock.close()
            except OSError:
                pass  # socket already closed
            time.sleep(app_info.TRTT_RECONNECT_SLEEP)

    _connected = False
    logger.info("TRTT client stopped")


# ═══════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

def start() -> None:
    """Launch the TRTT client background thread (idempotent)."""
    global _thread, _running
    if _thread and _thread.is_alive():
        return
    _running = True
    _thread = threading.Thread(target=_client_loop, daemon=True)
    _thread.start()
    logger.info(f"TRTT client started → {HOST}:{PORT}")
    logger.info("  (BMS User.cfg: set g_bTacviewRealTime 1)")


def stop() -> None:
    """Request shutdown of the background thread."""
    global _running
    _running = False


def is_connected() -> bool:
    """True if the TCP link to BMS TRTT is active."""
    return _connected


def get_contacts(*, own_lat: Optional[float] = None,
                 own_lon: Optional[float] = None,
                 max_nm: float = 9999.0,
                 allies_only: bool = False) -> List[dict]:
    """
    Return filtered TRTT contacts.

    Parameters:
        own_lat/own_lon: ownship position (for range filter + self-exclusion)
        max_nm:          max range in NM (solo=240, multi=ignored)
        allies_only:     if True, exclude confirmed enemies (camp=2)
    """
    now = time.time()
    with _lock:
        snapshot = list(_contacts.items())

    result: List[dict] = []
    for obj_id, c in snapshot:
        # Stale check (>30s = destroyed)
        if now - c.get('_ts', 0) > 30.0:
            continue
        # Camp filter: exclude confirmed enemies (camp=2), keep friendlies + unknown
        if allies_only and c.get('camp', 3) == 2:
            continue
        # Type filter: air only; 'other' kept only if recent (<10s)
        ct = c.get('type_name', 'other')
        if ct in ('ground', 'sea', 'weapon', 'navaid'):
            continue
        if ct == 'other' and (now - c.get('_ts', 0)) > 10.0:
            continue
        # Range filter
        if own_lat is not None and own_lon is not None and max_nm < 9999.0:
            dlat = c['lat'] - own_lat
            dlon = (c['lon'] - own_lon) * math.cos(math.radians(own_lat))
            dist_nm = math.sqrt(dlat**2 + dlon**2) * 60.0
            if dist_nm > max_nm:
                continue
        # Self-exclusion (same position ≈ ownship)
        if own_lat is not None and own_lon is not None:
            if abs(c['lat'] - own_lat) < 0.002 and abs(c['lon'] - own_lon) < 0.002:
                continue
        result.append({k: v for k, v in c.items() if k != '_ts'})
    return result


def get_diagnostics() -> dict:
    """
    Return diagnostic info for logging and /api/acmi/status.

    Returns dict with:
        host, connected, thread_alive, nb_contacts_raw, sample,
        config_hint
    """
    with _lock:
        nb = len(_contacts)
        sample_items = list(_contacts.items())[:8]
    now = time.time()
    sample = [
        {
            'id':       oid,
            'type':     c.get('type_name', '?'),
            'camp':     c.get('camp', '?'),
            'callsign': c.get('callsign', '?'),
            'age_s':    round(now - c.get('_ts', 0), 1),
        }
        for oid, c in sample_items
    ]
    return {
        "trtt_host":      f"{HOST}:{PORT}",
        "connected":      _connected,
        "thread_alive":   _thread.is_alive() if _thread else False,
        "nb_contacts_raw": nb,
        "sample":         sample,
        "config_bms":     app_info.BMS_CONFIG_HINT,
    }
