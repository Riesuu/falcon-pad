# -*- coding: utf-8 -*-
"""
falcon_pad.ui_prefs — UI preference persistence.

Public API:
    DEFAULTS  — default preference dict
    prefs     — live dict (mutate in place, then call save())
    load()    — load from disk (returns dict)
    save(p)   — persist dict to disk

Copyright (C) 2024  Riesu — GNU GPL v3
"""

from __future__ import annotations

import json
import logging
import os

import app_info

logger = logging.getLogger(__name__)

FILE = os.path.join(app_info.CONFIG_DIR, "ui_prefs.json")

DEFAULTS: dict = {
    "active_color":     "#3b82f6",
    "layer":            "dark",
    "ppt_visible":      False,
    "airports_visible": True,
    "runways_visible":  True,
    "ap_name_visible":  False,
    # Map element colors & sizes
    "color_draw":       "#3b82f6",  "size_draw":      3,
    "color_stpt":       "#e2e8f0", "size_stpt":      5,   "size_stpt_line":  2,
    "color_fplan":      "#f59e0b", "size_fplan":     4,   "size_fplan_line": 2,
    "color_ppt":        "#ef4444", "size_ppt":       1.2, "size_ppt_dot":    5,
    "color_bull":       "#60a5fa", "size_bull":      8,  "bull_visible":   True,
    # HSD line colors L1–L4
    "color_hsd_l1":     "#4ade80",
    "color_hsd_l2":     "#60a5fa",
    "color_hsd_l3":     "#f59e0b",
    "color_hsd_l4":     "#f87171",
    # Runway calibration & annotations
    "rwy_offsets":      "{}",
    "annotations":      "[]",
}


def load() -> dict:
    try:
        if os.path.exists(FILE):
            with open(FILE, encoding="utf-8") as f:
                saved = json.load(f)
            p = dict(DEFAULTS)
            p.update({k: v for k, v in saved.items() if k in DEFAULTS})
            return p
        p = dict(DEFAULTS)
        save(p)
        return p
    except Exception as e:
        logger.error(f"ui_prefs load: {e}", exc_info=True)
        return dict(DEFAULTS)


def save(p: dict) -> None:
    try:
        os.makedirs(os.path.dirname(FILE), exist_ok=True)
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(p, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"ui_prefs save: {e}", exc_info=True)


prefs: dict = load()
