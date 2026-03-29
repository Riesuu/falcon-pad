# -*- coding: utf-8 -*-
"""
Falcon-Pad — Tactical companion app for Falcon BMS
Copyright (C) 2024  Riesu <contact@falcon-charts.com>  GNU GPL v3
"""

# ── stdlib / framework ────────────────────────────────────────────────────────
import asyncio
import configparser
import html as _html
import json
import logging
import os
import re
import sys
import time as _time
from contextlib import asynccontextmanager
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as _StarResp

# ── falcon-pad modules ────────────────────────────────────────────────────────
import app_info
import config
import ui_prefs
import airports
import radar
import trtt
import mission
from sharedmem import BMSSharedMemory, safe_read
from stringdata import (detect_theater, get_bms_briefings_dir, get_campaign_dir,
                        get_hsd_lines, get_mk_markpoints, get_ppt_threats,
                        get_steerpoints, read_all_strings)
from theaters import (detect_theater_from_coords_multi,
                      get_theater, get_theater_name, is_theater_detected)

logger = logging.getLogger(__name__)

# ── Derived paths / constants ─────────────────────────────────────────────────
ASSETS_DIR   = os.path.join(app_info.BASE_DIR, "assets")
FRONTEND_DIR = os.path.join(app_info.BASE_DIR, "frontend")
if not os.path.isdir(FRONTEND_DIR):
    FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")


