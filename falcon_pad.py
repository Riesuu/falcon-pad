# -*- coding: utf-8 -*-
"""
Falcon-Pad — Tactical companion app for Falcon BMS
Copyright (C) 2026  Riesu <contact@falcon-charts.com>  GNU GPL v3
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
from core import trtt
from core.broadcast import broadcast_loop, ini_watcher_loop, broadcast, theater_msg
import core.broadcast as _bc
from server.routes import register_routes
from core.sharedmem import BMSSharedMemory, safe_read

logger = logging.getLogger(__name__)


def _get_local_ip() -> str:
    import socket as _s
    try:
        with _s.socket(_s.AF_INET, _s.SOCK_DGRAM) as s:
            s.connect((app_info.DNS_PROBE_HOST, app_info.DNS_PROBE_PORT))
            return s.getsockname()[0]
    except Exception:
        return app_info.DEFAULT_HOST


SERVER_IP   = _get_local_ip()
SERVER_PORT = int(config.APP_CONFIG["port"])

# ── Singletons ────────────────────────────────────────────────────────────
bms = BMSSharedMemory()
ws_clients: List[WebSocket] = []


# ── Middleware ────────────────────────────────────────────────────────────
def _is_local(ip: str) -> bool:
    return (ip in ("127.0.0.1", "::1", "localhost") or
            ip.startswith("10.") or ip.startswith("192.168.") or
            ip.startswith("fe80:") or ip.startswith("fd") or
            (ip.startswith("172.") and
             any(ip.startswith(f"172.{i}.") for i in range(16, 32))))


class _LocalOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else ""
        if not _is_local(client_ip):
            return _StarResp(app_info.ACCESS_DENIED_MSG, status_code=403)
        resp = await call_next(request)
        if request.url.path.startswith(app_info.STATIC_ROUTE + "/"):
            resp.headers["Cache-Control"] = app_info.CACHE_CONTROL_STATIC
        return resp


# ── App & lifespan ────────────────────────────────────────────────────────
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
    logger.info(f"  BMS      : {'CONNECTED' if bms.connected else 'NOT DETECTED'}")
    logger.info(f"  Local    : http://localhost:{SERVER_PORT}       <- PC")
    logger.info(f"  Network  : http://{SERVER_IP}:{SERVER_PORT}  <- Tablet/Mobile")
    config.log_sep()
    yield
    config.log_sep("SHUTDOWN")


app = FastAPI(title=app_info.SHORT, lifespan=lifespan)
app.mount(app_info.STATIC_ROUTE, StaticFiles(directory=app_info.FRONTEND_DIR), name="static")
app.add_middleware(_LocalOnlyMiddleware)

# Register all API routes
register_routes(
    app, bms, ws_clients,
    broadcast_fn=broadcast,
    theater_msg_fn=theater_msg,
    get_briefings_dir=lambda: _bc.bms_briefings_dir,
    frontend_dir=app_info.FRONTEND_DIR,
    server_ip=SERVER_IP,
    server_port=SERVER_PORT,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT — Qt tray window + uvicorn server thread
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import ctypes
    import threading as _th

    # Set Windows AppUserModelID so taskbar shows our icon instead of Python's
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"riesu.falconpad.{app_info.VERSION}")
    except Exception:
        pass

    def _run_server():
        try:
            uvicorn.run(
                app,
                host=app_info.DEFAULT_HOST,
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
                                       QIcon, QBrush, QPixmap)
    except ImportError:
        logger.error("PySide6 absent — pip install PySide6")
        raise SystemExit(0)

    from ui import ui_theme as _t

    class FalconPadWindow(QWidget):
        W, H = _t.WIN_W, _t.WIN_H

        # ── Color palette (from ui_theme) ────────────────────────
        BG         = QColor(_t.BG)
        BG2        = QColor(_t.BG2)
        ACCENT     = QColor(_t.ACCENT)
        ACCENT_DIM = QColor(_t.ACCENT_DIM)
        RED        = QColor(_t.RED)
        RED_DIM    = QColor(_t.RED_DIM)
        RED_HOV    = QColor(_t.RED_HOV)
        RED_OUT    = QColor(_t.RED_OUT)
        BLUE       = QColor(_t.BLUE)
        GREEN      = QColor(_t.GREEN)
        TXT_DIM    = QColor(_t.TXT_DIM)
        TXT_MID    = QColor(_t.TXT_MID)
        TXT_WHITE  = QColor(_t.TXT_WHITE)

        def __init__(self):
            super().__init__()
            self.setFixedSize(self.W, self.H)
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.setWindowTitle(app_info.SHORT)
            _ico = os.path.join(app_info.ASSETS_DIR, app_info.ICON_FILENAME)
            if os.path.exists(_ico):
                self.setWindowIcon(QIcon(_ico))
            screen = QApplication.primaryScreen().availableGeometry()
            self.move((screen.width()-self.W)//2, (screen.height()-self.H)//2)
            self._logo = None
            _logo_path = os.path.join(app_info.ASSETS_DIR, "logo.png")
            if os.path.exists(_logo_path):
                self._logo = QPixmap(_logo_path).scaledToHeight(
                    56, Qt.TransformationMode.SmoothTransformation)
            self._drag_pos = self._btn_rect = self._min_rect = None
            self._set_rect = None
            self._local_rect = self._net_rect = None
            self._local_hover = self._net_hover = False
            self._set_hover = False
            self._btn_hover = self._min_hover = self._bms_ok = self._acmi_ok = False
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._poll_bms)
            self._timer.start(_t.BMS_POLL_MS)
            QTimer.singleShot(_t.BMS_POLL_INITIAL_MS, self._poll_bms)
            self.setMouseTracking(True)
            self.show()

        def _poll_bms(self):
            try:
                ok = bms.connected or bms.try_reconnect()
                acmi = trtt.is_connected()
                if ok != self._bms_ok or acmi != self._acmi_ok:
                    self._bms_ok = ok
                    self._acmi_ok = acmi
                    self.update()
            except Exception:
                pass

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            W, H = self.W, self.H

            # Background
            p.fillRect(0, 0, W, H, self.BG)
            p.fillRect(0, 0, W, _t.HEADER_H, self.BG2)
            p.fillRect(0, 0, W, _t.ACCENT_LINE_H, self.ACCENT)

            # Logo (top-right of header)
            if self._logo:
                lx = W - self._logo.width() - 16
                ly = (_t.HEADER_H - self._logo.height()) // 2
                p.drawPixmap(lx, ly, self._logo)

            # Header separator
            p.setPen(QPen(self.ACCENT_DIM, 1))
            p.drawLine(_t.TITLE_X, _t.HEADER_H, W - _t.TITLE_X, _t.HEADER_H)

            # Minimize button (top-left area, no conflict with logo)
            rx = _t.TITLE_X
            ry = _t.MIN_BTN_Y
            rw, rh = _t.MIN_BTN_W, _t.MIN_BTN_H
            self._min_rect = (rx, ry, rw, rh)
            mc = self.TXT_MID if self._min_hover else self.TXT_DIM
            p.setPen(QPen(mc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rx, ry, rw, rh)
            p.setPen(QPen(mc, 2))
            p.drawLine(rx+5, ry+rh//2, rx+rw-5, ry+rh//2)

            # Settings button (gear) — right of minimize, borderless
            sx = rx + rw + _t.SET_BTN_X_OFFSET
            sy = _t.SET_BTN_Y
            sw, sh = _t.SET_BTN_W, _t.SET_BTN_H
            self._set_rect = (sx, sy, sw, sh)
            if self._set_hover:
                p.fillRect(sx, sy, sw, sh, self.ACCENT_DIM)
            sc = self.ACCENT if self._set_hover else self.TXT_MID
            p.setPen(QPen(sc))
            p.setFont(QFont(_t.FONT_FAMILY, 14, QFont.Weight.Bold))
            p.drawText(sx, sy - 1, sw, sh + 2, Qt.AlignmentFlag.AlignCenter, "\u2699")

            # Version + author (below minimize button)
            p.setPen(QPen(self.TXT_DIM))
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_SUBTITLE))
            p.drawText(_t.TITLE_X, _t.SUBTITLE_Y, W-64, _t.SUBTITLE_H,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       f"v{app_info.VERSION}  \u00b7  by {app_info.AUTHOR}")

            # Content area
            y = _t.CONTENT_START_Y

            # LOCAL
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_LABEL, QFont.Weight.Bold))
            p.setPen(QPen(self.TXT_DIM))
            p.drawText(_t.MARGIN_LEFT, y, _t.LBL_LOCAL); y += _t.LINE_LABEL_H
            _url_font = QFont(_t.FONT_MONO, _t.FONT_VALUE)
            _url_font.setUnderline(self._local_hover)
            p.setFont(_url_font)
            _local_url = f"http://localhost:{SERVER_PORT}"
            p.setPen(QPen(self.ACCENT if self._local_hover else self.TXT_WHITE))
            p.drawText(_t.MARGIN_LEFT, y, _local_url)
            self._local_rect = (_t.MARGIN_LEFT, y - 14, p.fontMetrics().horizontalAdvance(_local_url), 18)
            y += _t.LINE_VALUE_H

            # NETWORK
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_LABEL, QFont.Weight.Bold))
            p.setPen(QPen(self.TXT_DIM))
            p.drawText(_t.MARGIN_LEFT, y, _t.LBL_NETWORK); y += _t.LINE_LABEL_H
            _url_font2 = QFont(_t.FONT_MONO, _t.FONT_VALUE)
            _url_font2.setUnderline(self._net_hover)
            p.setFont(_url_font2)
            _net_url = f"http://{SERVER_IP}:{SERVER_PORT}"
            p.setPen(QPen(self.ACCENT if self._net_hover else self.BLUE))
            p.drawText(_t.MARGIN_LEFT, y, _net_url)
            self._net_rect = (_t.MARGIN_LEFT, y - 14, p.fontMetrics().horizontalAdvance(_net_url), 18)
            y += _t.LINE_VALUE_H

            # BMS status
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_LABEL, QFont.Weight.Bold))
            p.setPen(QPen(self.TXT_DIM))
            p.drawText(_t.MARGIN_LEFT, y, app_info.BMS.upper()); y += _t.LINE_LABEL_H
            dc = self.GREEN if self._bms_ok else self.RED
            p.setBrush(QBrush(dc)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(_t.MARGIN_LEFT, y-9, _t.STATUS_DOT_R, _t.STATUS_DOT_R)
            p.setPen(QPen(dc))
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_STATUS, QFont.Weight.Bold))
            lbl = _t.LBL_CONNECTED if self._bms_ok else _t.LBL_NOT_DETECTED
            p.drawText(_t.MARGIN_LEFT + _t.STATUS_DOT_R + 6, y, lbl); y += _t.LINE_VALUE_H

            # ACMI status
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_LABEL, QFont.Weight.Bold))
            p.setPen(QPen(self.TXT_DIM))
            p.drawText(_t.MARGIN_LEFT, y, "ACMI  (g_bTacviewRealTime 1)"); y += _t.LINE_LABEL_H
            ac = self.GREEN if self._acmi_ok else self.RED
            p.setBrush(QBrush(ac)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(_t.MARGIN_LEFT, y-9, _t.STATUS_DOT_R, _t.STATUS_DOT_R)
            p.setPen(QPen(ac))
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_STATUS, QFont.Weight.Bold))
            p.drawText(_t.MARGIN_LEFT + _t.STATUS_DOT_R + 6, y,
                       _t.LBL_CONNECTED if self._acmi_ok else _t.LBL_NOT_DETECTED); y += _t.LINE_VALUE_H

            # Logs
            p.setPen(QPen(self.TXT_DIM))
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_LABEL, QFont.Weight.Bold))
            p.drawText(_t.MARGIN_LEFT, y, _t.LBL_LOGS); y += 15
            ls = (app_info.LOG_DIR if len(app_info.LOG_DIR) <= _t.LOG_PATH_MAX_LEN
                  else "..." + app_info.LOG_DIR[-_t.LOG_PATH_TAIL:])
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_LOG_PATH))
            p.drawText(_t.MARGIN_LEFT, y, ls)

            # Eject button
            bx = W // 2 - _t.EJECT_BTN_W // 2
            by_ = H - _t.EJECT_BTN_MARGIN_BOTTOM
            bw_, bh_ = _t.EJECT_BTN_W, _t.EJECT_BTN_H
            self._btn_rect = (bx, by_, bw_, bh_)
            p.setBrush(QBrush(self.RED_HOV if self._btn_hover else self.RED_DIM))
            p.setPen(QPen(self.RED if self._btn_hover else self.RED_OUT, 1))
            p.drawRect(bx, by_, bw_, bh_)
            p.setPen(QPen(self.RED))
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_BUTTON, QFont.Weight.Bold))
            p.drawText(bx, by_, bw_, bh_, Qt.AlignmentFlag.AlignCenter, _t.LBL_EJECT)

            p.setPen(QPen(self.TXT_DIM))
            p.setFont(QFont(_t.FONT_FAMILY, _t.FONT_LABEL))
            p.end()

        @staticmethod
        def _in_rect(mx, my, rect):
            if not rect:
                return False
            rx, ry, rw, rh = rect
            return rx <= mx <= rx + rw and ry <= my <= ry + rh

        def mousePressEvent(self, e):
            if e.button() != Qt.MouseButton.LeftButton:
                return
            mx, my = e.position().x(), e.position().y()
            if self._in_rect(mx, my, self._btn_rect):
                self._do_quit(); return
            if self._in_rect(mx, my, self._local_rect):
                import webbrowser; webbrowser.open(f"http://localhost:{SERVER_PORT}"); return
            if self._in_rect(mx, my, self._net_rect):
                import webbrowser; webbrowser.open(f"http://{SERVER_IP}:{SERVER_PORT}"); return
            if self._in_rect(mx, my, self._min_rect):
                self._smooth_minimize(); return
            if self._in_rect(mx, my, self._set_rect):
                self._open_settings(); return
            if my < _t.HEADER_H:
                self._drag_pos = e.globalPosition().toPoint()

        def _open_settings(self):
            from PySide6.QtWidgets import (QDialog, QSpinBox, QVBoxLayout,
                                           QHBoxLayout, QPushButton, QLabel,
                                           QFrame, QAbstractSpinBox)
            dlg = QDialog(self)
            dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
            dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            dlg.setFixedWidth(340)
            drag_state: list = [None]

            dlg.setStyleSheet(f"""
                #root {{ background:{_t.BG}; border:1px solid {_t.ACCENT_DIM}; }}
                #header {{ background:{_t.BG2}; border-bottom:1px solid {_t.ACCENT_DIM}; }}
                #accentLine {{ background:{_t.ACCENT}; }}
                #title {{ color:{_t.TXT_WHITE}; font-family:'{_t.FONT_FAMILY}';
                          font-size:11px; font-weight:bold; letter-spacing:1px; }}
                #closeBtn {{ background:transparent; color:{_t.TXT_DIM};
                             border:none; font-size:14px; font-weight:bold;
                             min-width:28px; max-width:28px; min-height:22px; }}
                #closeBtn:hover {{ color:{_t.RED}; background:{_t.RED_DIM}; }}
                QLabel#fieldLbl {{ color:{_t.TXT_DIM}; font-family:'{_t.FONT_FAMILY}';
                                   font-size:8px; font-weight:bold; letter-spacing:1px;
                                   padding:0; background:transparent; }}
                QSpinBox {{ background:{_t.BG2}; color:{_t.TXT_WHITE};
                            selection-background-color:{_t.ACCENT_DIM};
                            selection-color:{_t.ACCENT};
                            border:1px solid {_t.ACCENT_DIM}; border-radius:2px;
                            padding:7px 10px; font-family:'{_t.FONT_MONO}';
                            font-size:13px; }}
                QSpinBox:focus {{ border:1px solid {_t.ACCENT}; }}
                QPushButton {{ background:{_t.BG2}; color:{_t.TXT_MID};
                               border:1px solid {_t.ACCENT_DIM}; border-radius:2px;
                               padding:8px 20px; font-family:'{_t.FONT_FAMILY}';
                               font-size:10px; font-weight:bold; letter-spacing:1px;
                               min-width:80px; }}
                QPushButton:hover {{ background:{_t.ACCENT_DIM}; color:{_t.ACCENT};
                                     border:1px solid {_t.ACCENT}; }}
                QPushButton#saveBtn {{ color:{_t.ACCENT}; border:1px solid {_t.ACCENT_DIM}; }}
                QPushButton#saveBtn:hover {{ background:{_t.ACCENT_DIM};
                                              border:1px solid {_t.ACCENT}; }}
            """)

            # Root frame (holds everything; styled background)
            root = QFrame(dlg); root.setObjectName("root")
            outer = QVBoxLayout(dlg); outer.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(root)
            rootLay = QVBoxLayout(root)
            rootLay.setContentsMargins(0, 0, 0, 0); rootLay.setSpacing(0)

            # Accent top line
            accent = QFrame(); accent.setObjectName("accentLine")
            accent.setFixedHeight(_t.ACCENT_LINE_H)
            rootLay.addWidget(accent)

            # Header with title + close
            header = QFrame(); header.setObjectName("header")
            header.setFixedHeight(34)
            hLay = QHBoxLayout(header)
            hLay.setContentsMargins(16, 0, 4, 0); hLay.setSpacing(0)
            title = QLabel("SETTINGS"); title.setObjectName("title")
            close_btn = QPushButton("\u2715"); close_btn.setObjectName("closeBtn")
            close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            hLay.addWidget(title); hLay.addStretch(1); hLay.addWidget(close_btn)
            rootLay.addWidget(header)

            # Drag handling on header
            def _hdr_press(e):
                if e.button() == Qt.MouseButton.LeftButton:
                    drag_state[0] = e.globalPosition().toPoint() - dlg.frameGeometry().topLeft()
            def _hdr_move(e):
                if drag_state[0] is not None and e.buttons() == Qt.MouseButton.LeftButton:
                    dlg.move(e.globalPosition().toPoint() - drag_state[0])
            def _hdr_release(_e):
                drag_state[0] = None
            header.mousePressEvent   = _hdr_press
            header.mouseMoveEvent    = _hdr_move
            header.mouseReleaseEvent = _hdr_release

            # Body
            body = QFrame()
            v = QVBoxLayout(body)
            v.setContentsMargins(22, 18, 22, 18); v.setSpacing(6)

            lbl1 = QLabel(f"LISTEN PORT  ({app_info.PORT_MIN}\u2013{app_info.PORT_MAX})")
            lbl1.setObjectName("fieldLbl")
            v.addWidget(lbl1)
            port_sp = QSpinBox()
            port_sp.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            port_sp.setRange(app_info.PORT_MIN, app_info.PORT_MAX)
            port_sp.setValue(int(config.APP_CONFIG["port"]))
            v.addWidget(port_sp)

            v.addSpacing(8)
            lbl2 = QLabel(f"BROADCAST INTERVAL  ({app_info.BROADCAST_MS_MIN}\u2013{app_info.BROADCAST_MS_MAX} MS)")
            lbl2.setObjectName("fieldLbl")
            v.addWidget(lbl2)
            bc_sp = QSpinBox()
            bc_sp.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            bc_sp.setRange(app_info.BROADCAST_MS_MIN, app_info.BROADCAST_MS_MAX)
            bc_sp.setValue(int(config.APP_CONFIG["broadcast_ms"]))
            v.addWidget(bc_sp)

            v.addSpacing(14)
            btns = QHBoxLayout(); btns.setSpacing(8)
            cancel_btn = QPushButton("CANCEL")
            ok_btn = QPushButton("SAVE"); ok_btn.setObjectName("saveBtn")
            ok_btn.setDefault(True)
            btns.addStretch(1); btns.addWidget(cancel_btn); btns.addWidget(ok_btn)
            v.addLayout(btns)
            rootLay.addWidget(body)

            close_btn.clicked.connect(dlg.reject)
            ok_btn.clicked.connect(dlg.accept)
            cancel_btn.clicked.connect(dlg.reject)

            # Center on parent
            pg = self.frameGeometry()
            dlg.adjustSize()
            dlg.move(pg.center().x() - dlg.width()//2, pg.center().y() - dlg.height()//2)

            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            old_port = int(config.APP_CONFIG["port"])
            new_port = port_sp.value()
            new_bcast = bc_sp.value()
            config.APP_CONFIG["port"] = new_port
            config.APP_CONFIG["broadcast_ms"] = new_bcast
            config.save(config.APP_CONFIG)
            logger.info(f"Settings saved: port={new_port}, broadcast_ms={new_bcast}")
            if new_port != old_port:
                self._show_restart_toast(new_port)

        def _show_restart_toast(self, new_port: int):
            from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                           QLabel, QFrame, QPushButton)
            dlg = QDialog(self)
            dlg.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
            dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            dlg.setStyleSheet(f"""
                #root {{ background:{_t.BG}; border:1px solid {_t.ACCENT_DIM}; }}
                #accentLine {{ background:{_t.ACCENT}; }}
                QLabel {{ color:{_t.TXT_WHITE}; font-family:'{_t.FONT_FAMILY}';
                          font-size:11px; background:transparent; }}
                #subtitle {{ color:{_t.TXT_DIM}; font-size:9px; }}
                QPushButton {{ background:{_t.BG2}; color:{_t.ACCENT};
                               border:1px solid {_t.ACCENT_DIM}; border-radius:2px;
                               padding:8px 24px; font-weight:bold; letter-spacing:1px;
                               font-size:10px; }}
                QPushButton:hover {{ background:{_t.ACCENT_DIM};
                                     border:1px solid {_t.ACCENT}; }}
            """)
            root = QFrame(dlg); root.setObjectName("root")
            outer = QVBoxLayout(dlg); outer.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(root)
            rl = QVBoxLayout(root); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(0)
            line = QFrame(); line.setObjectName("accentLine")
            line.setFixedHeight(_t.ACCENT_LINE_H); rl.addWidget(line)
            inner = QVBoxLayout(); inner.setContentsMargins(28, 20, 28, 18); inner.setSpacing(6)
            t1 = QLabel("RESTART REQUIRED")
            t1.setStyleSheet(f"color:{_t.ACCENT};font-weight:bold;letter-spacing:1px;font-size:11px;")
            t2 = QLabel(f"Port changed to {new_port}.")
            t3 = QLabel("Restart Falcon-Pad to apply."); t3.setObjectName("subtitle")
            inner.addWidget(t1); inner.addSpacing(4); inner.addWidget(t2); inner.addWidget(t3)
            inner.addSpacing(14)
            btn = QPushButton("OK"); btn.setDefault(True)
            row = QHBoxLayout(); row.addStretch(1); row.addWidget(btn); row.addStretch(1)
            inner.addLayout(row)
            rl.addLayout(inner)
            btn.clicked.connect(dlg.accept)
            pg = self.frameGeometry()
            dlg.adjustSize()
            dlg.move(pg.center().x() - dlg.width()//2, pg.center().y() - dlg.height()//2)
            dlg.exec()

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
            if self._set_rect:
                sx, sy, sw, sh = self._set_rect
                h3 = sx <= mx <= sx+sw and sy <= my <= sy+sh
                if h3 != self._set_hover:
                    self._set_hover = h3; self.update()
            # URL hover state
            lh = self._in_rect(mx, my, self._local_rect)
            nh = self._in_rect(mx, my, self._net_rect)
            if lh != self._local_hover or nh != self._net_hover:
                self._local_hover = lh; self._net_hover = nh; self.update()
            over_click = lh or nh or self._set_hover or self._min_hover or self._btn_hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if over_click else Qt.CursorShape.ArrowCursor)

        def mouseReleaseEvent(self, _e):
            self._drag_pos = None

        def leaveEvent(self, _e):
            changed = self._btn_hover or self._min_hover or self._set_hover or self._local_hover or self._net_hover
            self._btn_hover = False; self._min_hover = False; self._set_hover = False
            self._local_hover = False; self._net_hover = False
            if changed:
                self.update()

        def keyPressEvent(self, e):
            if e.key() == Qt.Key.Key_F4 and e.modifiers() == Qt.KeyboardModifier.AltModifier:
                self._do_quit()

        def _smooth_minimize(self):
            self._fade_step = 0
            self._fade_timer = QTimer(self)
            self._fade_timer.setInterval(15)
            self._fade_timer.timeout.connect(self._fade_tick)
            self._fade_timer.start()

        def _fade_tick(self):
            self._fade_step += 1
            opacity = max(0.0, 1.0 - self._fade_step / 12.0)
            self.setWindowOpacity(opacity)
            if self._fade_step >= 12:
                self._fade_timer.stop()
                self.showMinimized()
                self.setWindowOpacity(1.0)

        def _do_quit(self):
            self._timer.stop()
            self.close()
            qapp = QApplication.instance()
            if qapp:
                qapp.quit()

    _app = QApplication(sys.argv)
    _app.setApplicationName(app_info.SHORT)
    _app.setApplicationVersion(app_info.VERSION)
    _ico_path = os.path.join(app_info.ASSETS_DIR, app_info.ICON_FILENAME)
    if os.path.exists(_ico_path):
        _app.setWindowIcon(QIcon(_ico_path))
    _win = FalconPadWindow()
    _app.exec()
