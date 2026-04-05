# -*- coding: utf-8 -*-
"""Tests for tacview_server.py — detection and config toggle."""

import os
import tempfile
import pytest

import app_info
import tacview_server


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset module state before each test."""
    tacview_server._bms_install_dir = None
    tacview_server._exe_found = False
    tacview_server._enabled = None
    tacview_server._user_cfg_path = None
    yield


@pytest.fixture
def bms_tree(tmp_path):
    """Create a minimal BMS directory tree."""
    bin_dir = tmp_path / "Bin" / "x64"
    bin_dir.mkdir(parents=True)
    cfg_dir = tmp_path / "User" / "Config"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / app_info.BMS_USER_CFG_FILENAME
    cfg_file.write_text("set g_bTacviewRealTime 1\n", encoding="utf-8")
    return tmp_path


class TestDetect:
    def test_exe_not_found(self, bms_tree):
        result = tacview_server.detect(str(bms_tree))
        assert result["exe_found"] is False
        assert result["bms_dir"] == str(bms_tree)

    def test_exe_found(self, bms_tree):
        exe = bms_tree / "Bin" / "x64" / app_info.TACVIEW_SERVER_EXE
        exe.write_text("fake", encoding="utf-8")
        result = tacview_server.detect(str(bms_tree))
        assert result["exe_found"] is True

    def test_config_not_set(self, bms_tree):
        result = tacview_server.detect(str(bms_tree))
        assert result["enabled"] is None

    def test_config_enabled(self, bms_tree):
        cfg = bms_tree / "User" / "Config" / app_info.BMS_USER_CFG_FILENAME
        cfg.write_text(f"set {app_info.TACVIEW_SERVER_CFG_KEY} 1\n", encoding="utf-8")
        result = tacview_server.detect(str(bms_tree))
        assert result["enabled"] is True

    def test_config_disabled(self, bms_tree):
        cfg = bms_tree / "User" / "Config" / app_info.BMS_USER_CFG_FILENAME
        cfg.write_text(f"set {app_info.TACVIEW_SERVER_CFG_KEY} 0\n", encoding="utf-8")
        result = tacview_server.detect(str(bms_tree))
        assert result["enabled"] is False

    def test_no_user_cfg(self, tmp_path):
        result = tacview_server.detect(str(tmp_path))
        assert result["user_cfg"] is None
        assert result["enabled"] is None

    def test_github_url_in_status(self, bms_tree):
        result = tacview_server.detect(str(bms_tree))
        assert result["github"] == app_info.TACVIEW_SERVER_GITHUB


class TestSetEnabled:
    def test_enable_with_exe(self, bms_tree):
        exe = bms_tree / "Bin" / "x64" / app_info.TACVIEW_SERVER_EXE
        exe.write_text("fake", encoding="utf-8")
        cfg = bms_tree / "User" / "Config" / app_info.BMS_USER_CFG_FILENAME
        cfg.write_text("set g_bTacviewRealTime 1\n", encoding="utf-8")
        tacview_server.detect(str(bms_tree))

        result = tacview_server.set_enabled(True)
        assert result["enabled"] is True
        assert "error" not in result

        # Verify file was written
        content = cfg.read_text(encoding="utf-8")
        assert f"set {app_info.TACVIEW_SERVER_CFG_KEY} 1" in content

    def test_disable(self, bms_tree):
        exe = bms_tree / "Bin" / "x64" / app_info.TACVIEW_SERVER_EXE
        exe.write_text("fake", encoding="utf-8")
        cfg = bms_tree / "User" / "Config" / app_info.BMS_USER_CFG_FILENAME
        cfg.write_text(f"set {app_info.TACVIEW_SERVER_CFG_KEY} 1\n", encoding="utf-8")
        tacview_server.detect(str(bms_tree))

        result = tacview_server.set_enabled(False)
        assert result["enabled"] is False
        content = cfg.read_text(encoding="utf-8")
        assert f"set {app_info.TACVIEW_SERVER_CFG_KEY} 0" in content

    def test_enable_without_exe_fails(self, bms_tree):
        cfg = bms_tree / "User" / "Config" / app_info.BMS_USER_CFG_FILENAME
        cfg.write_text("", encoding="utf-8")
        tacview_server.detect(str(bms_tree))

        result = tacview_server.set_enabled(True)
        assert "error" in result

    def test_enable_without_cfg_fails(self, tmp_path):
        tacview_server.detect(str(tmp_path))
        result = tacview_server.set_enabled(True)
        assert "error" in result

    def test_insert_key_when_missing(self, bms_tree):
        exe = bms_tree / "Bin" / "x64" / app_info.TACVIEW_SERVER_EXE
        exe.write_text("fake", encoding="utf-8")
        cfg = bms_tree / "User" / "Config" / app_info.BMS_USER_CFG_FILENAME
        cfg.write_text("set g_bTacviewRealTime 1\n", encoding="utf-8")
        tacview_server.detect(str(bms_tree))

        tacview_server.set_enabled(True)
        content = cfg.read_text(encoding="utf-8")
        assert f"set {app_info.TACVIEW_SERVER_CFG_KEY} 1" in content

    def test_update_existing_key(self, bms_tree):
        exe = bms_tree / "Bin" / "x64" / app_info.TACVIEW_SERVER_EXE
        exe.write_text("fake", encoding="utf-8")
        cfg = bms_tree / "User" / "Config" / app_info.BMS_USER_CFG_FILENAME
        cfg.write_text(
            f"set g_bTacviewRealTime 1\nset {app_info.TACVIEW_SERVER_CFG_KEY} 0\nset g_nTacviewPort 42674\n",
            encoding="utf-8",
        )
        tacview_server.detect(str(bms_tree))

        tacview_server.set_enabled(True)
        content = cfg.read_text(encoding="utf-8")
        assert f"set {app_info.TACVIEW_SERVER_CFG_KEY} 1" in content
        # Other keys preserved
        assert "set g_bTacviewRealTime 1" in content
        assert "set g_nTacviewPort 42674" in content


class TestStatus:
    def test_initial_status(self):
        s = tacview_server.status()
        assert s["exe_found"] is False
        assert s["enabled"] is None
        assert s["bms_dir"] is None
        assert "github" in s
        assert "info" in s