def _get_local_ip() -> str:
    import socket as _s
    try:
        with _s.socket(_s.AF_INET, _s.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "0.0.0.0"


SERVER_IP   = _get_local_ip()
SERVER_PORT = int(config.APP_CONFIG["port"])

# ── BMS shared memory singleton ───────────────────────────────────────────────
bms = BMSSharedMemory()

# ── WebSocket clients ─────────────────────────────────────────────────────────
ws_clients: List[WebSocket] = []

# ── Broadcast helpers ─────────────────────────────────────────────────────────
async def _broadcast(msg: str) -> None:
    dead = []
    for ws in list(ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in ws_clients:
            ws_clients.remove(ws)


def _theater_msg() -> str:
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


# ── Broadcast loop ────────────────────────────────────────────────────────────
_bms_last_reconnect = 0.0
_BMS_RECONNECT_INTERVAL = 5.0
_bms_campaign_dir = ""
_bms_briefings_dir = ""


async def broadcast_loop() -> None:
    global _bms_last_reconnect, _bms_campaign_dir, _bms_briefings_dir
    while True:
        try:
            if not bms.connected:
                now = _time.time()
                if now - _bms_last_reconnect >= _BMS_RECONNECT_INTERVAL:
                    _bms_last_reconnect = now
                    was = bms.connected
                    bms.try_reconnect()
                    if not was and bms.connected:
                        radar.reset()

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
                        _bms_campaign_dir = _cd
                    _bd = get_bms_briefings_dir(_strings)
                    if _bd:
                        _bms_briefings_dir = _bd
                    _thr_changed = detect_theater(_strings)
                    _shm_route   = get_steerpoints(_strings)
                    _shm_threats = get_ppt_threats(_strings)
                    if (_shm_route or _shm_threats) and ws_clients:
                        mission.update_from_shm(_shm_route, _shm_threats)
                        await _broadcast(json.dumps({"type": "mission", "data": mission.mission_data}))
                    _mk_marks = get_mk_markpoints(_strings)
                    _hsd      = get_hsd_lines(_strings)

            if pos and ws_clients:
                await _broadcast(json.dumps({"type": "aircraft", "data": pos}))
                own_lat = pos.get("lat")
                own_lon = pos.get("lon")
                radar_c = radar.get_contacts(
                    bms.shm_ptrs, bms.ptr1,
                    own_lat=own_lat, own_lon=own_lon,
                    ptr2=bms.ptr2 or 0,
                ) if bms.ptr1 else []
                await _broadcast(json.dumps({"type": "radar", "data": radar_c}))
                acmi_c = trtt.get_contacts(own_lat=own_lat, own_lon=own_lon)
                if acmi_c:
                    await _broadcast(json.dumps({"type": "acmi", "data": acmi_c}))
                if bms.connected and ptr_str:
                    if _thr_changed:
                        await _broadcast(_theater_msg())
                    await _broadcast(json.dumps({"type": "mk_marks", "data": _mk_marks}))
                    await _broadcast(json.dumps({"type": "hsd_lines", "data": _hsd}))

            if ws_clients:
                await _broadcast(json.dumps({"type": "status", "data": {"connected": bms.connected}}))

        except Exception as e:
            logger.debug(f"broadcast_loop: {e}")
        await asyncio.sleep(config.APP_CONFIG.get("broadcast_ms", 200) / 1000.0)


# ── INI watcher ───────────────────────────────────────────────────────────────
async def _ini_watcher_loop() -> None:
    _last_path  = ""
    _last_mtime = 0.0
    while True:
        try:
            if not (bms.connected and mission.mission_data.get("route")):
                extra = ([os.path.join(_bms_campaign_dir, "*.ini")]
                         if (_bms_campaign_dir and os.path.isdir(_bms_campaign_dir)) else None)
                path, mtime = mission.find_latest_ini(extra)
                if path and (path != _last_path or mtime > _last_mtime + 1):
                    _last_path  = path
                    _last_mtime = mtime
                    # Detect theater from raw BMS coords before parsing
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
                                await _broadcast(_theater_msg())
                    except Exception:
                        pass
                    result = mission.parse_ini_file(path)
                    if result and ws_clients:
                        await _broadcast(json.dumps({"type": "mission", "data": mission.mission_data}))
        except Exception as e:
            logger.debug(f"INI watcher: {e}")
        await asyncio.sleep(3)


def _try_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# ── App & lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_a):
    asyncio.create_task(broadcast_loop())
    asyncio.create_task(_ini_watcher_loop())
    trtt.start()
    config.log_sep(f"{app_info.SHORT} v{app_info.VERSION} — by {app_info.AUTHOR}")
    logger.info(f"  Contact  : {app_info.CONTACT}")
    logger.info(f"  Website  : {app_info.WEBSITE}")
    logger.info(f"  License  : {app_info.LICENSE}")
    logger.info(f"  Log      : {config.LOG_FILE}")
    logger.info(f"  Briefing : {config.BRIEFING_DIR}")
    logger.info(f"  Config   : {app_info.CONFIG_FILE}")
    logger.info(f"  BMS      : {'CONNECTE' if bms.connected else 'NON DETECTE'}")
    logger.info(f"  Local    : http://localhost:{SERVER_PORT}       <- PC")
    logger.info(f"  Reseau   : http://{SERVER_IP}:{SERVER_PORT}  <- Tablette/Mobile")
    config.log_sep()
    yield
    config.log_sep("ARRET")


app = FastAPI(title="Falcon-Pad", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


def _is_local(ip: str) -> bool:
    return (ip in ("127.0.0.1", "::1", "localhost") or
            ip.startswith("10.") or ip.startswith("192.168.") or
            (ip.startswith("172.") and
             any(ip.startswith(f"172.{i}.") for i in range(16, 32))))


class _LocalOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else ""
        if not _is_local(client_ip):
            return _StarResp("Acces refuse — reseau local uniquement", status_code=403)
        return await call_next(request)


app.add_middleware(_LocalOnlyMiddleware)


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        await websocket.send_text(json.dumps({"type": "status", "data": {"connected": bms.connected}}))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in ws_clients:
            ws_clients.remove(websocket)


@app.get("/api/airports")
async def get_airports():
    if not is_theater_detected():
        return []
    return airports.load(get_theater_name())


@app.get("/api/ini/status")
async def ini_status():
    status = mission.ini_status()
    status["theater"] = get_theater_name()
    status["source"]  = "shm" if (bms.connected and mission.mission_data.get("route")) else "ini"
    return status


@app.get("/api/mission")
async def get_mission():
    return mission.mission_data


@app.post("/api/upload")
async def upload_mission(file: UploadFile = File(...)):
    try:
        content = (await file.read()).decode("latin-1")
        # Theater detection from raw BMS coords before parsing
        _cfg = configparser.RawConfigParser()
        _cfg.optionxform = str  # type: ignore[assignment]
        _cfg.read_string(content)
        if _cfg.has_section("STPT"):
            _pts = [(float(_p[0]), float(_p[1]))
                    for _, _v in _cfg["STPT"].items()
                    for _p in [_v.split(",")]
                    if len(_p) >= 2 and _try_float(_p[0]) and _try_float(_p[1])
                    and abs(float(_p[0])) > 10 and abs(float(_p[1])) > 10]
            if _pts and detect_theater_from_coords_multi(_pts):
                await _broadcast(_theater_msg())
        result = mission.set_from_upload(content, file.filename or "uploaded.ini")
        route   = result.get("route",   [])
        threats = result.get("threats", [])
        fplan   = result.get("flightplan", [])
        if not route and not threats and not fplan:
            raise HTTPException(400, "No valid steerpoints found — check theater and file format")
        logger.info(f"INI upload OK: {len(route)} WP, {len(threats)} PPT, {len(fplan)} FP")
        return {"status": "ok", "route": len(route),
                "threats": len(threats), "flightplan": len(fplan)}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"INI upload error: {e}")
        raise HTTPException(400, f"Parse error: {e}")


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingsModel(BaseModel):
    port:         Optional[int] = None
    briefing_dir: Optional[str] = None
    broadcast_ms: Optional[int] = None
    theme:        Optional[str] = None


@app.get("/api/settings")
async def settings_get():
    return {**config.APP_CONFIG, "current_port": SERVER_PORT, "current_ip": SERVER_IP}


@app.post("/api/settings")
async def settings_save(s: SettingsModel):
    changed: list = []
    if s.port is not None and 1024 <= s.port <= 65535 and s.port != config.APP_CONFIG.get("port"):
        config.APP_CONFIG["port"] = s.port
        changed.append("port")
    if s.briefing_dir is not None and s.briefing_dir.strip():
        nd = s.briefing_dir.strip()
        try:
            os.makedirs(nd, exist_ok=True)
            config.APP_CONFIG["briefing_dir"] = nd
            config.BRIEFING_DIR = nd
            changed.append("briefing_dir")
        except Exception as e:
            raise HTTPException(400, f"Dossier invalide: {e}")
    if s.broadcast_ms is not None and 50 <= s.broadcast_ms <= 2000:
        config.APP_CONFIG["broadcast_ms"] = s.broadcast_ms
        changed.append("broadcast_ms")
    if s.theme is not None and s.theme in ("dark", "light"):
        config.APP_CONFIG["theme"] = s.theme
        changed.append("theme")
    config.save(config.APP_CONFIG)
    needs_restart = "port" in changed
    logger.info(f"Settings: {changed}" + (" — RESTART requis (port)" if needs_restart else ""))
    return {"ok": True, "changed": changed, "needs_restart": needs_restart, "config": config.APP_CONFIG}


@app.get("/api/server/info")
async def server_info():
    return {"ip": SERVER_IP, "port": SERVER_PORT, "url": f"http://{SERVER_IP}:{SERVER_PORT}"}


@app.get("/api/app/info")
async def app_info_route():
    return {"name": app_info.SHORT, "version": app_info.VERSION,
            "author": app_info.AUTHOR, "website": app_info.WEBSITE,
            "github": app_info.GITHUB, "bms": app_info.BMS}


@app.get("/api/theater")
async def theater_info():
    if not is_theater_detected():
        return {}
    tp = get_theater()
    lat_min, lat_max, lon_min, lon_max = tp.bbox
    c_lat = (lat_min + lat_max) / 2
    c_lon = (lon_min + lon_max) / 2
    span  = max(lat_max - lat_min, lon_max - lon_min)
    zoom  = 6 if span > 20 else 7 if span > 15 else 8
    return {"name": get_theater_name(),
            "center_lat": c_lat, "center_lon": c_lon, "zoom": zoom,
            "bbox": {"lat_min": lat_min, "lat_max": lat_max,
                     "lon_min": lon_min, "lon_max": lon_max}}


# ── UI Preferences ────────────────────────────────────────────────────────────

class UiPrefsModel(BaseModel):
    active_color:     Optional[str]   = None
    layer:            Optional[str]   = None
    ppt_visible:      Optional[bool]  = None
    airports_visible: Optional[bool]  = None
    runways_visible:  Optional[bool]  = None
    ap_name_visible:  Optional[bool]  = None
    color_draw:       Optional[str]   = None
    size_draw:        Optional[float] = None
    color_stpt:       Optional[str]   = None
    size_stpt:        Optional[float] = None
    color_fplan:      Optional[str]   = None
    size_fplan:       Optional[float] = None
    color_ppt:        Optional[str]   = None
    size_ppt:         Optional[float] = None
    size_stpt_line:   Optional[float] = None
    size_fplan_line:  Optional[float] = None
    size_ppt_dot:     Optional[float] = None
    color_hsd_l1:     Optional[str]   = None
    color_hsd_l2:     Optional[str]   = None
    color_hsd_l3:     Optional[str]   = None
    color_hsd_l4:     Optional[str]   = None
    rwy_offsets:      Optional[str]   = None
    annotations:      Optional[str]   = None


@app.get("/api/ui-prefs")
async def ui_prefs_get():
    return ui_prefs.prefs


@app.post("/api/ui-prefs")
async def ui_prefs_save(p: UiPrefsModel):
    hex_re = r"#[0-9a-fA-F]{6}$"
    for key in ("active_color", "color_draw", "color_stpt", "color_fplan", "color_ppt",
                "color_hsd_l1", "color_hsd_l2", "color_hsd_l3", "color_hsd_l4"):
        val = getattr(p, key)
        if val is not None and re.match(hex_re, val):
            ui_prefs.prefs[key] = val
    if p.layer is not None and p.layer in ("dark", "osm", "satellite", "terrain"):
        ui_prefs.prefs["layer"] = p.layer
    for key in ("ppt_visible", "airports_visible", "runways_visible", "ap_name_visible"):
        val = getattr(p, key)
        if val is not None:
            ui_prefs.prefs[key] = val
    for key in ("size_draw", "size_stpt", "size_stpt_line", "size_fplan",
                "size_fplan_line", "size_ppt", "size_ppt_dot"):
        val = getattr(p, key)
        if val is not None and 0.5 <= val <= 50:
            ui_prefs.prefs[key] = val
    for key in ("rwy_offsets", "annotations"):
        val = getattr(p, key)
        if val is not None:
            try:
                json.loads(val)
                ui_prefs.prefs[key] = val
            except Exception:
                pass
    ui_prefs.save(ui_prefs.prefs)
    logger.debug(f"ui_prefs saved: {p.model_dump(exclude_none=True)}")
    return {"ok": True, "prefs": ui_prefs.prefs}


# ── ACMI status ───────────────────────────────────────────────────────────────

@app.get("/api/acmi/status")
async def acmi_status():
    diag = trtt.get_diagnostics()
    return {"trtt_host": diag.get("host", ""),
            "connected": diag.get("connected", False),
            "thread_alive": diag.get("thread_alive", False),
            "nb_contacts": diag.get("nb_contacts", 0),
            "config_bms": "set g_bTacviewRealTime 1  (User/config/Falcon BMS User.cfg)"}


# ── Briefing ──────────────────────────────────────────────────────────────────

_BRIEFING_ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".html", ".htm"}
_BRIEFING_MAX_MB  = 50


def _scan_briefing_dir(bdir: str, source: str = "user") -> list:
    """List briefing files in a directory. `source` marks origin (user / bms)."""
    from datetime import datetime as _dt
    files = []
    if not bdir or not os.path.isdir(bdir):
        return files
    for fn in sorted(os.listdir(bdir)):
        ext = os.path.splitext(fn)[1].lower()
        if ext not in _BRIEFING_ALLOWED:
            continue
        fp = os.path.join(bdir, fn)
        try:
            stat = os.stat(fp)
        except OSError:
            continue
        files.append({"name": fn, "ext": ext.lstrip("."),
                      "size_kb":  round(stat.st_size / 1024, 1),
                      "modified": _dt.fromtimestamp(stat.st_mtime).strftime("%d/%m %H:%M"),
                      "source":   source})
    return files


def _briefing_meta() -> list:
    files = _scan_briefing_dir(config.BRIEFING_DIR, "user")
    if _bms_briefings_dir and _bms_briefings_dir != config.BRIEFING_DIR:
        files += _scan_briefing_dir(_bms_briefings_dir, "bms")
    return files


@app.get("/api/briefing/list")
async def briefing_list():
    return {"files": _briefing_meta()}


@app.post("/api/briefing/upload")
async def briefing_upload(file: UploadFile = File(...)):
    filename = file.filename or "unnamed"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _BRIEFING_ALLOWED:
        raise HTTPException(400, f"Type non supporté: {ext}. Acceptés: {', '.join(_BRIEFING_ALLOWED)}")
    data = await file.read()
    if len(data) > _BRIEFING_MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"Fichier trop lourd (max {_BRIEFING_MAX_MB} MB)")
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
    dest = os.path.join(config.BRIEFING_DIR, safe_name)
    with open(dest, "wb") as f:
        f.write(data)
    logger.info(f"Briefing uploadé: {safe_name} ({len(data)//1024} KB)")
    return {"ok": True, "name": safe_name, "files": _briefing_meta()}


