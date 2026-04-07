# -*- coding: utf-8 -*-
"""
falcon_pad.ui_theme — Qt GUI theme constants for the desktop tray window.

All colors, fonts, layout dimensions, labels and timings live here.
Import from here in falcon_pad.py — nothing hardcoded in the widget.

Copyright (C) 2026  Riesu — GNU GPL v3
"""

# ── Window ──────────────────────────────────────────────────────────────────
WIN_W = 440
WIN_H = 400
HEADER_H = 80
ACCENT_LINE_H = 3

# ── Colors (matched to logo: navy, green, white) ────────────────────────────
BG         = "#060a12"
BG2        = "#0b1220"
ACCENT     = "#4ade80"
ACCENT_DIM = "#0f2b18"
RED        = "#c0392b"
RED_DIM    = "#1a0808"
RED_HOV    = "#3d1010"
RED_OUT    = "#7f2222"
BLUE       = "#60a5fa"
GREEN      = "#4ade80"
TXT_DIM    = "#64748b"
TXT_MID    = "#94a3b8"
TXT_WHITE  = "#e2e8f0"

# ── Fonts ───────────────────────────────────────────────────────────────────
FONT_FAMILY    = "Segoe UI"
FONT_MONO      = "Consolas"
FONT_TITLE     = 16
FONT_SUBTITLE  = 9
FONT_LABEL     = 8
FONT_VALUE     = 12
FONT_STATUS    = 11
FONT_BUTTON    = 12
FONT_LOG_PATH  = 8

# ── Layout (pixel offsets) ──────────────────────────────────────────────────
MARGIN_LEFT     = 22
TITLE_X         = 20
TITLE_Y         = 8
TITLE_H         = 40
SUBTITLE_Y      = 48
SUBTITLE_H      = 20
CONTENT_START_Y = 96
LINE_LABEL_H    = 19
LINE_VALUE_H    = 28
STATUS_DOT_R    = 10

# ── Minimize button ────────────────────────────────────────────────────────
MIN_BTN_MARGIN_R = 80
MIN_BTN_Y        = 10
MIN_BTN_W        = 24
MIN_BTN_H        = 18

# ── Eject button ───────────────────────────────────────────────────────────
EJECT_BTN_W = 144
EJECT_BTN_H = 28
EJECT_BTN_MARGIN_BOTTOM = 52

# ── Timers (ms) ────────────────────────────────────────────────────────────
BMS_POLL_MS         = 3000
BMS_POLL_INITIAL_MS = 600

# ── Labels ──────────────────────────────────────────────────────────────────
LBL_TITLE       = "FALCON-PAD"
LBL_LOCAL       = "LOCAL"
LBL_NETWORK     = "NETWORK"
LBL_LOGS        = "LOGS"
LBL_CONNECTED   = "CONNECTED"
LBL_NOT_DETECTED = "NOT DETECTED"
LBL_EJECT       = "\u25a0  PUSH TO EJECT"
LOG_PATH_MAX_LEN = 54
LOG_PATH_TAIL    = 52

# ── DOCX viewer CSS (used in routes.py for .docx → HTML conversion) ────────
DOCX_CSS = (
    "body{background:#060a12;color:#cbd5e1;font-family:system-ui,-apple-system,"
    "'Segoe UI',sans-serif;max-width:860px;margin:0 auto;padding:32px 24px;"
    "font-size:15px;line-height:1.7}"
    "h1{font-size:22px;color:#fbbf24}h2{font-size:16px;color:#94a3b8}"
    "h3{font-size:13px;color:#4ade80}p{margin:4px 0;color:#94a3b8}"
    "strong{color:#e2e8f0}em{color:#fbbf24}"
)
DOCX_ERROR_STYLE = "background:#060a12;color:#ef4444;font-family:monospace;padding:40px"
