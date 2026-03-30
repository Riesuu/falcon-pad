# -*- coding: utf-8 -*-
"""
falcon_pad.routes — All FastAPI API endpoints.

Copyright (C) 2024  Riesu — GNU GPL v3
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

import airports
import app_info
import config
import mission
import trtt
import ui_prefs
from theaters import (detect_theater_from_coords_multi,
                      get_theater, get_theater_name, is_theater_detected)

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
        if not af:
            return {"dep": None, "arr": None, "alt": None}
        ap_list = airports.load(get_theater_name()) if is_theater_detected() else []
        return mission.match_airfields_to_airports(af, ap_list)

    @app.post("/api/upload")
    async def upload_mission(file: UploadFile = File(...)):
        try:
            content = (await file.read()).decode("latin-1")
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
        briefing_dir: Optional[str] = None
        broadcast_ms: Optional[int] = None
        theme:        Optional[str] = None

    @app.get("/api/settings")
    async def settings_get():
        return {**config.APP_CONFIG, "current_port": server_port, "current_ip": server_ip}

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
        return {"ip": server_ip, "port": server_port, "url": f"http://{server_ip}:{server_port}"}

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
        return {"ok": True, "prefs": ui_prefs.prefs}

    # ── ACMI / TRTT ──────────────────────────────────────────────
    class TrttConfigModel(BaseModel):
        host: Optional[str] = None
        port: Optional[int] = None

    @app.post("/api/trtt/config")
    async def trtt_config(c: TrttConfigModel):
        if c.host:
            trtt.HOST = c.host.strip()
        if c.port and 1024 <= c.port <= 65535:
            trtt.PORT = c.port
        logger.info(f"TRTT config: {trtt.HOST}:{trtt.PORT}")
        return {"status": "ok", "trtt_host": f"{trtt.HOST}:{trtt.PORT}"}

    @app.get("/api/acmi/status")
    async def acmi_status():
        diag = trtt.get_diagnostics()
        return {"trtt_host": diag.get("host", ""),
                "connected": diag.get("connected", False),
                "thread_alive": diag.get("thread_alive", False),
                "nb_contacts": diag.get("nb_contacts_raw", 0),
                "config_bms": "set g_bTacviewRealTime 1  (User/config/Falcon BMS User.cfg)"}

    # ── Briefing ─────────────────────────────────────────────────
    _BRIEFING_ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".html", ".htm"}
    _BRIEFING_MAX_MB  = 50

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

    @app.post("/api/briefing/upload")
    async def briefing_upload(file: UploadFile = File(...)):
        filename = file.filename or "unnamed"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _BRIEFING_ALLOWED:
            raise HTTPException(400, f"Type non supporté: {ext}")
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

    def _resolve_briefing_file(filename):
        safe = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
        fp = os.path.join(config.BRIEFING_DIR, safe)
        if os.path.exists(fp):
            return fp
        bd = get_briefings_dir()
        if bd:
            fp2 = os.path.join(bd, safe)
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

    async def _docx_to_html(fp):
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
                '<!DOCTYPE html><html><head><meta charset="UTF-8"><style>'
                'body{background:#060a12;color:#cbd5e1;font-family:system-ui,-apple-system,'
                "'Segoe UI',sans-serif;max-width:860px;margin:0 auto;padding:32px 24px;"
                'font-size:15px;line-height:1.7}'
                'h1{font-size:22px;color:#fbbf24}h2{font-size:16px;color:#94a3b8}'
                'h3{font-size:13px;color:#4ade80}p{margin:4px 0;color:#94a3b8}'
                'strong{color:#e2e8f0}em{color:#fbbf24}'
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

    # ── Index ────────────────────────────────────────────────────
    @app.get("/")
    async def index():
        idx = os.path.join(frontend_dir, "index.html")
        if os.path.exists(idx):
            return FileResponse(idx, media_type="text/html")
        return HTMLResponse("<h1>Falcon-Pad — frontend/index.html manquant</h1>", status_code=500)