@app.delete("/api/briefing/delete/{filename}")
async def briefing_delete(filename: str):
    safe = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
    fp   = os.path.join(config.BRIEFING_DIR, safe)
    if not os.path.exists(fp):
        raise HTTPException(404, "Fichier introuvable")
    os.remove(fp)
    logger.info(f"Briefing supprimé: {safe}")
    return {"ok": True, "files": _briefing_meta()}


def _resolve_briefing_file(filename: str) -> str:
    """Find a briefing file in user dir or BMS dir. Raises 404 if not found."""
    safe = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
    fp = os.path.join(config.BRIEFING_DIR, safe)
    if os.path.exists(fp):
        return fp
    if _bms_briefings_dir:
        fp2 = os.path.join(_bms_briefings_dir, safe)
        if os.path.exists(fp2):
            return fp2
    raise HTTPException(404, "Fichier introuvable")


@app.get("/api/briefing/file/{filename}")
async def briefing_serve(filename: str):
    fp = _resolve_briefing_file(filename)
    ext = os.path.splitext(fp)[1].lower()
    if ext == ".docx":
        return await _docx_to_html(fp)
    mime = {".pdf": "application/pdf", ".png": "image/png",
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".html": "text/html", ".htm": "text/html"}.get(ext, "application/octet-stream")
    return FileResponse(fp, media_type=mime, headers={"Content-Disposition": "inline"})


