# -*- coding: utf-8 -*-
"""
Falcon-Pad — conftest.py
Fixtures partagées entre tous les tests.
"""
import sys
import os
import struct

import pytest

# Ajout du répertoire racine au path pour les imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Helpers pour construire des blobs NavPoint ──────────────────────────────

def _encode_navpoint(idx: int, typ: str, x: float, y: float,
                     z: float = 0.0, ge: float = 0.0,
                     pt_name: str = "", pt_range: float = 0.0) -> str:
    """Construit une chaîne NavPoint au format BMS FlightData.h SDK."""
    raw = f"NP:{idx},{typ},{x},{y},{z},{ge};"
    if typ == "PT":
        raw += f'PT:"{pt_name}",{pt_range},0;'
    return raw


def _encode_strings_blob(entries: list[tuple[int, str]]) -> tuple[bytes, int]:
    """
    Construit un blob FalconSharedMemoryAreaString minimal.
    entries = [(str_id, text), ...]
    Retourne (blob_bytes, ptr_offset=0).
    """
    # Header: VersionNum, NoOfStrings, dataSize (calculé après)
    parts = []
    for str_id, text in entries:
        encoded = text.encode("utf-8")
        parts.append(struct.pack("<II", str_id, len(encoded)) + encoded + b"\x00")
    data = b"".join(parts)
    header = struct.pack("<III", 3, len(entries), len(data))
    blob = header + data
    return blob, 0


def make_reader(blob: bytes):
    """Retourne une fonction safe_read qui lit dans le blob en mémoire."""
    def reader(addr: int, size: int):
        end = addr + size
        if end > len(blob):
            return None
        return blob[addr:end]
    return reader


# ── Fixtures Korea coords ────────────────────────────────────────────────────

# Coordonnées BMS Korea connues → WGS-84 attendues (Osan AB ~37.09°N, 127.03°E)
OSAN_BMS_X = 1_145_000.0  # North ft
OSAN_BMS_Y = 1_550_000.0  # East ft


@pytest.fixture(autouse=True)
def set_korea_theater():
    """Force le théâtre Korea pour tous les tests."""
    from theaters import set_active_theater
    set_active_theater("Korea")
    yield
