# -*- coding: utf-8 -*-
"""
falcon_pad.routes — All FastAPI API endpoints.

Copyright (C) 2026  Riesu — GNU GPL v3
"""

import configparser
import html as _html
import json
import logging
import os
import re
from typing import Optional

from fastapi import File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

import app_info
import config
from core import airports, mission, trtt
from ui import ui_prefs, ui_theme
from core.theaters import (detect_theater_from_coords_multi,
                           get_theater, get_theater_name, is_theater_detected,
                           THEATER_DB)

logger = logging.getLogger(__name__)


def register_routes(app, bms, ws_clients, broadcast_fn, theater_msg_fn,
                    get_briefings_dir, try_float_fn, frontend_dir, server_ip, server_port):
    """Register all API routes on the FastAPI app instance."""

    # ── WebSocket ────────────────────────────────────────────────
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

    # ── Mission & Airports ───────────────────────────────────────
    @app.get("/api/airports")
    async def get_airports():
        if not is_theater_detected():
            return []
        return airports.load(get_theater_name())

    @app.get("/api/checklist")
    async def get_checklist():
        _cl_path = os.path.join(app_info.BUNDLE_DIR, *app_info.CHECKLIST_REL_PATH)
        try:
            with open(_cl_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    @app.get("/api/ini/status")
    async def ini_status():
        status = mission.ini_status()
        status["theater"] = get_theater_name()
        status["source"]  = "shm" if (bms.connected and mission.mission_data.get("route")) else "ini"
        return status

    @app.get("/api/mission")
    async def get_mission():
        return mission.mission_data

    @app.get("/api/mission/airfields")
    async def get_mission_airfields():
        af = mission.mission_data.get("airfields")
        ap_list = airports.load(get_theater_name()) if is_theater_detected() else []

        # 1. INI type-code airfields (type=1 takeoff, type=7 landing) — most precise
        if af and af.get("_typed"):
            return mission.match_airfields_to_airports(af, ap_list)

        # 2. COMMS TACAN for DEP + route scanning for ARR/ALT (SHM mode)
        comms = mission.mission_data.get("comms")
        if comms and ap_list:
            comms_match = mission.match_comms_to_airport(comms, ap_list)
            if comms_match:
                route = mission.mission_data.get("route", [])
                result = {"dep": comms_match, "arr": None, "alt": None}
                if route:
                    route_match = mission.find_airfields_from_route(route, ap_list)
                    result["arr"] = route_match.get("arr")
                    result["alt"] = route_match.get("alt")
                return result

        # 3. Route scanning (all steerpoints against airports)
        route = mission.mission_data.get("route", [])
        if route and ap_list:
            result = mission.find_airfields_from_route(route, ap_list)
            if result.get("dep") or result.get("arr"):
                return result

        # 4. Fallback to position-based matching
        if af:
            return mission.match_airfields_to_airports(af, ap_list)

        return {"dep": None, "arr": None, "alt": None}

    @app.post("/api/upload")
    async def upload_mission(file: UploadFile = File(...)):
        try:
            content = (await file.read()).decode(app_info.INI_ENCODING)
            _cfg = configparser.RawConfigParser()
            _cfg.optionxform = str  # type: ignore[assignment]
            _cfg.read_string(content)
            if _cfg.has_section("STPT"):
                _pts = [(float(_p[0]), float(_p[1]))
                        for _, _v in _cfg["STPT"].items()
                        for _p in [_v.split(",")]
                        if len(_p) >= 2 and try_float_fn(_p[0]) and try_float_fn(_p[1])
                        and abs(float(_p[0])) > 10 and abs(float(_p[1])) > 10]
                if _pts and detect_theater_from_coords_multi(_pts):
                    await broadcast_fn(ws_clients, theater_msg_fn())
            result = mission.set_from_upload(content, file.filename or "uploaded.ini")
            route   = result.get("route",   [])
            threats = result.get("threats", [])
            fplan   = result.get("flightplan", [])
            if not route and not threats and not fplan:
                raise HTTPException(400, "No valid steerpoints found")
            logger.info(f"INI upload OK: {len(route)} WP, {len(threats)} PPT, {len(fplan)} FP")
            return {"status": "ok", "route": len(route),
                    "threats": len(threats), "flightplan": len(fplan)}
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"INI upload error: {e}")
            raise HTTPException(400, f"Parse error: {e}")

    # ── Settings ─────────────────────────────────────────────────
    class SettingsModel(BaseModel):
        port:         Optional[int] = None
        broadcast_ms: Optional[int] = None
        theme:        Optional[str] = None

    @app.get("/api/settings")
    async def settings_get():
        return {**config.APP_CONFIG, "current_port": server_port, "current_ip": server_ip}

    @app.post("/api/settings")
    async def settings_save(s: SettingsModel):
        changed: list = []
        if s.port is not None and app_info.PORT_MIN <= s.port <= app_info.PORT_MAX and s.port != config.APP_CONFIG.get("port"):
            import socket as _sock
            with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as _sk:
                _sk.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
                if _sk.connect_ex(("127.0.0.1", s.port)) == 0:
                    raise HTTPException(400, f"Port {s.port} is already in use")
            config.APP_CONFIG["port"] = s.port
            changed.append("port")
        if s.broadcast_ms is not None and app_info.BROADCAST_MS_MIN <= s.broadcast_ms <= app_info.BROADCAST_MS_MAX:
            config.APP_CONFIG["broadcast_ms"] = s.broadcast_ms
            changed.append("broadcast_ms")
        if s.theme is not None and s.theme in app_info.VALID_THEMES:
            config.APP_CONFIG["theme"] = s.theme
            changed.append("theme")
        config.save(config.APP_CONFIG)
        needs_restart = "port" in changed
        logger.info(f"Settings: {changed}" + (" — RESTART required (port)" if needs_restart else ""))
        return {"ok": True, "changed": changed, "needs_restart": needs_restart, "config": config.APP_CONFIG}

    @app.get("/api/server/info")
    async def server_info():
        return {"ip": server_ip, "port": server_port, "url": f"http://{server_ip}:{server_port}"}

    @app.get("/api/app/info")
    async def app_info_route():
        return {"name": app_info.SHORT, "version": app_info.VERSION,
                "author": app_info.AUTHOR, "website": app_info.WEBSITE,
                "charts": app_info.CHARTS,
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

    # ── UI Preferences ───────────────────────────────────────────
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
        color_bull:       Optional[str]   = None
        size_bull:        Optional[float] = None
        bull_visible:     Optional[bool]  = None
        size_stpt_line:   Optional[float] = None
        size_fplan_line:  Optional[float] = None
        size_ppt_dot:     Optional[float] = None
        color_aircraft:   Optional[str]   = None
        color_ally:       Optional[str]   = None
        color_enemy:      Optional[str]   = None
        color_ap_blue:    Optional[str]   = None
        color_ap_red:     Optional[str]   = None
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
                    "color_bull", "color_aircraft", "color_ally", "color_enemy",
                    "color_ap_blue", "color_ap_red",
                    "color_hsd_l1", "color_hsd_l2", "color_hsd_l3", "color_hsd_l4"):
            val = getattr(p, key)
            if val is not None and re.match(hex_re, val):
                ui_prefs.prefs[key] = val
        if p.layer is not None and p.layer in app_info.VALID_LAYERS:
            ui_prefs.prefs["layer"] = p.layer
        for key in ("ppt_visible", "airports_visible", "runways_visible", "ap_name_visible", "bull_visible"):
            val = getattr(p, key)
            if val is not None:
                ui_prefs.prefs[key] = val
        for key in ("size_draw", "size_stpt", "size_stpt_line", "size_fplan",
                    "size_fplan_line", "size_ppt", "size_ppt_dot", "size_bull"):
            val = getattr(p, key)
            if val is not None and app_info.SIZE_MIN <= val <= app_info.SIZE_MAX:
                ui_prefs.prefs[key] = val
        for key in ("rwy_offsets", "annotations"):
            val = getattr(p, key)
            if val is not None:
                try:
                    json.loads(val)
                    ui_prefs.prefs[key] = val
                except Exception as e:
                    logger.warning(f"ui_prefs_save: invalid JSON for '{key}': {e}")
        ui_prefs.save(ui_prefs.prefs)
        return {"ok": True, "prefs": ui_prefs.prefs}

    # ── Briefing ─────────────────────────────────────────────────
    _BRIEFING_ALLOWED = app_info.BRIEFING_ALLOWED_EXT
    _BRIEFING_MAX_MB  = app_info.BRIEFING_MAX_MB

    def _scan_briefing_dir(bdir, source="user"):
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
                          "size_kb": round(stat.st_size / 1024, 1),
                          "modified": _dt.fromtimestamp(stat.st_mtime).strftime("%d/%m %H:%M"),
                          "source": source})
        return files

    def _briefing_meta():
        files = _scan_briefing_dir(config.BRIEFING_DIR, "user")
        bd = get_briefings_dir()
        if bd and bd != config.BRIEFING_DIR:
            files += _scan_briefing_dir(bd, "bms")
        return files

    @app.get("/api/briefing/list")
    async def briefing_list():
        return {"files": _briefing_meta()}

    def _safe_briefing_path(filename: str, base_dir: str) -> str:
        """Sanitize filename and verify the resolved path stays inside base_dir."""
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
        dest = os.path.realpath(os.path.join(base_dir, safe_name))
        if not dest.startswith(os.path.realpath(base_dir) + os.sep):
            raise HTTPException(400, "Invalid filename")
        return dest

    @app.post("/api/briefing/upload")
    async def briefing_upload(file: UploadFile = File(...)):
        filename = file.filename or "unnamed"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _BRIEFING_ALLOWED:
            raise HTTPException(400, f"Unsupported file type: {ext}")
        data = await file.read()
        if len(data) > _BRIEFING_MAX_MB * 1024 * 1024:
            raise HTTPException(400, f"File too large (max {_BRIEFING_MAX_MB} MB)")
        safe_name = os.path.basename("".join(c for c in filename if c.isalnum() or c in "._- ").strip())
        dest = _safe_briefing_path(safe_name, config.BRIEFING_DIR)
        with open(dest, "wb") as f:
            f.write(data)
        logger.info(f"Briefing uploaded: {safe_name} ({len(data)//1024} KB)")
        return {"ok": True, "name": safe_name, "files": _briefing_meta()}

    @app.delete("/api/briefing/delete/{filename}")
    async def briefing_delete(filename: str):
        safe = os.path.basename("".join(c for c in filename if c.isalnum() or c in "._- ").strip())
        fp   = _safe_briefing_path(safe, config.BRIEFING_DIR)
        if not os.path.exists(fp):
            raise HTTPException(404, "File not found")
        os.remove(fp)
        logger.info(f"Briefing deleted: {safe}")
        return {"ok": True, "files": _briefing_meta()}

    def _resolve_briefing_file(filename):
        safe = os.path.basename("".join(c for c in filename if c.isalnum() or c in "._- ").strip())
        fp = _safe_briefing_path(safe, config.BRIEFING_DIR)
        if os.path.exists(fp):
            return fp
        bd = get_briefings_dir()
        if bd:
            try:
                fp2 = _safe_briefing_path(safe, bd)
                if os.path.exists(fp2):
                    return fp2
            except HTTPException:
                pass
        raise HTTPException(404, "File not found")

    @app.get("/api/briefing/file/{filename}")
    async def briefing_serve(filename: str):
        fp = _resolve_briefing_file(filename)
        ext = os.path.splitext(fp)[1].lower()
        if ext == ".docx":
            return await _docx_to_html(fp)
        mime = app_info.MIME_MAP.get(ext, app_info.MIME_DEFAULT)
        return FileResponse(fp, media_type=mime, headers={"Content-Disposition": "inline"})

    async def _docx_to_html(fp):
        _err_style = ui_theme.DOCX_ERROR_STYLE
        try:
            from docx import Document as _Doc  # type: ignore[import-untyped]
            doc = _Doc(fp)
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
                f'<!DOCTYPE html><html><head><meta charset="UTF-8"><style>'
                f'{ui_theme.DOCX_CSS}'
                f'</style></head><body>{body}</body></html>'
            )
            return HTMLResponse(content=html)
        except ImportError:
            return HTMLResponse(
                f'<html><body style="{_err_style}">'
                f'<h2>python-docx not installed</h2><p><code>pip install python-docx</code></p></body></html>',
                status_code=500)
        except Exception as e:
            return HTMLResponse(
                f'<html><body style="{_err_style}">'
                f'<h2>DOCX conversion error</h2><pre>{e}</pre></body></html>',
                status_code=500)

    # ── Index ────────────────────────────────────────────────────
    @app.get("/")
    async def index():
        idx = os.path.join(frontend_dir, app_info.INDEX_HTML)
        if os.path.exists(idx):
            return FileResponse(idx, media_type="text/html")
        return HTMLResponse(f"<h1>{app_info.SHORT} — {app_info.INDEX_HTML} missing</h1>", status_code=500)