async def _docx_to_html(fp: str):
    try:
        from docx import Document as _Doc  # type: ignore[import-untyped]
        doc  = _Doc(fp)
        para_html = []
        for p in doc.paragraphs:
            if not p.text.strip():
                para_html.append("<br>")
                continue
            style = (p.style.name.lower() if p.style and p.style.name else "")
            if   "heading 1" in style: para_html.append(f"<h1>{p.text}</h1>")
            elif "heading 2" in style: para_html.append(f"<h2>{p.text}</h2>")
            elif "heading 3" in style: para_html.append(f"<h3>{p.text}</h3>")
            else:
                runs = ""
                for r in p.runs:
                    t = _html.escape(r.text)
                    if r.bold:   t = f"<strong>{t}</strong>"
                    if r.italic: t = f"<em>{t}</em>"
                    runs += t
                para_html.append(f"<p>{runs}</p>")
        body = "\n".join(para_html)
        html = (
            '<!DOCTYPE html><html><head><meta charset="UTF-8"><style>'
            'body{background:#060a12;color:#cbd5e1;font-family:system-ui,-apple-system,'
            "'Segoe UI',sans-serif;max-width:860px;margin:0 auto;padding:32px 24px;"
            'font-size:15px;line-height:1.7}'
            'h1{font-size:22px;color:#fbbf24;letter-spacing:2px;text-transform:uppercase;'
            'border-bottom:1px solid rgba(251,191,36,.2);padding-bottom:8px;margin:24px 0 12px}'
            'h2{font-size:16px;color:#94a3b8;letter-spacing:1.5px;text-transform:uppercase;margin:20px 0 8px}'
            'h3{font-size:13px;color:#4ade80;letter-spacing:1px;text-transform:uppercase;margin:16px 0 6px}'
            'p{margin:4px 0;color:#94a3b8}strong{color:#e2e8f0}em{color:#fbbf24}'
            f'</style></head><body>{body}</body></html>'
        )
        return HTMLResponse(content=html)
    except ImportError:
        return HTMLResponse(
            '<html><body style="background:#060a12;color:#ef4444;font-family:monospace;padding:40px">'
            '<h2>python-docx non installé</h2><p><code>pip install python-docx</code></p></body></html>',
            status_code=500)
    except Exception as e:
        return HTMLResponse(
            f'<html><body style="background:#060a12;color:#ef4444;padding:40px;font-family:monospace">'
            f'<h2>Erreur conversion DOCX</h2><pre>{e}</pre></body></html>',
            status_code=500)


