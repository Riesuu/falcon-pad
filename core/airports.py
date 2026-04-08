# -*- coding: utf-8 -*-
"""
falcon_pad.airports — Dynamic airport data loading per theater.

Public API:
    load(theater_name) → list   cached JSON load for the given theater

Copyright (C) 2026  Riesu — GNU GPL v3
"""

from __future__ import annotations

import json
import logging
import os

import app_info

logger = logging.getLogger(__name__)

_DIR = os.path.join(app_info.BUNDLE_DIR, "data", "airports")

_FILES: dict = {
    "korea kto": "korea.json",
    "balkans":   "balkans.json",
    "israel":    "israel.json",
    "hellas":    "hto.json",
}

_cache: dict = {}


def load(theater_name: str) -> list:
    """Return airport list for *theater_name*, loading from JSON on first call."""
    key = theater_name.lower()
    if key in _cache:
        return _cache[key]
    filename = _FILES.get(key)
    if not filename:
        return []
    path = os.path.join(_DIR, filename)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _cache[key] = data
        return data
    except Exception as e:
        logger.warning(f"airports: cannot load {path}: {e}")
        return []
