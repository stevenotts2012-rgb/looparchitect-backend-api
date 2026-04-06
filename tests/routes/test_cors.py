"""
Tests for CORS middleware configuration.

Verifies that:
- Vercel production domain receives CORS headers
- Vercel preview deployment subdomains receive CORS headers
- localhost development origins receive CORS headers
- OPTIONS preflight requests are handled correctly
"""

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALLOWED_ORIGINS = [
    "https://looparchitect-frontend.vercel.app",
    "https://looparchitect-frontend-git-main-abc123.vercel.app",
    "https://any-preview-abc.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

BLOCKED_ORIGINS = [
    "https://evil.com",
    "https://notvercel.app",
    "http://localhost:9999",
]


def _preflight(client: TestClient, origin: str, path: str = "/api/v1/health/live") -> object:
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )


def _get(client: TestClient, origin: str, path: str = "/api/v1/health/live") -> object:
    return client.get(path, headers={"Origin": origin})


# ---------------------------------------------------------------------------
# Allowed origins — preflight
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
def test_preflight_allowed_origins(client, origin):
    """OPTIONS preflight from allowed origins must return ACAO header."""
    response = _preflight(client, origin)
    assert response.headers.get("access-control-allow-origin") in (origin, "*"), (
        f"Expected ACAO header for origin {origin!r}, got: {dict(response.headers)}"
    )


# ---------------------------------------------------------------------------
# Allowed origins — simple request
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
def test_cors_header_on_simple_request(client, origin):
    """GET from an allowed origin must carry Access-Control-Allow-Origin."""
    response = _get(client, origin)
    assert response.headers.get("access-control-allow-origin") in (origin, "*"), (
        f"Expected ACAO header for origin {origin!r}, got: {dict(response.headers)}"
    )


# ---------------------------------------------------------------------------
# Blocked origins — should NOT receive ACAO header
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("origin", BLOCKED_ORIGINS)
def test_cors_header_absent_for_blocked_origins(client, origin):
    """Requests from origins not on the allowlist must not get an ACAO header."""
    response = _get(client, origin)
    acao = response.headers.get("access-control-allow-origin", "")
    assert acao != origin and acao != "*", (
        f"Unexpected ACAO header {acao!r} returned for blocked origin {origin!r}"
    )


# ---------------------------------------------------------------------------
# Methods and headers are permitted
# ---------------------------------------------------------------------------


def test_preflight_allows_post_method(client):
    origin = "https://looparchitect-frontend.vercel.app"
    response = _preflight(client, origin)
    allowed_methods = response.headers.get("access-control-allow-methods", "")
    # Either explicit POST or wildcard
    assert "POST" in allowed_methods or "*" in allowed_methods


def test_preflight_allows_content_type_header(client):
    origin = "https://looparchitect-frontend.vercel.app"
    response = _preflight(client, origin)
    allowed_headers = response.headers.get("access-control-allow-headers", "")
    assert "content-type" in allowed_headers.lower() or "*" in allowed_headers