@app.get("/")
async def index():
    idx = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx, media_type="text/html")
    return HTMLResponse("<h1>Falcon-Pad — frontend/index.html manquant</h1>", status_code=500)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT — Qt tray window + uvicorn server thread
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import threading as _th

    def _run_server():
        uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="warning")

    _th.Thread(target=_run_server, daemon=True).start()

    try:
        from PySide6.QtWidgets import QApplication, QWidget  # type: ignore[import-untyped]
        from PySide6.QtCore    import Qt, QTimer             # type: ignore[import-untyped]
        from PySide6.QtGui     import (QPainter, QColor, QPen, QFont,  # type: ignore[import-untyped]
                                       QPixmap, QIcon, QBrush)
    except ImportError:
        logger.error("PySide6 absent — pip install PySide6")
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
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
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
                    self._logo = px.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
            self._drag_pos = self._btn_rect = self._min_rect = None
            self._btn_hover = self._min_hover = self._bms_ok = False
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
            rx, ry, rw, rh = W-36, 10, 24, 18
            self._min_rect = (rx, ry, rw, rh)
            mc = self.TXT_MID if self._min_hover else self.TXT_DIM
            p.setPen(QPen(mc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rx, ry, rw, rh)
            p.setPen(QPen(mc, 2))
            p.drawLine(rx+5, ry+rh//2, rx+rw-5, ry+rh//2)
            tx = 20
            if self._logo:
                p.drawPixmap(12, 8, self._logo); tx = 88
            p.setPen(QPen(self.ACCENT))
            p.setFont(QFont("Consolas", 15, QFont.Weight.Bold))
            p.drawText(tx, 8, W-tx-44, 40, Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft, "FALCON-PAD")
            p.setPen(QPen(self.TXT_DIM))
            p.setFont(QFont("Consolas", 8))
            p.drawText(tx, 48, W-tx-44, 20, Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,
                       f"v{app_info.VERSION}  ·  by {app_info.AUTHOR}")
            y = 96
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold)); p.setPen(QPen(self.TXT_DIM))
            p.drawText(22, y, "LOCAL"); y += 17
            p.setFont(QFont("Consolas", 11)); p.setPen(QPen(self.ACCENT))
            p.drawText(22, y, f"http://localhost:{SERVER_PORT}"); y += 25
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold)); p.setPen(QPen(self.TXT_DIM))
            p.drawText(22, y, "RESEAU  —  Tablette / Mobile"); y += 17
            p.setFont(QFont("Consolas", 11)); p.setPen(QPen(self.BLUE))
            p.drawText(22, y, f"http://{SERVER_IP}:{SERVER_PORT}"); y += 25
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold)); p.setPen(QPen(self.TXT_DIM))
            p.drawText(22, y, "FALCON BMS 4.38"); y += 17
            dc = self.ACCENT if self._bms_ok else self.RED
            p.setBrush(QBrush(dc)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(22, y-9, 10, 10)
            p.setPen(QPen(dc))
            p.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            p.drawText(38, y, "CONNECTE" if self._bms_ok else "NON DETECTE"); y += 25
            p.setPen(QPen(self.TXT_DIM))
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
            p.drawText(22, y, "LOGS"); y += 15
            ls = app_info.LOG_DIR if len(app_info.LOG_DIR) <= 54 else "..." + app_info.LOG_DIR[-52:]
            p.setFont(QFont("Consolas", 8)); p.drawText(22, y, ls)
            bx, by_, bw_, bh_ = W//2-72, H-52, 144, 28
            self._btn_rect = (bx, by_, bw_, bh_)
            p.setBrush(QBrush(self.RED_HOV if self._btn_hover else self.RED_DIM))
            p.setPen(QPen(self.RED if self._btn_hover else self.RED_OUT, 1))
            p.drawRect(bx, by_, bw_, bh_)
            p.setPen(QPen(self.RED))
            p.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
            p.drawText(bx, by_, bw_, bh_, Qt.AlignmentFlag.AlignCenter, "■  ARRET")
            p.setPen(QPen(self.TXT_DIM)); p.setFont(QFont("Consolas", 7))
            p.drawText(0, H-13, W, 12, Qt.AlignmentFlag.AlignCenter, "Le serveur sera arrete")
            p.end()

        def mousePressEvent(self, e):
            if e.button() != Qt.MouseButton.LeftButton:
                return
            mx, my = e.position().x(), e.position().y()
            if self._btn_rect:
                bx, by_, bw_, bh_ = self._btn_rect
                if bx <= mx <= bx+bw_ and by_ <= my <= by_+bh_:
                    self._do_quit(); return
            if self._min_rect:
                rx, ry, rw, rh = self._min_rect
                if rx <= mx <= rx+rw and ry <= my <= ry+rh:
                    self.showMinimized(); return
            if my < 80:
                self._drag_pos = e.globalPosition().toPoint()

        def mouseMoveEvent(self, e):
            if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
                delta = e.globalPosition().toPoint() - self._drag_pos
                self.move(self.pos() + delta)
                self._drag_pos = e.globalPosition().toPoint()
            mx, my = e.position().x(), e.position().y()
            if self._btn_rect:
                bx, by_, bw_, bh_ = self._btn_rect
                h = bx <= mx <= bx+bw_ and by_ <= my <= by_+bh_
                if h != self._btn_hover:
                    self._btn_hover = h; self.update()
            if self._min_rect:
                rx, ry, rw, rh = self._min_rect
                h2 = rx <= mx <= rx+rw and ry <= my <= ry+rh
                if h2 != self._min_hover:
                    self._min_hover = h2; self.update()

        def mouseReleaseEvent(self, _e):
            self._drag_pos = None

        def leaveEvent(self, _e):
            if self._btn_hover or self._min_hover:
                self._btn_hover = False; self._min_hover = False; self.update()

        def keyPressEvent(self, e):
            if e.key() == Qt.Key.Key_F4 and e.modifiers() == Qt.KeyboardModifier.AltModifier:
                self._do_quit()

        def _do_quit(self):
            self._timer.stop(); self.close()
            os.kill(os.getpid(), 9)

    _app = QApplication(sys.argv)
    _app.setApplicationName("Falcon-Pad")
    _app.setApplicationVersion(app_info.VERSION)
    _win = FalconPadWindow()
    _app.exec()
