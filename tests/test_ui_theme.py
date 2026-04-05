# -*- coding: utf-8 -*-
"""Tests for ui_theme.py — Qt GUI theme constants validation."""

import ui_theme


class TestColors:
    """Validate all color hex strings."""

    def _is_hex(self, c):
        if not isinstance(c, str) or not c.startswith("#"):
            return False
        try:
            int(c[1:], 16)
            return len(c) == 7
        except ValueError:
            return False

    def test_bg_is_hex(self):
        assert self._is_hex(ui_theme.BG)

    def test_accent_is_hex(self):
        assert self._is_hex(ui_theme.ACCENT)

    def test_red_is_hex(self):
        assert self._is_hex(ui_theme.RED)

    def test_blue_is_hex(self):
        assert self._is_hex(ui_theme.BLUE)

    def test_all_colors_are_hex(self):
        colors = [ui_theme.BG, ui_theme.BG2, ui_theme.ACCENT, ui_theme.ACCENT_DIM,
                  ui_theme.RED, ui_theme.RED_DIM, ui_theme.RED_HOV, ui_theme.RED_OUT,
                  ui_theme.EJECT_YEL, ui_theme.EJECT_BLK, ui_theme.EJECT_STRP,
                  ui_theme.EJECT_HOV, ui_theme.BLUE, ui_theme.TXT_DIM, ui_theme.TXT_MID]
        for c in colors:
            assert self._is_hex(c), f"{c} is not a valid hex color"


class TestDimensions:
    def test_window_positive(self):
        assert ui_theme.WIN_W > 0
        assert ui_theme.WIN_H > 0

    def test_header_within_window(self):
        assert 0 < ui_theme.HEADER_H < ui_theme.WIN_H

    def test_eject_button_fits(self):
        assert ui_theme.EJECT_BTN_W < ui_theme.WIN_W
        assert ui_theme.EJECT_BTN_MARGIN_BOTTOM < ui_theme.WIN_H


class TestFonts:
    def test_font_family_is_string(self):
        assert isinstance(ui_theme.FONT_FAMILY, str)
        assert len(ui_theme.FONT_FAMILY) > 0

    def test_font_sizes_positive(self):
        sizes = [ui_theme.FONT_TITLE, ui_theme.FONT_SUBTITLE, ui_theme.FONT_LABEL,
                 ui_theme.FONT_VALUE, ui_theme.FONT_STATUS, ui_theme.FONT_BUTTON,
                 ui_theme.FONT_LOG_PATH]
        for s in sizes:
            assert s > 0, f"Font size {s} should be positive"


class TestTimers:
    def test_poll_ms_positive(self):
        assert ui_theme.BMS_POLL_MS > 0

    def test_initial_poll_shorter(self):
        assert ui_theme.BMS_POLL_INITIAL_MS < ui_theme.BMS_POLL_MS


class TestLabels:
    def test_labels_are_nonempty_strings(self):
        labels = [ui_theme.LBL_TITLE, ui_theme.LBL_LOCAL, ui_theme.LBL_NETWORK,
                  ui_theme.LBL_LOGS, ui_theme.LBL_CONNECTED, ui_theme.LBL_NOT_DETECTED,
                  ui_theme.LBL_EJECT]
        for lbl in labels:
            assert isinstance(lbl, str) and len(lbl) > 0


class TestDocxCss:
    def test_docx_css_contains_body(self):
        assert "body{" in ui_theme.DOCX_CSS or "body {" in ui_theme.DOCX_CSS

    def test_error_style_contains_background(self):
        assert "background" in ui_theme.DOCX_ERROR_STYLE
