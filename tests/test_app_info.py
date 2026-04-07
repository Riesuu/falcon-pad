# -*- coding: utf-8 -*-
"""Tests for app_info.py — centralized constants validation."""

import os
import app_info


class TestIdentity:
    def test_name_is_string(self):
        assert isinstance(app_info.NAME, str) and len(app_info.NAME) > 0

    def test_version_is_string(self):
        assert isinstance(app_info.VERSION, str)

    def test_short_is_string(self):
        assert isinstance(app_info.SHORT, str)


class TestNetwork:
    def test_default_port_in_range(self):
        assert app_info.PORT_MIN <= app_info.DEFAULT_PORT <= app_info.PORT_MAX

    def test_broadcast_ms_range(self):
        assert app_info.BROADCAST_MS_MIN < app_info.DEFAULT_BROADCAST_MS < app_info.BROADCAST_MS_MAX

    def test_dns_probe(self):
        assert isinstance(app_info.DNS_PROBE_HOST, str)
        assert 1 <= app_info.DNS_PROBE_PORT <= 65535


class TestConversions:
    def test_ft_to_m(self):
        assert abs(app_info.FT_TO_M - 0.3048) < 1e-6

    def test_m_to_ft(self):
        assert abs(app_info.M_TO_FT - 3.28084) < 1e-4

    def test_ft_to_m_inverse_of_m_to_ft(self):
        assert abs(app_info.FT_TO_M * app_info.M_TO_FT - 1.0) < 1e-4

    def test_ft_to_nm_divisor_positive(self):
        assert app_info.FT_TO_NM_DIVISOR > 6000

    def test_kt_per_ms(self):
        assert 1.9 < app_info.KT_PER_MS < 2.0

    def test_ppt_defaults(self):
        assert app_info.PPT_DEFAULT_RANGE_M > 0
        assert app_info.PPT_DEFAULT_RANGE_NM > 0


class TestPaths:
    def test_frontend_subdir(self):
        assert app_info.FRONTEND_SUBDIR == "frontend"

    def test_icon_filename(self):
        assert app_info.ICON_FILENAME.endswith(".ico")

    def test_index_html(self):
        assert app_info.INDEX_HTML == "index.html"

    def test_checklist_rel_path_is_tuple(self):
        assert isinstance(app_info.CHECKLIST_REL_PATH, tuple)
        assert len(app_info.CHECKLIST_REL_PATH) >= 2

    def test_derived_frontend_dir(self):
        assert app_info.FRONTEND_DIR.endswith(app_info.FRONTEND_SUBDIR)

    def test_derived_assets_dir(self):
        assert app_info.ASSETS_DIR.endswith(app_info.IMAGES_SUBDIR)

    def test_base_dir_exists(self):
        assert os.path.isdir(app_info.BASE_DIR)

    def test_config_dir_exists(self):
        assert os.path.isdir(app_info.CONFIG_DIR)

    def test_log_dir_exists(self):
        assert os.path.isdir(app_info.LOG_DIR)


class TestServer:
    def test_static_route_starts_with_slash(self):
        assert app_info.STATIC_ROUTE.startswith("/")

    def test_cache_control(self):
        assert "no-cache" in app_info.CACHE_CONTROL_STATIC

    def test_access_denied_msg(self):
        assert isinstance(app_info.ACCESS_DENIED_MSG, str)

    def test_ini_encoding(self):
        assert app_info.INI_ENCODING == "latin-1"

    def test_bms_config_hint(self):
        assert "g_bTacviewRealTime" in app_info.BMS_CONFIG_HINT


class TestMime:
    def test_pdf_mime(self):
        assert app_info.MIME_MAP[".pdf"] == "application/pdf"

    def test_png_mime(self):
        assert app_info.MIME_MAP[".png"] == "image/png"

    def test_default_mime(self):
        assert app_info.MIME_DEFAULT == "application/octet-stream"

    def test_all_briefing_ext_have_mime(self):
        for ext in app_info.BRIEFING_ALLOWED_EXT:
            if ext != ".docx":  # docx is handled separately
                assert ext in app_info.MIME_MAP, f"Missing MIME for {ext}"


class TestValidation:
    def test_valid_themes(self):
        assert "dark" in app_info.VALID_THEMES
        assert "light" in app_info.VALID_THEMES

    def test_valid_layers(self):
        assert len(app_info.VALID_LAYERS) >= 3

    def test_port_range(self):
        assert app_info.PORT_MIN == 1024
        assert app_info.PORT_MAX == 65535

    def test_size_range(self):
        assert app_info.SIZE_MIN < app_info.SIZE_MAX

