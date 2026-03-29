# -*- coding: utf-8 -*-
"""Tests — airports.py : dynamic airport loading per theater."""
import json
import os

import pytest

import airports


class TestLoad:
    def test_unknown_theater_returns_empty(self):
        assert airports.load("Narnia") == []

    def test_korea_returns_list(self):
        result = airports.load("Korea")
        # Might be empty if data file missing in CI, but must be a list
        assert isinstance(result, list)

    def test_korea_kto_same_data_as_korea(self):
        a = airports.load("Korea")
        b = airports.load("Korea KTO")
        assert a == b  # same file, same data

    def test_case_insensitive(self):
        a = airports.load("balkans")
        b = airports.load("Balkans")
        # Both go through .lower(), should be same
        assert a is b

    def test_cache_hit(self):
        """Second call should return cached reference (same id)."""
        airports._cache.clear()
        first = airports.load("Korea")
        second = airports.load("Korea")
        assert first is second

    def test_empty_name(self):
        assert airports.load("") == []

    def test_files_mapping_all_lowercase_keys(self):
        for key in airports._FILES:
            assert key == key.lower()


class TestLoadMissingFile:
    def test_missing_data_dir_returns_empty(self, monkeypatch):
        monkeypatch.setattr("airports._DIR", "/nonexistent_path_12345")
        airports._cache.clear()
        assert airports.load("Korea") == []
