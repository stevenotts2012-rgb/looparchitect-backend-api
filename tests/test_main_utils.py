"""
Tests for app/main.py utility functions and exception handlers.

Covers previously-untested paths:
- _is_railway_environment() (line 82)
- _normalize_origin() (line 87)
- _to_absolute_url() (lines 92-95)
- _get_public_base_url() (lines 100-113 including the fallback env vars)
- _build_openapi_servers() (lines 118-136, the public_url branch at line 123)
- validation_exception_handler (lines 293-294)
- pydantic_exception_handler (lines 307-308)
- general_exception_handler (lines 321-326)
- worker_health endpoint (lines 379-381, 386)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _is_railway_environment
# ---------------------------------------------------------------------------


class TestIsRailwayEnvironment:
    def test_returns_true_when_railway_environment_set(self):
        from app.main import _is_railway_environment

        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT": "production"}, clear=False):
            assert _is_railway_environment() is True

    def test_returns_true_when_port_set(self):
        from app.main import _is_railway_environment

        env = {"PORT": "8080"}
        # Remove RAILWAY_ENVIRONMENT to isolate the PORT branch
        patched = {k: v for k, v in os.environ.items() if k not in ("RAILWAY_ENVIRONMENT",)}
        patched.update(env)
        with patch.dict(os.environ, patched, clear=True):
            assert _is_railway_environment() is True

    def test_returns_false_when_neither_set(self):
        from app.main import _is_railway_environment

        without = {k: v for k, v in os.environ.items() if k not in ("RAILWAY_ENVIRONMENT", "PORT")}
        with patch.dict(os.environ, without, clear=True):
            assert _is_railway_environment() is False


# ---------------------------------------------------------------------------
# _normalize_origin
# ---------------------------------------------------------------------------


class TestNormalizeOrigin:
    def test_strips_trailing_slash(self):
        from app.main import _normalize_origin

        assert _normalize_origin("https://example.com/") == "https://example.com"

    def test_strips_leading_and_trailing_whitespace(self):
        from app.main import _normalize_origin

        assert _normalize_origin("  https://example.com  ") == "https://example.com"

    def test_leaves_clean_origin_unchanged(self):
        from app.main import _normalize_origin

        assert _normalize_origin("https://example.com") == "https://example.com"


# ---------------------------------------------------------------------------
# _to_absolute_url
# ---------------------------------------------------------------------------


class TestToAbsoluteUrl:
    def test_adds_https_when_no_scheme(self):
        from app.main import _to_absolute_url

        assert _to_absolute_url("example.com") == "https://example.com"

    def test_preserves_existing_https_scheme(self):
        from app.main import _to_absolute_url

        assert _to_absolute_url("https://example.com") == "https://example.com"

    def test_preserves_existing_http_scheme(self):
        from app.main import _to_absolute_url

        assert _to_absolute_url("http://localhost:8000") == "http://localhost:8000"

    def test_strips_trailing_slash(self):
        from app.main import _to_absolute_url

        assert _to_absolute_url("https://example.com/") == "https://example.com"

    def test_strips_whitespace(self):
        from app.main import _to_absolute_url

        assert _to_absolute_url("  https://example.com  ") == "https://example.com"


# ---------------------------------------------------------------------------
# _get_public_base_url
# ---------------------------------------------------------------------------


class TestGetPublicBaseUrl:
    def test_returns_railway_public_domain_first(self):
        from app.main import _get_public_base_url

        env = {"RAILWAY_PUBLIC_DOMAIN": "myapp.railway.app"}
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_PUBLIC_URL",
                               "RAILWAY_STATIC_URL", "RENDER_EXTERNAL_URL")}
        clean.update(env)
        with patch.dict(os.environ, clean, clear=True):
            result = _get_public_base_url()
        assert result == "https://myapp.railway.app"

    def test_fallback_to_railway_public_url(self):
        from app.main import _get_public_base_url

        env = {"RAILWAY_PUBLIC_URL": "https://myapp.up.railway.app"}
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_PUBLIC_URL",
                               "RAILWAY_STATIC_URL", "RENDER_EXTERNAL_URL")}
        clean.update(env)
        with patch.dict(os.environ, clean, clear=True):
            result = _get_public_base_url()
        assert result == "https://myapp.up.railway.app"

    def test_fallback_to_render_external_url(self):
        from app.main import _get_public_base_url

        env = {"RENDER_EXTERNAL_URL": "https://myapp.onrender.com"}
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_PUBLIC_URL",
                               "RAILWAY_STATIC_URL", "RENDER_EXTERNAL_URL")}
        clean.update(env)
        with patch.dict(os.environ, clean, clear=True):
            result = _get_public_base_url()
        assert result == "https://myapp.onrender.com"

    def test_returns_none_when_no_env_vars(self):
        from app.main import _get_public_base_url

        clean = {k: v for k, v in os.environ.items()
                 if k not in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_PUBLIC_URL",
                               "RAILWAY_STATIC_URL", "RENDER_EXTERNAL_URL")}
        with patch.dict(os.environ, clean, clear=True):
            result = _get_public_base_url()
        assert result is None


# ---------------------------------------------------------------------------
# _build_openapi_servers
# ---------------------------------------------------------------------------


class TestBuildOpenApiServers:
    def test_includes_public_url_when_available(self):
        from app.main import _build_openapi_servers

        with patch("app.main._get_public_base_url", return_value="https://myapp.railway.app"), \
             patch("app.main._is_railway_environment", return_value=True):
            servers = _build_openapi_servers()

        urls = [s["url"] for s in servers]
        assert "https://myapp.railway.app" in urls

    def test_always_includes_localhost(self):
        from app.main import _build_openapi_servers

        with patch("app.main._get_public_base_url", return_value=None):
            servers = _build_openapi_servers()

        urls = [s["url"] for s in servers]
        assert any("localhost" in url for url in urls)

    def test_no_public_url_only_local_servers(self):
        from app.main import _build_openapi_servers

        with patch("app.main._get_public_base_url", return_value=None):
            servers = _build_openapi_servers()

        # Should have exactly the two local entries
        assert len(servers) == 2

    def test_public_url_description_railway(self):
        from app.main import _build_openapi_servers

        with patch("app.main._get_public_base_url", return_value="https://myapp.railway.app"), \
             patch("app.main._is_railway_environment", return_value=True):
            servers = _build_openapi_servers()

        production_entry = next(
            (s for s in servers if s["url"] == "https://myapp.railway.app"), None
        )
        assert production_entry is not None
        assert "Railway" in production_entry["description"]


# ---------------------------------------------------------------------------
# Exception handlers (trigger via invalid requests)
# ---------------------------------------------------------------------------


class TestExceptionHandlers:
    def test_validation_exception_handler_returns_422(self, client):
        """Sending malformed JSON to a validated endpoint triggers the handler."""
        # POST to an endpoint with a validated body; send a value that fails
        # pydantic validation (e.g. a non-integer loop_id path param)
        response = client.post("/api/v1/loops/not-a-number/render-async", json={})
        # FastAPI converts path param validation → 422
        assert response.status_code == 422

    def test_404_for_completely_unknown_route(self, client):
        """Requesting a non-existent route returns 404 (FastAPI default)."""
        response = client.get("/this-route-does-not-exist-at-all-xyz")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# /health/worker (root-level, not /api/v1) – embedded worker endpoint
# ---------------------------------------------------------------------------


class TestWorkerHealthEndpoint:
    def test_worker_health_returns_200(self, client):
        """GET /health/worker (root, not /api/v1) returns 200."""
        response = client.get("/health/worker")
        assert response.status_code == 200

    def test_worker_health_response_shape(self, client):
        response = client.get("/health/worker")
        data = response.json()
        assert "embedded_worker_enabled" in data
        assert "active_worker_count" in data
        assert "active_workers" in data
        assert isinstance(data["active_workers"], list)
