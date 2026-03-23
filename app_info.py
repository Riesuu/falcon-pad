# -*- coding: utf-8 -*-
"""
Falcon-Pad — Application identity constants & directory paths.

Single source of truth. Import from here everywhere.
Change version/author/URLs/paths here ONCE — propagates to Python, logs, Qt GUI, and frontend.
"""

import os
import sys
from datetime import datetime

# ── Identity ─────────────────────────────────────────────────────────────
NAME    = "Falcon-Pad || Tactical Companion for BMS"
SHORT   = "Falcon-Pad"
VERSION = "0.3"
AUTHOR  = "Riesu"
CONTACT = "contact@falcon-charts.com"
WEBSITE = "https://pad.falcon-charts.com"
GITHUB  = "https://github.com/riesu/falcon-pad"
LICENSE = "GNU GPL v3"
BMS     = "Falcon BMS 4.38"

# ── Directory resolution ──────────────────────────────────────────────────
# Structure cible : falcon-pad/ logs/ briefing/ config/ frontend/images/
def _resolve_base_dir() -> str:
    if getattr(sys, "frozen", False):
        candidate = os.path.dirname(os.path.abspath(sys.executable))
    else:
        candidate = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(candidate).lower() == "falcon-pad":
        return candidate
    fp_dir = os.path.join(candidate, "falcon-pad")
    os.makedirs(fp_dir, exist_ok=True)
    return fp_dir

BASE_DIR     = _resolve_base_dir()
IMAGES_DIR   = os.path.join(BASE_DIR, "frontend", "images")
LOG_DIR      = os.path.join(BASE_DIR, "logs")
BRIEFING_DIR = os.path.join(BASE_DIR, "briefing")
CONFIG_DIR   = os.path.join(BASE_DIR, "config")
CONFIG_FILE  = os.path.join(CONFIG_DIR, "falcon_pad_config.json")

# Créer les dossiers au premier import
for _d in (IMAGES_DIR, LOG_DIR, BRIEFING_DIR, CONFIG_DIR):
    os.makedirs(_d, exist_ok=True)
