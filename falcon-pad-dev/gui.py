# -*- coding: utf-8 -*-
"""
falcon_pad.gui — PySide6 splash / status window (optional).

Shows BMS connection status, server URLs, and a STOP button.
If PySide6 is not installed, this module is silently skipped.

Public API:
    run_gui(bms, **kwargs) — blocks on QApplication.exec()

Copyright (C) 2024  Riesu — GNU GPL v3
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sharedmem import BMSSharedMemory

logger = logging.getLogger(__name__)


import app_info


def run_gui(bms: "BMSSharedMemory", *,
            app_version: str = app_info.VERSION,
            app_author: str = app_info.AUTHOR,
            server_ip: str = "0.0.0.0",
            server_port: int = 8000,
            log_dir: str = "logs",
            images_dir: str = app_info.IMAGES_DIR) -> None:
    """
    Launch the PySide6 splash window. Blocks until closed.
    Raises SystemExit(0) if PySide6 is not available.
    """
    try:
        from PySide6.QtWidgets import QApplication, QWidget  # type: ignore[import-untyped]
        from PySide6.QtCore import Qt, QTimer                 # type: ignore[import-untyped]
        from PySide6.QtGui import (QPainter, QColor, QPen,    # type: ignore[import-untyped]
                                   QFont, QPixmap, QIcon, QBrush)
    except ImportError:
        logger.error("PySide6 not found — pip install PySide6")
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
            self.setWindowFlags(
                Qt.WindowType.Window |
                Qt.WindowType.FramelessWindowHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.setWindowTitle(app_info.NAME)
            _ico = os.path.join(images_dir, "falcon_pad.ico")
            if os.path.exists(_ico):
                self.setWindowIcon(QIcon(_ico))
            screen = QApplication.primaryScreen().availableGeometry()
            self.move((screen.width() - self.W) // 2,
                      (screen.height() - self.H) // 2)
            self._logo = None
            _lp = os.path.join(images_dir, "logo_app.png")
            if os.path.exists(_lp):
                px = QPixmap(_lp)
                if not px.isNull():
                    self._logo = px.scaled(
                        64, 64,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
            self._drag_pos = None
            self._btn_hover = False
            self._min_hover = False
            self._btn_rect = None
            self._min_rect = None
            self._bms_ok = False
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
            except (OSError, RuntimeError):
                pass  # SHM access may fail transiently

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            W, H = self.W, self.H
            p.fillRect(0, 0, W, H, self.BG)
            p.fillRect(0, 0, W, 80, self.BG2)
            p.fillRect(0, 0, W, 3, self.ACCENT)
            p.setPen(QPen(self.ACCENT_DIM, 1))
            p.drawRect(0, 0, W - 1, H - 1)
            p.drawLine(20, 80, W - 20, 80)
            p.drawLine(20, H - 66, W - 20, H - 66)
            # Minimize button
            rx, ry, rw, rh = W - 36, 10, 24, 18
            self._min_rect = (rx, ry, rw, rh)
            mc = self.TXT_MID if self._min_hover else self.TXT_DIM
            p.setPen(QPen(mc, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rx, ry, rw, rh)
            p.setPen(QPen(mc, 2))
            p.drawLine(rx + 5, ry + rh // 2, rx + rw - 5, ry + rh // 2)
            # Logo + title
            tx = 20
            if self._logo:
                p.drawPixmap(12, 8, self._logo)
                tx = 88
            p.setPen(QPen(self.ACCENT))
            p.setFont(QFont("Consolas", 15, QFont.Weight.Bold))
            p.drawText(tx, 8, W - tx - 44, 40,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "FALCON-PAD")
            p.setPen(QPen(self.TXT_DIM))
            p.setFont(QFont("Consolas", 8))
            p.drawText(tx, 48, W - tx - 44, 20,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       f"v{app_version}  ·  by {app_author}")
            # URLs
            y = 96
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
            p.setPen(QPen(self.TXT_DIM))
            p.drawText(22, y, "LOCAL"); y += 17
            p.setFont(QFont("Consolas", 11))
            p.setPen(QPen(self.ACCENT))
            p.drawText(22, y, f"http://localhost:{server_port}"); y += 25
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
            p.setPen(QPen(self.TXT_DIM))
            p.drawText(22, y, "NETWORK  —  Tablet / Mobile"); y += 17
            p.setFont(QFont("Consolas", 11))
            p.setPen(QPen(self.BLUE))
            p.drawText(22, y, f"http://{server_ip}:{server_port}"); y += 25
            # BMS status
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
            p.setPen(QPen(self.TXT_DIM))
            p.drawText(22, y, "FALCON BMS 4.38"); y += 17
            dc = self.ACCENT if self._bms_ok else self.RED
            p.setBrush(QBrush(dc))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(22, y - 9, 10, 10)
            p.setPen(QPen(dc))
            p.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            p.drawText(38, y, "CONNECTED" if self._bms_ok else "NOT DETECTED"); y += 25
            # Logs
            p.setPen(QPen(self.TXT_DIM))
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
            p.drawText(22, y, "LOGS"); y += 15
            ls = log_dir if len(log_dir) <= 54 else "…" + log_dir[-52:]
            p.setFont(QFont("Consolas", 8))
            p.drawText(22, y, ls)
            # Stop button
            bx, by_, bw_, bh_ = W // 2 - 72, H - 52, 144, 28
            self._btn_rect = (bx, by_, bw_, bh_)
            p.setBrush(QBrush(self.RED_HOV if self._btn_hover else self.RED_DIM))
            p.setPen(QPen(self.RED if self._btn_hover else self.RED_OUT, 1))
            p.drawRect(bx, by_, bw_, bh_)
            p.setPen(QPen(self.RED))
            p.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
            p.drawText(bx, by_, bw_, bh_, Qt.AlignmentFlag.AlignCenter, "■  STOP")
            p.setPen(QPen(self.TXT_DIM))
            p.setFont(QFont("Consolas", 7))
            p.drawText(0, H - 13, W, 12, Qt.AlignmentFlag.AlignCenter,
                       "Server will be stopped")
            p.end()

        def mousePressEvent(self, e):
            if e.button() != Qt.MouseButton.LeftButton:
                return
            mx, my = e.position().x(), e.position().y()
            if self._btn_rect:
                bx, by_, bw_, bh_ = self._btn_rect
                if bx <= mx <= bx + bw_ and by_ <= my <= by_ + bh_:
                    self._do_quit()
                    return
            if self._min_rect:
                rx, ry, rw, rh = self._min_rect
                if rx <= mx <= rx + rw and ry <= my <= ry + rh:
                    self.showMinimized()
                    return
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
                h = bx <= mx <= bx + bw_ and by_ <= my <= by_ + bh_
                if h != self._btn_hover:
                    self._btn_hover = h
                    self.update()
            if self._min_rect:
                rx, ry, rw, rh = self._min_rect
                h2 = rx <= mx <= rx + rw and ry <= my <= ry + rh
                if h2 != self._min_hover:
                    self._min_hover = h2
                    self.update()

        def mouseReleaseEvent(self, _e):
            self._drag_pos = None

        def leaveEvent(self, _e):
            if self._btn_hover or self._min_hover:
                self._btn_hover = False
                self._min_hover = False
                self.update()

        def keyPressEvent(self, e):
            if (e.key() == Qt.Key.Key_F4
                    and e.modifiers() == Qt.KeyboardModifier.AltModifier):
                self._do_quit()

        def _do_quit(self):
            self._timer.stop()
            self.close()
            os.kill(os.getpid(), 9)

    _app = QApplication([])
    _app.setApplicationName(app_info.NAME)
    _app.setApplicationVersion(app_version)
    _win = FalconPadWindow()
    _app.exec()
