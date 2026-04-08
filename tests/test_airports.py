# -*- coding: utf-8 -*-
"""Tests — airports.py : dynamic airport loading per theater."""
import json
import os

import pytest

from core import airports


class TestLoad:
    def test_unknown_theater_returns_empty(self):
        assert airports.load("Narnia") == []

    def test_korea_kto_returns_list(self):
        result = airports.load("Korea KTO")
        # Might be empty if data file missing in CI, but must be a list
        assert isinstance(result, list)

    def test_case_insensitive(self):
        a = airports.load("balkans")
        b = airports.load("Balkans")
        # Both go through .lower(), should be same
        assert a is b

    def test_cache_hit(self):
        """Second call should return cached reference (same id)."""
        airports._cache.clear()
        first = airports.load("Korea KTO")
        second = airports.load("Korea KTO")
        assert first is second

    def test_empty_name(self):
        assert airports.load("") == []

    def test_files_mapping_all_lowercase_keys(self):
        for key in airports._FILES:
            assert key == key.lower()


class TestLoadMissingFile:
    def test_missing_data_dir_returns_empty(self, monkeypatch):
        monkeypatch.setattr("core.airports._DIR", "/nonexistent_path_12345")
        airports._cache.clear()
        assert airports.load("Korea KTO") == []
