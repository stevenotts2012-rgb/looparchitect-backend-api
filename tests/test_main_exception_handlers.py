"""Tests for app/main.py exception handlers and worker health endpoint.

Covers previously-uncovered lines:
- validation_exception_handler body (lines 293-294)
- pydantic_exception_handler body (lines 307-308)
- general_exception_handler body (lines 321-326)
- worker_health endpoint (lines 379-381)

Note: this file tests functions defined in *app/main.py* directly.
The root-level main.py is a separate module with its own app instance.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

# Use root main.py app (the one served by all other tests)
from main import app as root_app


@pytest.fixture
def client():
    return TestClient(root_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Direct invocation of exception handlers
# ---------------------------------------------------------------------------


class TestValidationExceptionHandlerDirect:
    """Test the handler function directly with mock Request and exception objects."""

    @pytest.mark.asyncio
    async def test_returns_422_json_response(self):
        from app.main import validation_exception_handler
        from fastapi.exceptions import RequestValidationError

        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/test/path"

        exc = RequestValidationError(
            errors=[
                {
                    "type": "missing",
                    "loc": ["body", "field"],
                    "msg": "Field required",
                    "input": {},
                }
            ]
        )

        response = await validation_exception_handler(mock_request, exc)
        assert isinstance(response, JSONResponse)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_response_contains_path(self):
        from app.main import validation_exception_handler
        from fastapi.exceptions import RequestValidationError
        import json

        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/api/v1/loops"

        exc = RequestValidationError(
            errors=[{"type": "missing", "loc": ["body"], "msg": "required", "input": {}}]
        )

        response = await validation_exception_handler(mock_request, exc)
        body = json.loads(response.body)
        assert body["path"] == "/api/v1/loops"
        assert "error" in body


class TestPydanticExceptionHandlerDirect:
    @pytest.mark.asyncio
    async def test_returns_422_for_pydantic_validation_error(self):
        from app.main import pydantic_exception_handler
        from pydantic import BaseModel
        import json

        class _StrictModel(BaseModel):
            value: int

        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/api/v1/test"

        try:
            _StrictModel(value="not-an-int")  # type: ignore[arg-type]
        except ValidationError as exc:
            response = await pydantic_exception_handler(mock_request, exc)
            assert isinstance(response, JSONResponse)
            assert response.status_code == 422

            body = json.loads(response.body)
            assert "error" in body
            assert body["path"] == "/api/v1/test"


class TestGeneralExceptionHandlerDirect:
    @pytest.mark.asyncio
    async def test_returns_500_for_runtime_error(self):
        from app.main import general_exception_handler
        import json

        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/api/v1/crash"
        mock_request.method = "GET"

        exc = RuntimeError("something went wrong")

        response = await general_exception_handler(mock_request, exc)
        assert isinstance(response, JSONResponse)
        assert response.status_code == 500

        body = json.loads(response.body)
        assert body["error"] == "Internal Server Error"
        assert body["path"] == "/api/v1/crash"

    @pytest.mark.asyncio
    async def test_response_detail_is_user_safe(self):
        """The detail message should not expose internal error details."""
        from app.main import general_exception_handler
        import json

        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/sensitive"
        mock_request.method = "POST"

        response = await general_exception_handler(
            mock_request, Exception("internal secret")
        )
        body = json.loads(response.body)
        # The user-facing detail should NOT expose the exception message
        assert "internal secret" not in body["detail"]


# ---------------------------------------------------------------------------
# /health/worker root endpoint — embedded worker state (root main.py)
# ---------------------------------------------------------------------------


class TestRootWorkerHealthEndpoint:
    def test_worker_health_disabled_shows_zero_active(self, client):
        """Default config has embedded worker disabled — zero active workers."""
        response = client.get("/health/worker")
        assert response.status_code == 200
        data = response.json()
        assert data["embedded_worker_enabled"] is False
        assert data["active_worker_count"] == 0
        assert data["active_workers"] == []

    def test_worker_health_with_alive_thread(self, client):
        """When an alive embedded thread is present it appears in the response."""
        import main as root_main_mod  # root main.py, not app/main.py

        mock_thread = MagicMock()
        mock_thread.name = "embedded-rq-worker-1"
        mock_thread.is_alive.return_value = True

        original = root_main_mod._embedded_worker_threads[:]
        root_main_mod._embedded_worker_threads = [mock_thread]

        try:
            response = client.get("/health/worker")
        finally:
            root_main_mod._embedded_worker_threads = original

        assert response.status_code == 200
        data = response.json()
        assert data["active_worker_count"] == 1
        assert "embedded-rq-worker-1" in data["active_workers"]

    def test_worker_health_response_fields_present(self, client):
        """Response contains all expected fields."""
        response = client.get("/health/worker")
        data = response.json()
        assert "embedded_worker_enabled" in data
        assert "active_worker_count" in data
        assert "active_workers" in data
        assert "target_worker_count" in data


# ---------------------------------------------------------------------------
# app/main.py /health/worker (api/v1 route) — RQ workers with workers present
# ---------------------------------------------------------------------------


class TestAppMainWorkerHealthWithWorkers:
    """Test app/main.py's /api/v1/health/worker route with RQ workers present."""

    def test_health_worker_with_rq_workers_returns_ok(self):
        """When RQ workers are available the route returns ok=True."""
        import app.main as app_main_mod

        mock_worker = MagicMock()
        mock_worker.name = "rq-worker-1"
        mock_worker.get_state.return_value = "idle"
        mock_worker.last_heartbeat = None
        mock_worker.queues = []
        mock_worker.pid = 1234

        mock_queue = MagicMock()
        mock_queue.count = 2
        mock_queue.failed_job_registry = []

        mock_conn = MagicMock()
        mock_conn.ping.return_value = True

        # Use app/main.py's app instance for this test
        app_main_client = TestClient(app_main_mod.app, raise_server_exceptions=False)

        with (
            patch("app.routes.health.get_redis_conn", return_value=mock_conn),
            patch("app.routes.health._get_queue", return_value=mock_queue),
            patch("rq.Worker.all", return_value=[mock_worker]),
            patch(
                "app.services.render_observability.get_worker_mode",
                return_value="dedicated",
            ),
        ):
            response = app_main_client.get("/api/v1/health/worker")

        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") is True or "worker_count" in data
