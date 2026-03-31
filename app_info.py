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
WEBSITE = "https://www.falcon-charts.com"
GITHUB  = "https://github.com/riesu/falcon-pad"
LICENSE = "GNU GPL v3"
BMS     = "Falcon BMS 4.38"

SHORT   = "Falcon-Pad"

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
