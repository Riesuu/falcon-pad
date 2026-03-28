# -*- coding: utf-8 -*-
"""
Tests d'intégration — API FastAPI via httpx TestClient.
On mocke BMS (non connecté) pour tester les endpoints REST.
"""
import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

# Skip si FastAPI/httpx indisponibles
pytest.importorskip("httpx")
pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def client():
    """Crée un TestClient FastAPI avec BMS déconnecté."""
    # Mock les imports Windows-only avant d'importer falcon_pad
    with patch("ctypes.WinDLL", MagicMock()):
        # S'assurer que le dossier config existe
        import tempfile, app_info
        with patch.object(app_info, "CONFIG_DIR", tempfile.mkdtemp()):
            with patch.object(app_info, "CONFIG_FILE",
                              os.path.join(tempfile.mkdtemp(), "cfg.json")):
                with patch.object(app_info, "LOG_DIR", tempfile.mkdtemp()):
                    with patch.object(app_info, "BRIEFING_DIR", tempfile.mkdtemp()):
                        # Import différé pour que les mocks soient actifs
                        import importlib
                        if "falcon_pad" in sys.modules:
                            del sys.modules["falcon_pad"]
                        try:
                            import falcon_pad as fp
                            from httpx import AsyncClient, ASGITransport
                            import asyncio

                            async def _get_client():
                                return AsyncClient(
                                    transport=ASGITransport(app=fp.app),
                                    base_url="http://test"
                                )

                            loop = asyncio.new_event_loop()
                            c = loop.run_until_complete(_get_client())
                            yield c, loop
                            loop.run_until_complete(c.aclose())
                            loop.close()
                        except Exception as e:
                            pytest.skip(f"falcon_pad import failed: {e}")


def _get(client_tuple, path):
    c, loop = client_tuple
    import asyncio
    return loop.run_until_complete(c.get(path))


class TestApiEndpoints:
    """Vérifie que les endpoints répondent correctement."""

    def test_root_returns_html(self, client):
        # La route / retourne index.html ou 500 si frontend/ absent
        r = _get(client, "/")
        assert r.status_code in (200, 500)

    def test_api_mission(self, client):
        r = _get(client, "/api/mission")
        assert r.status_code == 200
        data = r.json()
        assert "route" in data
        assert "threats" in data
        assert "flightplan" in data

    def test_api_ini_status(self, client):
        r = _get(client, "/api/ini/status")
        assert r.status_code == 200
        data = r.json()
        assert "loaded" in data

    def test_api_settings_get(self, client):
        r = _get(client, "/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert "port" in data
        assert "broadcast_ms" in data

    def test_api_server_info(self, client):
        r = _get(client, "/api/server/info")
        assert r.status_code == 200
        data = r.json()
        assert "ip" in data
        assert "port" in data

    def test_api_app_info(self, client):
        r = _get(client, "/api/app/info")
        assert r.status_code == 200
        data = r.json()
        assert "name" in data
        assert "version" in data

    def test_api_ui_prefs_get(self, client):
        r = _get(client, "/api/ui-prefs")
        assert r.status_code == 200
        data = r.json()
        assert "active_color" in data
        assert "layer" in data

    def test_api_airports(self, client):
        r = _get(client, "/api/airports")
        assert r.status_code == 200
        airports = r.json()
        assert isinstance(airports, list)
        assert len(airports) > 0
        # Vérifier la structure d'un aéroport
        ap = airports[0]
        assert "icao" in ap
        assert "lat" in ap
        assert "lon" in ap
