# -*- coding: utf-8 -*-
"""
Falcon-Pad test configuration.
Run from project root: python -m pytest tests/ -v
"""

import os
import struct
import sys

import pytest

# ── Path setup: add project root so modules are importable ───────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ── Shared fixtures ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_theater():
    """Ensure every test starts with Korea theater active."""
    from theaters import set_active_theater
    set_active_theater("Korea")
    yield
    set_active_theater("Korea")


@pytest.fixture
def reset_stringdata_cache():
    """Reset the StringData theater detection cache."""
    import stringdata
    old = stringdata._last_thr_name
    stringdata._last_thr_name = ""
    yield
    stringdata._last_thr_name = old


@pytest.fixture
def reset_mission():
    """Reset mission module state."""
    import mission
    old_data = mission.mission_data
    old_hash = mission._shm_mission_hash
    mission.mission_data = {"route": [], "threats": [], "flightplan": []}
    mission._shm_mission_hash = ""
    yield
    mission.mission_data = old_data
    mission._shm_mission_hash = old_hash


# ── Helpers for fake StringData blobs ────────────────────────────────────

def make_string_blob(entries: list) -> bytes:
    """
    Build a fake StringData binary blob from [(strId, text), ...].
    Mirrors the BMS FalconSharedMemoryAreaString layout.
    """
    data_parts = []
    for str_id, text in entries:
        encoded = text.encode('utf-8')
        data_parts.append(struct.pack('<II', str_id, len(encoded)))
        data_parts.append(encoded + b'\x00')
    data_blob = b''.join(data_parts)
    header = struct.pack('<III', 5, len(entries), len(data_blob))
    return header + data_blob


def fake_reader(blob: bytes):
    """Return a safe_read-compatible function that reads from a byte blob."""
    def reader(addr: int, size: int):
        end = addr + size
        return blob[addr:end] if end <= len(blob) else None
    return reader
