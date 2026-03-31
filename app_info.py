# -*- coding: utf-8 -*-
"""
Falcon-Pad — Application identity constants.

Single source of truth. Import from here everywhere.
Change version/author/URLs here ONCE — propagates to Python, logs, Qt GUI, and frontend.
"""

NAME    = "Falcon-Pad || Tactical Companion for BMS"
VERSION = "0.3"
AUTHOR  = "Riesu"
CONTACT = "contact@falcon-charts.com"
WEBSITE = "https://pad.falcon-charts.com"
CHARTS  = "https://www.falcon-charts.com"
GITHUB  = "https://github.com/riesu/falcon-pad"
LICENSE = "GNU GPL v3"
BMS     = "Falcon BMS 4.38"

SHORT   = "Falcon-Pad"

# ── Network defaults ─────────────────────────────────────────────────────────
DEFAULT_PORT         = 8000
DEFAULT_HOST         = "0.0.0.0"
DEFAULT_BROADCAST_MS = 200
BROADCAST_MS_MIN     = 50
BROADCAST_MS_MAX     = 2000

# ── TRTT (Tacview Real-Time Telemetry) ───────────────────────────────────────
TRTT_HOST              = "127.0.0.1"
TRTT_PORT              = 42674
TRTT_HANDSHAKE_TIMEOUT = 5.0
TRTT_INITIAL_TIMEOUT   = 10.0
TRTT_RECEIVE_TIMEOUT   = 30.0
TRTT_RECONNECT_SLEEP   = 5

# ── BMS detection ────────────────────────────────────────────────────────────
BMS_REGISTRY_BASE   = r"SOFTWARE\WOW6432Node\Benchmark Sims"
BMS_REGISTRY_PREFIX = "falcon bms"
BMS_REGISTRY_KEY    = "InstallDir"
BMS_USER_CONFIG_SUB = ("User", "Config")
BMS_RECONNECT_S     = 5.0

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_FILENAME     = "falcon_pad.log"
LOG_MAX_BYTES    = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3

# ── Briefing ─────────────────────────────────────────────────────────────────
BRIEFING_MAX_MB      = 50
BRIEFING_ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".html", ".htm"}

# ── Mission / distances ──────────────────────────────────────────────────────
FT_TO_M           = 0.3048
FT_TO_NM_DIVISOR  = 6076.12
GREAT_CIRCLE_NM   = 3440.065
AIRPORT_SEARCH_NM = 5.0
ACMI_CONTACT_NM   = 240.0

import os as _os, sys as _sys

def _resolve_base_dir() -> str:
    """Retourne le dossier racine du projet — fonctionne en dev et en .exe PyInstaller."""
    if getattr(_sys, 'frozen', False):
        return _os.path.dirname(_sys.executable)
    return _os.path.dirname(_os.path.abspath(__file__))

def _resolve_bundle_dir() -> str:
    """Dossier contenant les fichiers embarqués (frontend, data). _MEIPASS en --onefile."""
    if getattr(_sys, 'frozen', False):
        return getattr(_sys, '_MEIPASS', _os.path.dirname(_sys.executable))
    return _os.path.dirname(_os.path.abspath(__file__))

BASE_DIR     = _resolve_base_dir()
BUNDLE_DIR   = _resolve_bundle_dir()
CONFIG_DIR   = _os.path.join(BASE_DIR, "config")
LOG_DIR      = _os.path.join(BASE_DIR, "logs")
BRIEFING_DIR = _os.path.join(BASE_DIR, "briefing")
CONFIG_FILE  = _os.path.join(CONFIG_DIR, "falcon_pad_config.json")

# Créer les dossiers nécessaires
for _d in (CONFIG_DIR, LOG_DIR, BRIEFING_DIR):
    _os.makedirs(_d, exist_ok=True)
