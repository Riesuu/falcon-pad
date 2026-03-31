# -*- coding: utf-8 -*-
"""
Falcon-Pad — Tactical companion app for Falcon BMS
Copyright (C) 2024  Riesu <contact@falcon-charts.com>  GNU GPL v3
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import List

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as _StarResp

import app_info
import config
import trtt
from broadcast import broadcast_loop, ini_watcher_loop, broadcast, theater_msg, _try_float
import broadcast as _bc
from routes import register_routes
from sharedmem import BMSSharedMemory, safe_read

logger = logging.getLogger(__name__)

# ── Paths / constants ─────────────────────────────────────────────────────────
ASSETS_DIR   = os.path.join(app_info.BUNDLE_DIR, "assets")
FRONTEND_DIR = os.path.join(app_info.BUNDLE_DIR, "frontend")


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

# ── Singletons ────────────────────────────────────────────────────────────────
bms = BMSSharedMemory()
ws_clients: List[WebSocket] = []


# ── Middleware ────────────────────────────────────────────────────────────────
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


# ── App & lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_a):
    asyncio.create_task(broadcast_loop(bms, ws_clients, safe_read))
    asyncio.create_task(ini_watcher_loop(bms, ws_clients))
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
app.add_middleware(_LocalOnlyMiddleware)

# Register all API routes
register_routes(
    app, bms, ws_clients,
    broadcast_fn=broadcast,
    theater_msg_fn=theater_msg,
    get_briefings_dir=lambda: _bc.bms_briefings_dir,
    try_float_fn=_try_float,
    frontend_dir=FRONTEND_DIR,
    server_ip=SERVER_IP,
    server_port=SERVER_PORT,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT — Qt tray window + uvicorn server thread
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import threading as _th

    def _run_server():
        try:
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=SERVER_PORT,
                log_level="warning",
                log_config=None,
                access_log=False,
            )
        except Exception:
            logger.exception("Uvicorn server thread crashed")

    _th.Thread(target=_run_server, daemon=True).start()

    try:
        from PySide6.QtWidgets import QApplication, QWidget
        from PySide6.QtCore    import Qt, QTimer
        from PySide6.QtGui     import (QPainter, QColor, QPen, QFont,
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
            p.drawText(22, y, "NETWORK"); y += 17
            p.setFont(QFont("Consolas", 11)); p.setPen(QPen(self.BLUE))
            p.drawText(22, y, f"http://{SERVER_IP}:{SERVER_PORT}"); y += 25
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold)); p.setPen(QPen(self.TXT_DIM))
            p.drawText(22, y, app_info.BMS.upper()); y += 17
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
            p.drawText(bx, by_, bw_, bh_, Qt.AlignmentFlag.AlignCenter, "\u25a0  PUSH TO EJECT")
            p.setPen(QPen(self.TXT_DIM)); p.setFont(QFont("Consolas", 7))
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
