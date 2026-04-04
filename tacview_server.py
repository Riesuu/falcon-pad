# -*- coding: utf-8 -*-
"""
falcon_pad.tacview_server — Tacview-server.exe detection and configuration.

tacview-server.exe is an external ACMI compressor from UOAF that reduces
ACMI recording file sizes by up to 10x without losing data.
It must be placed in BMS Bin/x64 and enabled via g_bExternalTacview 1.

Public API:
    detect(bms_install_dir)  — detect exe + read config
    set_enabled(enabled)     — toggle g_bExternalTacview in User.cfg
    status()                 — current detection status dict

Copyright (C) 2024  Riesu — GNU GPL v3
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

import app_info

logger = logging.getLogger(__name__)

# ── State ───────────────────────────────────────────────────────────────────
_bms_install_dir: Optional[str] = None
_exe_found: bool = False
_enabled: Optional[bool] = None
_user_cfg_path: Optional[str] = None


def _find_user_cfg(install_dir: str) -> Optional[str]:
    """Locate Falcon BMS User.cfg in the install directory."""
    path = os.path.join(install_dir, *app_info.BMS_USER_CFG_SUB,
                        app_info.BMS_USER_CFG_FILENAME)
    return path if os.path.isfile(path) else None


def _read_cfg_value(cfg_path: str, key: str) -> Optional[str]:
    """Read a 'set key value' line from a BMS .cfg file."""
    try:
        with open(cfg_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"set {key} "):
                    return line.split(None, 2)[2]
    except Exception as e:
        logger.debug(f"tacview_server: read cfg: {e}")
    return None


def _write_cfg_value(cfg_path: str, key: str, value: str) -> bool:
    """Set or insert a 'set key value' line in a BMS .cfg file."""
    try:
        with open(cfg_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        pattern = re.compile(rf"^set\s+{re.escape(key)}\s+")
        found = False
        for i, line in enumerate(lines):
            if pattern.match(line.strip()):
                lines[i] = f"set {key} {value}\n"
                found = True
                break

        if not found:
            lines.append(f"\nset {key} {value}\n")

        with open(cfg_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception as e:
        logger.error(f"tacview_server: write cfg: {e}")
        return False


def detect(bms_install_dir: str) -> dict:
    """
    Detect tacview-server.exe and read its config from User.cfg.

    Args:
        bms_install_dir: BMS installation root (e.g. C:/Falcon BMS 4.38)

    Returns status dict.
    """
    global _bms_install_dir, _exe_found, _enabled, _user_cfg_path

    _bms_install_dir = bms_install_dir

    # Check for exe in Bin/x64
    exe_path = os.path.join(bms_install_dir, *app_info.TACVIEW_SERVER_BIN_SUB,
                            app_info.TACVIEW_SERVER_EXE)
    _exe_found = os.path.isfile(exe_path)

    # Read config
    _user_cfg_path = _find_user_cfg(bms_install_dir)
    if _user_cfg_path:
        raw = _read_cfg_value(_user_cfg_path, app_info.TACVIEW_SERVER_CFG_KEY)
        _enabled = (raw == "1") if raw is not None else None
    else:
        _enabled = None

    logger.info(f"Tacview-server: exe={'found' if _exe_found else 'missing'}, "
                f"enabled={_enabled}, cfg={_user_cfg_path}")
    return status()


def set_enabled(enabled: bool) -> dict:
    """
    Toggle g_bExternalTacview in User.cfg.

    Returns updated status dict, or status with error key on failure.
    """
    global _enabled

    if not _user_cfg_path:
        return {**status(), "error": "User.cfg not found"}

    if not _exe_found and enabled:
        return {**status(), "error": f"{app_info.TACVIEW_SERVER_EXE} not found in BMS Bin/x64"}

    value = "1" if enabled else "0"
    ok = _write_cfg_value(_user_cfg_path, app_info.TACVIEW_SERVER_CFG_KEY, value)
    if ok:
        _enabled = enabled
        logger.info(f"Tacview-server: {'enabled' if enabled else 'disabled'}")
    else:
        return {**status(), "error": "Failed to write User.cfg"}

    return status()


def status() -> dict:
    """Return current tacview-server detection status."""
    return {
        "exe_found": _exe_found,
        "enabled": _enabled,
        "bms_dir": _bms_install_dir,
        "user_cfg": _user_cfg_path,
        "github": app_info.TACVIEW_SERVER_GITHUB,
        "info": "ACMI compression up to 10x — requires BMS restart to apply",
    }
