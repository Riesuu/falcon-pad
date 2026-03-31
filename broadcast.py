# -*- coding: utf-8 -*-
"""
falcon_pad.broadcast — Real-time WebSocket broadcast + BMS polling loops.

Runs two async loops:
    broadcast_loop()     — push aircraft, contacts, mission, HSD, markpoints
    ini_watcher_loop()   — auto-load .ini files when BMS is not connected

Copyright (C) 2024  Riesu — GNU GPL v3
"""

import asyncio
import configparser
import json
import logging
import os
import time as _time

import config
import mission
import trtt
from stringdata import (detect_theater, get_bms_briefings_dir, get_bms_user_dir,
                        get_campaign_dir, get_hsd_lines, get_mk_markpoints,
                        get_ppt_threats, get_steerpoints, read_all_strings)
from theaters import detect_theater_from_coords_multi, get_theater, get_theater_name

logger = logging.getLogger(__name__)

# ── State (shared with falcon_pad via module-level access) ────────────────────
import app_info

_bms_last_reconnect = 0.0
bms_campaign_dir = ""
bms_briefings_dir = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

async def broadcast(ws_clients, msg: str) -> None:
    dead = []
    for ws in list(ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in ws_clients:
            ws_clients.remove(ws)


def theater_msg() -> str:
    tp = get_theater()
    lat_min, lat_max, lon_min, lon_max = tp.bbox
    c_lat = (lat_min + lat_max) / 2
    c_lon = (lon_min + lon_max) / 2
    span  = max(lat_max - lat_min, lon_max - lon_min)
    zoom  = 6 if span > 20 else 7 if span > 15 else 8
    return json.dumps({"type": "theater", "data": {
        "name": get_theater_name(),
        "center_lat": c_lat, "center_lon": c_lon, "zoom": zoom,
        "bbox": {"lat_min": lat_min, "lat_max": lat_max,
                 "lon_min": lon_min, "lon_max": lon_max},
    }})


def _try_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# ── Main broadcast loop ──────────────────────────────────────────────────────

async def broadcast_loop(bms, ws_clients, safe_read) -> None:
    global _bms_last_reconnect, bms_campaign_dir, bms_briefings_dir
    while True:
        try:
            if not bms.connected:
                now = _time.time()
                if now - _bms_last_reconnect >= app_info.BMS_RECONNECT_S:
                    _bms_last_reconnect = now
                    was = bms.connected
                    bms.try_reconnect()
                    if not was and bms.connected:
                        logger.info("BMS reconnected")

            pos = bms.get_position() if bms.connected else None

            ptr_str = None
            _thr_changed = False
            _mk_marks: list = []
            _hsd: list = []
            if bms.connected:
                ptr_str = (bms.shm_ptrs.get("FalconSharedMemoryAreaString")
                           or bms.shm_ptrs.get("FalconSharedMemoryArea3"))
                if ptr_str:
                    _strings = read_all_strings(ptr_str, safe_read)
                    _cd = get_campaign_dir(_strings)
                    if _cd:
                        bms_campaign_dir = _cd
                    _bd = get_bms_briefings_dir(_strings)
                    if _bd:
                        bms_briefings_dir = _bd
                    _thr_changed = detect_theater(_strings)
                    # Load radio presets from pilot INI if not yet loaded
                    if not mission.mission_data.get("radio"):
                        _ud = get_bms_user_dir(_strings)
                        if _ud:
                            _cfg_dir = os.path.join(_ud, "Config")
                            mission.load_radio_from_dir(_cfg_dir)
                    _shm_route   = get_steerpoints(_strings)
                    _shm_threats = get_ppt_threats(_strings)
                    if (_shm_route or _shm_threats) and ws_clients:
                        mission.update_from_shm(_shm_route, _shm_threats)
                        await broadcast(ws_clients, json.dumps({"type": "mission", "data": mission.mission_data}))
                    _mk_marks = get_mk_markpoints(_strings)
                    _hsd      = get_hsd_lines(_strings)

            if pos and ws_clients:
                await broadcast(ws_clients, json.dumps({"type": "aircraft", "data": pos}))
                own_lat = pos.get("lat")
                own_lon = pos.get("lon")
                acmi_c = trtt.get_contacts(own_lat=own_lat, own_lon=own_lon, allies_only=True, max_nm=app_info.ACMI_CONTACT_NM)
                if acmi_c:
                    await broadcast(ws_clients, json.dumps({"type": "acmi", "data": acmi_c}))
                if bms.connected and ptr_str:
                    if _thr_changed:
                        await broadcast(ws_clients, theater_msg())
                    await broadcast(ws_clients, json.dumps({"type": "mk_marks", "data": _mk_marks}))
                    await broadcast(ws_clients, json.dumps({"type": "hsd_lines", "data": _hsd}))

            if ws_clients:
                await broadcast(ws_clients, json.dumps({"type": "status", "data": {"connected": bms.connected}}))

        except Exception as e:
            logger.debug(f"broadcast_loop: {e}")
        await asyncio.sleep(config.APP_CONFIG.get("broadcast_ms", app_info.DEFAULT_BROADCAST_MS) / 1000.0)


# ── INI watcher loop ─────────────────────────────────────────────────────────

async def ini_watcher_loop(bms, ws_clients) -> None:
    _last_path  = ""
    _last_mtime = 0.0
    while True:
        try:
            if not bms.connected:
                extra = ([os.path.join(bms_campaign_dir, "*.ini")]
                         if (bms_campaign_dir and os.path.isdir(bms_campaign_dir)) else None)
                path, mtime = mission.find_latest_ini(extra)
                if path and (path != _last_path or mtime > _last_mtime + 1):
                    _last_path  = path
                    _last_mtime = mtime
                    try:
                        with open(path, encoding="latin-1") as _f:
                            _raw = _f.read()
                        _cfg = configparser.RawConfigParser()
                        _cfg.optionxform = str  # type: ignore[assignment]
                        _cfg.read_string(_raw)
                        if _cfg.has_section("STPT"):
                            _pts = [(float(_p[0]), float(_p[1]))
                                    for _, _v in _cfg["STPT"].items()
                                    for _p in [_v.split(",")]
                                    if len(_p) >= 2
                                    and _try_float(_p[0]) and _try_float(_p[1])
                                    and abs(float(_p[0])) > 10 and abs(float(_p[1])) > 10]
                            if _pts and detect_theater_from_coords_multi(_pts) and ws_clients:
                                await broadcast(ws_clients, theater_msg())
                    except Exception:
                        pass
                    result = mission.parse_ini_file(path)
                    if result and ws_clients:
                        await broadcast(ws_clients, json.dumps({"type": "mission", "data": mission.mission_data}))
        except Exception as e:
            logger.debug(f"INI watcher: {e}")
        await asyncio.sleep(app_info.BMS_RECONNECT_S)
