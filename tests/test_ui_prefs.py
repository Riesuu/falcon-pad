# -*- coding: utf-8 -*-
"""Tests — ui_prefs.py : UI preference persistence."""
import json
import os

import pytest

from ui import ui_prefs


class TestLoad:
    def test_returns_dict(self):
        result = ui_prefs.load()
        assert isinstance(result, dict)

    def test_has_all_default_keys(self):
        result = ui_prefs.load()
        for key in ui_prefs.DEFAULTS:
            assert key in result

    def test_unknown_keys_filtered(self, tmp_path, monkeypatch):
        pref_file = tmp_path / "ui_prefs.json"
        pref_file.write_text(json.dumps({"active_color": "#ff0000", "JUNK": 42}))
        monkeypatch.setattr("ui.ui_prefs.FILE", str(pref_file))
        result = ui_prefs.load()
        assert result["active_color"] == "#ff0000"
        assert "JUNK" not in result

    def test_corrupt_file_returns_defaults(self, tmp_path, monkeypatch):
        pref_file = tmp_path / "ui_prefs.json"
        pref_file.write_text("NOT JSON!!!")
        monkeypatch.setattr("ui.ui_prefs.FILE", str(pref_file))
        result = ui_prefs.load()
        assert result == ui_prefs.DEFAULTS

    def test_missing_file_creates_it(self, tmp_path, monkeypatch):
        pref_file = tmp_path / "ui_prefs.json"
        monkeypatch.setattr("ui.ui_prefs.FILE", str(pref_file))
        result = ui_prefs.load()
        assert pref_file.exists()
        assert result["layer"] == "dark"


class TestSave:
    def test_save_roundtrip(self, tmp_path, monkeypatch):
        pref_file = tmp_path / "ui_prefs.json"
        monkeypatch.setattr("ui.ui_prefs.FILE", str(pref_file))
        data = dict(ui_prefs.DEFAULTS)
        data["active_color"] = "#00ff00"
        ui_prefs.save(data)
        loaded = json.loads(pref_file.read_text())
        assert loaded["active_color"] == "#00ff00"

    def test_save_bad_path_no_crash(self, monkeypatch):
        monkeypatch.setattr("ui.ui_prefs.FILE", "/\x00/bad")
        ui_prefs.save({"x": 1})  # should not raise


class TestModuleState:
    def test_prefs_is_dict(self):
        assert isinstance(ui_prefs.prefs, dict)

    def test_defaults_not_empty(self):
        assert len(ui_prefs.DEFAULTS) > 10
