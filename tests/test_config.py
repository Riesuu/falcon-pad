# -*- coding: utf-8 -*-
"""Tests — config.py : configuration persistence and logging."""
import json
import os

import pytest

import config


class TestLoad:
    def test_returns_dict(self):
        result = config.load()
        assert isinstance(result, dict)

    def test_has_all_default_keys(self):
        result = config.load()
        for key in ("port", "briefing_dir", "broadcast_ms", "theme"):
            assert key in result

    def test_unknown_keys_ignored(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text(json.dumps({"port": 9999, "UNKNOWN": "bad"}))
        monkeypatch.setattr("config.app_info.CONFIG_FILE", str(cfg_file))
        result = config.load()
        assert result["port"] == 9999
        assert "UNKNOWN" not in result

    def test_corrupt_json_returns_defaults(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text("{corrupt!!!")
        monkeypatch.setattr("config.app_info.CONFIG_FILE", str(cfg_file))
        result = config.load()
        assert result["port"] == 8000

    def test_missing_file_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.app_info.CONFIG_FILE",
                            str(tmp_path / "nope.json"))
        result = config.load()
        assert result == config._DEFAULTS


class TestSave:
    def test_save_creates_file(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "sub" / "cfg.json"
        monkeypatch.setattr("config.app_info.CONFIG_FILE", str(cfg_file))
        config.save({"port": 1234})
        assert cfg_file.exists()
        assert json.loads(cfg_file.read_text())["port"] == 1234

    def test_save_invalid_path_no_crash(self, monkeypatch):
        monkeypatch.setattr("config.app_info.CONFIG_FILE", "/\x00/bad")
        config.save({"port": 1})  # should not raise


class TestLogSep:
    def test_log_sep_no_crash(self):
        config.log_sep()

    def test_log_sep_with_title(self):
        config.log_sep("Hello")


class TestModuleState:
    def test_app_config_is_dict(self):
        assert isinstance(config.APP_CONFIG, dict)

    def test_briefing_dir_is_str(self):
        assert isinstance(config.BRIEFING_DIR, str)

    def test_log_file_is_str(self):
        assert isinstance(config.LOG_FILE, str)
