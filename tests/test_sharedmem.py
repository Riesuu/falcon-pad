# -*- coding: utf-8 -*-
"""Tests — sharedmem.py : safe_read avec mémoire mockée."""
import sys
import struct
import pytest
from unittest.mock import patch, MagicMock


# sharedmem utilise ctypes.WinDLL — on mocke sur Linux/CI
@pytest.fixture(autouse=True)
def mock_windll():
    """Mock WinDLL pour les plateformes non-Windows."""
    if sys.platform != "win32":
        # create=True nécessaire car WinDLL n'existe pas sur Linux
        with patch("ctypes.WinDLL", create=True) as mock:
            mock.return_value = MagicMock()
            yield mock
    else:
        yield None


class TestSafeRead:
    """Tests de safe_read via injection directe du reader."""

    def test_reader_returns_bytes(self):
        """Un reader valide doit retourner des bytes."""
        from tests.conftest import make_reader
        data = b"\x01\x02\x03\x04"
        reader = make_reader(data)
        result = reader(0, 4)
        assert result == b"\x01\x02\x03\x04"

    def test_reader_out_of_bounds_returns_none(self):
        from tests.conftest import make_reader
        data = b"\x01\x02"
        reader = make_reader(data)
        result = reader(0, 10)  # demande plus que disponible
        assert result is None

    def test_reader_partial_read(self):
        from tests.conftest import make_reader
        data = b"\xAA\xBB\xCC\xDD\xEE"
        reader = make_reader(data)
        result = reader(2, 2)
        assert result == b"\xCC\xDD"


class TestReadAllStrings:
    """Tests de read_all_strings avec blobs en mémoire."""

    def test_header_too_short(self):
        from core.stringdata import read_all_strings
        from tests.conftest import make_reader
        # Blob trop court pour le header (< 12 bytes)
        blob = b"\x00" * 8
        result = read_all_strings(0, make_reader(blob))
        assert result == {}

    def test_zero_strings(self):
        from core.stringdata import read_all_strings
        from tests.conftest import make_reader
        # Header valide mais 0 strings
        blob = struct.pack("<III", 3, 0, 0)
        result = read_all_strings(0, make_reader(blob))
        assert result == {}

    def test_too_many_strings_rejected(self):
        from core.stringdata import read_all_strings
        from tests.conftest import make_reader
        # no_strings = 600 > 500 → rejeté
        blob = struct.pack("<III", 3, 600, 100)
        result = read_all_strings(0, make_reader(blob))
        assert result == {}

    def test_valid_single_string(self):
        from core.stringdata import read_all_strings, STRID_THR_NAME
        from tests.conftest import _encode_strings_blob, make_reader
        blob, _ = _encode_strings_blob([(STRID_THR_NAME, "Korea")])
        strings = read_all_strings(0, make_reader(blob))
        assert STRID_THR_NAME in strings
        assert strings[STRID_THR_NAME][0] == "Korea"
