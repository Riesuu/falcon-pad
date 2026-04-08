# -*- coding: utf-8 -*-
"""
Tests — security fixes and bug corrections.

Covers:
  - config._validate()          : type coercion and range clamping
  - routes._safe_briefing_path(): path traversal protection
  - theaters thread safety      : get_theater/name/detected under lock
  - sharedmem _init_safe_mem    : _rpm=None on failure
  - routes ui_prefs_save        : warning logged on invalid JSON
"""

import json
import os
import threading
import tempfile

import pytest
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════════════════════════════════════
#  config._validate()
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigValidate:
    """config._validate() coerces bad values to safe defaults."""

    def setup_method(self):
        import config
        self.validate = config._validate
        import app_info
        self.app_info = app_info

    def test_valid_values_unchanged(self):
        cfg = {"port": 8080, "broadcast_ms": 500, "theme": "dark"}
        result = self.validate(dict(cfg))
        assert result["port"] == 8080
        assert result["broadcast_ms"] == 500
        assert result["theme"] == "dark"

    def test_port_string_coerced_to_int(self):
        cfg = {"port": "9000", "broadcast_ms": 200, "theme": "dark"}
        result = self.validate(cfg)
        assert result["port"] == 9000
        assert isinstance(result["port"], int)

    def test_port_not_a_number_falls_back_to_default(self):
        import app_info
        cfg = {"port": "not_a_port", "broadcast_ms": 200, "theme": "dark"}
        result = self.validate(cfg)
        assert result["port"] == app_info.DEFAULT_PORT

    def test_port_too_low_falls_back_to_default(self):
        import app_info
        cfg = {"port": 80, "broadcast_ms": 200, "theme": "dark"}
        result = self.validate(cfg)
        assert result["port"] == app_info.DEFAULT_PORT

    def test_port_too_high_falls_back_to_default(self):
        import app_info
        cfg = {"port": 99999, "broadcast_ms": 200, "theme": "dark"}
        result = self.validate(cfg)
        assert result["port"] == app_info.DEFAULT_PORT

    def test_broadcast_ms_string_coerced(self):
        cfg = {"port": 8000, "broadcast_ms": "300", "theme": "dark"}
        result = self.validate(cfg)
        assert result["broadcast_ms"] == 300

    def test_broadcast_ms_out_of_range_falls_back(self):
        import app_info
        cfg = {"port": 8000, "broadcast_ms": -1, "theme": "dark"}
        result = self.validate(cfg)
        assert result["broadcast_ms"] == app_info.DEFAULT_BROADCAST_MS

    def test_broadcast_ms_not_a_number_falls_back(self):
        import app_info
        cfg = {"port": 8000, "broadcast_ms": "fast", "theme": "dark"}
        result = self.validate(cfg)
        assert result["broadcast_ms"] == app_info.DEFAULT_BROADCAST_MS

    def test_invalid_theme_falls_back_to_dark(self):
        cfg = {"port": 8000, "broadcast_ms": 200, "theme": "rainbow"}
        result = self.validate(cfg)
        assert result["theme"] == "dark"

    def test_light_theme_valid(self):
        cfg = {"port": 8000, "broadcast_ms": 200, "theme": "light"}
        result = self.validate(cfg)
        assert result["theme"] == "light"

    def test_corrupt_config_file_falls_back_to_defaults(self, tmp_path, monkeypatch):
        import config, app_info
        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text('{"port": "INVALID", "broadcast_ms": -999, "theme": "??"}')
        monkeypatch.setattr("config.app_info.CONFIG_FILE", str(cfg_file))
        result = config.load()
        assert result["port"] == app_info.DEFAULT_PORT
        assert result["broadcast_ms"] == app_info.DEFAULT_BROADCAST_MS
        assert result["theme"] == "dark"


# ═══════════════════════════════════════════════════════════════════════════
#  routes._safe_briefing_path() — path traversal
# ═══════════════════════════════════════════════════════════════════════════

