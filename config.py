# -*- coding: utf-8 -*-
"""
falcon_pad.config — App configuration persistence and logging setup.

Public API:
    APP_CONFIG   — dict with live config values
    BRIEFING_DIR — personal briefing directory (fixed at app root /personal)
    LOG_FILE     — path to rotating log file
    load()       — reload config from disk
    save(cfg)    — persist config to disk
    log_sep(t)   — print a separator to the log

Copyright (C) 2024  Riesu — GNU GPL v3
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

import app_info

# ── Defaults ─────────────────────────────────────────────────────────────────

_DEFAULTS: dict = {
    "port":         app_info.DEFAULT_PORT,
    "broadcast_ms": app_info.DEFAULT_BROADCAST_MS,
    "theme":        "dark",
}

# ── Persistence ───────────────────────────────────────────────────────────────

def load() -> dict:
    try:
        if os.path.exists(app_info.CONFIG_FILE):
            with open(app_info.CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            cfg = dict(_DEFAULTS)
            cfg.update({k: v for k, v in saved.items() if k in _DEFAULTS})
            return cfg
    except Exception as e:
        logging.getLogger(__name__).warning(f"config load: {e}")
    return dict(_DEFAULTS)


def save(cfg: dict) -> None:
    try:
        os.makedirs(os.path.dirname(app_info.CONFIG_FILE), exist_ok=True)
        with open(app_info.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logging.getLogger(__name__).error(f"config save failed: {e}")


APP_CONFIG:   dict = load()
BRIEFING_DIR: str  = app_info.BRIEFING_DIR
os.makedirs(BRIEFING_DIR, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_FILE = os.path.join(app_info.LOG_DIR, app_info.LOG_FILENAME)


class _Fmt(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        return f"[{ts}] [{r.levelname:<8}] {r.getMessage()}"


_fh = RotatingFileHandler(LOG_FILE, maxBytes=app_info.LOG_MAX_BYTES, backupCount=app_info.LOG_BACKUP_COUNT, encoding="utf-8")
_fh.setLevel(logging.INFO)
_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_fh.setFormatter(_Fmt())
_ch.setFormatter(_Fmt())
logging.basicConfig(level=logging.INFO, handlers=[_fh, _ch])

_log = logging.getLogger(__name__)
_log.info(f"Logging initialized — {LOG_FILE}")


def log_sep(t: str = "") -> None:
    _log.info("=" * 60)
    if t:
        _log.info(f"  {t}")
        _log.info("=" * 60)
