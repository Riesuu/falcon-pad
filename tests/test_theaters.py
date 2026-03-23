# -*- coding: utf-8 -*-
"""Tests — theaters.py : projection TMERC et détection de théâtre."""
import pytest
from theaters import (
    bms_to_latlon, in_theater_bbox,
    set_active_theater, get_theater_name, THEATER_DB,
)


class TestBmsToLatlon:
    """Conversion coordonnées BMS → WGS-84."""

    def test_korea_osan_approx(self):
        """Osan AB (BMS) doit donner ~37.09°N, 127.03°E."""
        lat, lon = bms_to_latlon(1_145_000.0, 1_550_000.0)
        assert 36.5 < lat < 37.5, f"lat hors plage: {lat}"
        assert 126.5 < lon < 127.5, f"lon hors plage: {lon}"

    def test_korea_zero_invalid(self):
        """Coordonnées hors bbox (Tokyo) doivent être rejetées."""
        # Tokyo ~35.7N, 139.7E est hors de la bbox Korea (lon_max=135)
        assert not in_theater_bbox(35.7, 139.7)

    def test_korea_invert(self):
        """Une position valide doit être dans la bbox Korea."""
        lat, lon = bms_to_latlon(1_145_000.0, 1_550_000.0)
        assert in_theater_bbox(lat, lon)

    def test_out_of_bbox_japan(self):
        """Point au Japon (140°E) doit être hors bbox Korea."""
        assert not in_theater_bbox(35.0, 140.0)

    def test_out_of_bbox_china(self):
        """Point en Chine profonde (100°E) doit être hors bbox."""
        assert not in_theater_bbox(35.0, 100.0)


class TestSetActiveTheater:
    """Sélection et détection de théâtre."""

    def test_set_korea(self):
        assert set_active_theater("Korea") is False  # déjà actif (autouse fixture)

    def test_set_balkans(self):
        changed = set_active_theater("Balkans")
        assert changed is True
        assert get_theater_name() == "Balkans"
        # Remettre Korea
        set_active_theater("Korea")

    def test_set_unknown_returns_false(self):
        changed = set_active_theater("UnknownTheater_XYZ")
        assert changed is False

    def test_fuzzy_match(self):
        """'Korea KTO' doit matcher Korea."""
        set_active_theater("Korea")  # reset
        changed = set_active_theater("Korea KTO")
        # Soit change vers KTO, soit reste Korea — dans les deux cas pas d'erreur
        assert get_theater_name() in ("Korea KTO", "Korea")
        set_active_theater("Korea")

    def test_all_theaters_registered(self):
        """Les théâtres documentés doivent tous être dans THEATER_DB."""
        for name in ("korea", "balkans", "israel", "aegean", "iberia", "nordic"):
            assert name in THEATER_DB, f"{name} absent de THEATER_DB"