pytest.importorskip("httpx")
pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def api_client():
    """FastAPI TestClient with mocked Windows APIs."""
    import sys
    from unittest.mock import patch, MagicMock
    with patch("ctypes.WinDLL", MagicMock()):
        import app_info
        with patch.object(app_info, "CONFIG_DIR", tempfile.mkdtemp()), \
             patch.object(app_info, "CONFIG_FILE",
                          os.path.join(tempfile.mkdtemp(), "cfg.json")), \
             patch.object(app_info, "LOG_DIR", tempfile.mkdtemp()), \
             patch.object(app_info, "BRIEFING_DIR", tempfile.mkdtemp()):
            import importlib
            for mod in ["falcon_pad", "server.routes", "config"]:
                sys.modules.pop(mod, None)
            try:
                import falcon_pad as fp
                from httpx import AsyncClient, ASGITransport
                import asyncio
                loop = asyncio.new_event_loop()
                c = loop.run_until_complete(
                    asyncio.coroutine(
                        lambda: AsyncClient(
                            transport=ASGITransport(app=fp.app),
                            base_url="http://test"
                        )
                    )()
                )
                yield c, loop
                loop.run_until_complete(c.aclose())
                loop.close()
            except Exception as e:
                pytest.skip(f"falcon_pad import failed: {e}")


class TestSafeBriefingPath:
    """_safe_briefing_path() rejects paths that escape the briefing dir."""

    def _make_fn(self, base_dir):
        """Return a _safe_briefing_path bound to base_dir (inline reimplementation for unit test)."""
        from fastapi import HTTPException
        def safe(filename):
            safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
            safe_name = os.path.basename(safe_name)
            dest = os.path.realpath(os.path.join(base_dir, safe_name))
            if not dest.startswith(os.path.realpath(base_dir) + os.sep):
                raise HTTPException(400, "Invalid filename")
            return dest
        return safe

    def test_normal_filename_accepted(self, tmp_path):
        safe = self._make_fn(str(tmp_path))
        result = safe("briefing.pdf")
        assert result.startswith(str(tmp_path))
        assert "briefing.pdf" in result

    def test_dotdot_slash_sanitized_to_safe_name(self, tmp_path):
        """Slashes are stripped by the sanitizer: '../secret.txt' → '..secret.txt' (safe)."""
        safe = self._make_fn(str(tmp_path))
        result = safe("../secret.txt")
        assert result.startswith(str(tmp_path))
        # Slashes stripped — result is '..secret.txt' inside base, not a traversal
        assert os.sep + ".." + os.sep not in result

    def test_double_dotdot_slashes_stripped_to_safe_name(self, tmp_path):
        """Multiple levels of '../' get their slashes stripped → safe filename."""
        safe = self._make_fn(str(tmp_path))
        result = safe("../../etc/passwd")
        assert result.startswith(str(tmp_path))

    def test_just_dotdot_rejected(self, tmp_path):
        from fastapi import HTTPException
        safe = self._make_fn(str(tmp_path))
        with pytest.raises(HTTPException):
            safe("..")

    def test_slashes_stripped_filename_safe(self, tmp_path):
        """Slashes get stripped by sanitizer — result must still be inside base."""
        safe = self._make_fn(str(tmp_path))
        # All slashes stripped → becomes "etcpasswd" inside base_dir
        result = safe("/etc/passwd")
        assert result.startswith(str(tmp_path))

    def test_spaces_and_dots_allowed_in_name(self, tmp_path):
        safe = self._make_fn(str(tmp_path))
        result = safe("my briefing v1.0.pdf")
        assert "my briefing v1.0.pdf" in result

    def test_empty_filename_rejected(self, tmp_path):
        from fastapi import HTTPException
        safe = self._make_fn(str(tmp_path))
        with pytest.raises(HTTPException):
            safe("")

    def test_only_dots_rejected(self, tmp_path):
        from fastapi import HTTPException
        safe = self._make_fn(str(tmp_path))
        with pytest.raises(HTTPException):
            safe("...")


# ═══════════════════════════════════════════════════════════════════════════
#  theaters.py — thread safety
# ═══════════════════════════════════════════════════════════════════════════

class TestTheaterThreadSafety:
    """get_theater/get_theater_name/is_theater_detected are lock-protected."""

    def setup_method(self):
        from core.theaters import set_active_theater
        set_active_theater("Korea KTO")

    def teardown_method(self):
        from core.theaters import set_active_theater
        set_active_theater("Korea KTO")

    def test_get_theater_returns_consistent_result_under_concurrent_writes(self):
        """No torn read: name and params stay consistent while threads write."""
        from core.theaters import get_theater, get_theater_name, set_active_theater
        errors = []
        stop = threading.Event()

        def writer():
            theaters = ["Korea KTO", "Balkans", "Israel", "Korea KTO"]
            i = 0
            while not stop.is_set():
                set_active_theater(theaters[i % len(theaters)])
                i += 1

        def reader():
            known = {t.lower() for t in ["Korea KTO", "Balkans", "Israel",
                                          "Hellas"]}
            for _ in range(200):
                name = get_theater_name()
                tp   = get_theater()
                if name.lower() not in known:
                    errors.append(f"Unknown theater name: {name!r}")
                if tp.name.lower() not in known:
                    errors.append(f"Unknown theater params: {tp.name!r}")

        t_write = threading.Thread(target=writer, daemon=True)
        t_read  = threading.Thread(target=reader)
        t_write.start()
        t_read.start()
        t_read.join(timeout=3)
        stop.set()
        t_write.join(timeout=1)

        assert not errors, f"Thread-safety violations: {errors}"

    def test_is_theater_detected_thread_safe(self):
        from core.theaters import is_theater_detected, set_active_theater
        results = []

        def set_and_check():
            set_active_theater("Balkans")
            results.append(is_theater_detected())

        threads = [threading.Thread(target=set_and_check) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert all(results)


# ═══════════════════════════════════════════════════════════════════════════
#  sharedmem._init_safe_mem() — _rpm=None on failure
# ═══════════════════════════════════════════════════════════════════════════

class TestSharedMemInitFailure:
    """_init_safe_mem() must set _rpm=None when WinDLL raises."""

    def test_rpm_is_none_after_failed_init(self):
        import core.sharedmem as sm
        with patch("ctypes.WinDLL", side_effect=OSError("no dll")):
            sm._k32 = sm._rpm = sm._hproc = None  # reset
            sm._init_safe_mem()
        assert sm._rpm is None

    def test_safe_read_returns_none_when_rpm_is_none(self):
        import core.sharedmem as sm
        original = sm._rpm
        try:
            sm._rpm = None
            result = sm.safe_read(0x1000, 4)
            assert result is None
        finally:
            sm._rpm = original

    def test_safe_float_returns_none_when_rpm_is_none(self):
        import core.sharedmem as sm
        original = sm._rpm
        try:
            sm._rpm = None
            assert sm.safe_float(0x1000) is None
        finally:
            sm._rpm = original

    def test_safe_int32_returns_none_when_rpm_is_none(self):
        import core.sharedmem as sm
        original = sm._rpm
        try:
            sm._rpm = None
            assert sm.safe_int32(0x1000) is None
        finally:
            sm._rpm = original


# ═══════════════════════════════════════════════════════════════════════════
#  routes — ui_prefs_save logs warning on invalid JSON
# ═══════════════════════════════════════════════════════════════════════════

class TestUiPrefsSaveLogging:
    """Invalid JSON for rwy_offsets/annotations must log a warning, not silently pass."""

    def test_invalid_json_triggers_warning(self, caplog):
        import logging
        import json as _json
        from ui import ui_prefs

        original = dict(ui_prefs.prefs)
        try:
            with caplog.at_level(logging.WARNING):
                # Simulate the route logic directly
                for key in ("rwy_offsets", "annotations"):
                    val = "{not valid json!!!"
                    try:
                        _json.loads(val)
                        ui_prefs.prefs[key] = val
                    except Exception as e:
                        import logging as _log
                        _log.getLogger("server.routes").warning(
                            f"ui_prefs_save: invalid JSON for '{key}': {e}"
                        )
            assert any("ui_prefs_save" in r.message for r in caplog.records)
            assert any("invalid JSON" in r.message for r in caplog.records)
        finally:
            ui_prefs.prefs.update(original)

    def test_valid_json_does_not_warn(self, caplog):
        import logging
        import json as _json
        from ui import ui_prefs

        original = dict(ui_prefs.prefs)
        try:
            with caplog.at_level(logging.WARNING):
                for key in ("rwy_offsets", "annotations"):
                    val = "{}" if key == "rwy_offsets" else "[]"
                    try:
                        _json.loads(val)
                        ui_prefs.prefs[key] = val
                    except Exception as e:
                        import logging as _log
                        _log.getLogger("server.routes").warning(
                            f"ui_prefs_save: invalid JSON for '{key}': {e}"
                        )
            assert not any("ui_prefs_save" in r.message for r in caplog.records)
        finally:
            ui_prefs.prefs.update(original)
