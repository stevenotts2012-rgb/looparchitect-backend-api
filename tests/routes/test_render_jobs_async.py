"""
Tests for the async render POST endpoint in app/routes/render_jobs.py.

Previously-untested paths in render_jobs.py (lines 31-66):
- POST /loops/{loop_id}/render-async when Redis unavailable → 503
- POST /loops/{loop_id}/render-async when loop not found → 404
- POST /loops/{loop_id}/render-async when loop has no audio file → 400
- POST /loops/{loop_id}/render-async success path → 202
- POST /loops/{loop_id}/render-async when create_render_job raises ValueError → 400
- POST /loops/{loop_id}/render-async when create_render_job raises RuntimeError → 503
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.db as db_module
from app.models.loop import Loop
from app.models.job import RenderJob
from main import app


pytestmark = pytest.mark.usefixtures("fresh_sqlite_integration_db")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = db_module.SessionLocal()
    yield session
    session.close()


@pytest.fixture
def test_loop_with_file(db):
    """Loop that has a file_key so it passes the audio-file check."""
    loop = Loop(
        name="Render Jobs Test Loop",
        file_key="uploads/render_jobs_test.wav",
        bpm=120.0,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


@pytest.fixture
def test_loop_no_file(db):
    """Loop with neither file_key nor file_url."""
    loop = Loop(
        name="No File Loop",
        file_key=None,
        file_url=None,
        bpm=120.0,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


# ---------------------------------------------------------------------------
# POST /api/v1/loops/{loop_id}/render-async
# ---------------------------------------------------------------------------


class TestRenderAsyncEndpoint:
    def test_redis_unavailable_returns_503(self, client, test_loop_with_file):
        with patch("app.routes.render_jobs.is_redis_available", return_value=False):
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )
        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()

    def test_loop_not_found_returns_404(self, client):
        with patch("app.routes.render_jobs.is_redis_available", return_value=True):
            response = client.post("/api/v1/loops/999999/render-async", json={})
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_loop_no_audio_file_returns_400(self, client, test_loop_no_file):
        with patch("app.routes.render_jobs.is_redis_available", return_value=True):
            response = client.post(
                f"/api/v1/loops/{test_loop_no_file.id}/render-async", json={}
            )
        assert response.status_code == 400
        assert "no associated audio file" in response.json()["detail"].lower()

    def test_successful_job_creation_returns_202(self, client, test_loop_with_file):
        fake_job = RenderJob(
            id=str(uuid.uuid4()),
            loop_id=test_loop_with_file.id,
            job_type="render_arrangement",
            status="queued",
            progress=0.0,
            created_at=datetime.utcnow(),
        )
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", return_value=(fake_job, False)):
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )
        assert response.status_code == 202, response.text
        data = response.json()
        assert data["job_id"] == fake_job.id
        assert data["loop_id"] == test_loop_with_file.id
        assert data["status"] == "queued"
        assert data["deduplicated"] is False

    def test_deduplicated_job_returns_202(self, client, test_loop_with_file):
        fake_job = RenderJob(
            id=str(uuid.uuid4()),
            loop_id=test_loop_with_file.id,
            job_type="render_arrangement",
            status="queued",
            progress=0.0,
            created_at=datetime.utcnow(),
        )
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", return_value=(fake_job, True)):
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )
        assert response.status_code == 202
        assert response.json()["deduplicated"] is True

    def test_create_render_job_value_error_returns_400(self, client, test_loop_with_file):
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch(
                 "app.routes.render_jobs.create_render_job",
                 side_effect=ValueError("Invalid params"),
             ):
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )
        assert response.status_code == 400
        assert "Invalid params" in response.json()["detail"]

    def test_create_render_job_runtime_error_returns_503(self, client, test_loop_with_file):
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch(
                 "app.routes.render_jobs.create_render_job",
                 side_effect=RuntimeError("redis unavailable"),
             ):
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )
        assert response.status_code == 503
        assert "redis unavailable" in response.json()["detail"]

    def test_response_includes_poll_url(self, client, test_loop_with_file):
        fake_job = RenderJob(
            id=str(uuid.uuid4()),
            loop_id=test_loop_with_file.id,
            job_type="render_arrangement",
            status="queued",
            progress=0.0,
            created_at=datetime.utcnow(),
        )
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", return_value=(fake_job, False)):
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )
        data = response.json()
        assert "poll_url" in data
        assert fake_job.id in data["poll_url"]

    def test_render_config_fields_passed_to_create_job(self, client, test_loop_with_file):
        """Verify that config fields (genre, energy, etc.) are forwarded."""
        fake_job = RenderJob(
            id=str(uuid.uuid4()),
            loop_id=test_loop_with_file.id,
            job_type="render_arrangement",
            status="queued",
            progress=0.0,
            created_at=datetime.utcnow(),
        )
        captured_params = {}

        def capture_create(db, loop_id, params, **kwargs):
            captured_params.update(params)
            return fake_job, False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_create):
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async",
                json={"genre": "hip-hop", "energy": "high"},
            )
        assert response.status_code == 202
        assert captured_params.get("genre") == "hip-hop"
        assert captured_params.get("energy") == "high"


# ---------------------------------------------------------------------------
# POST /api/v1/loops/{loop_id}/render-async – enqueue-level tests
# ---------------------------------------------------------------------------


class TestRenderAsyncEnqueue:
    """Tests that exercise the actual Redis enqueue path inside create_render_job
    (patching at get_queue / queue.enqueue level, not at create_render_job level)."""

    def _make_mock_rq_job(self, job_id: str):
        """Return a MagicMock that mimics an rq.job.Job with a known id."""
        mock = MagicMock()
        mock.id = job_id
        return mock

    def test_202_only_returned_after_successful_enqueue(self, client, test_loop_with_file):
        """Endpoint must return 202 only when queue.enqueue() succeeds."""
        expected_job_id = str(uuid.uuid4())
        mock_rq_job = self._make_mock_rq_job(expected_job_id)
        mock_queue = MagicMock()
        mock_queue.name = "render"
        mock_queue.enqueue.return_value = mock_rq_job

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.services.job_service.get_queue", return_value=mock_queue), \
             patch("app.services.job_service.uuid") as mock_uuid:
            mock_uuid.uuid4.return_value = uuid.UUID(expected_job_id)
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )

        assert response.status_code == 202, response.text
        assert mock_queue.enqueue.called, "queue.enqueue() must be called for a 202 response"

    def test_queue_enqueue_failure_returns_503(self, client, test_loop_with_file):
        """When queue.enqueue() raises, the endpoint must return 503 (not 202)."""
        mock_queue = MagicMock()
        mock_queue.name = "render"
        mock_queue.enqueue.side_effect = Exception("Redis connection refused")

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.services.job_service.get_queue", return_value=mock_queue):
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )

        assert response.status_code == 503, response.text
        assert mock_queue.enqueue.called

    def test_returned_job_id_matches_rq_job_id(self, client, test_loop_with_file):
        """The job_id in the response body must equal the RQ job id."""
        expected_job_id = str(uuid.uuid4())
        mock_rq_job = self._make_mock_rq_job(expected_job_id)
        mock_queue = MagicMock()
        mock_queue.name = "render"
        mock_queue.enqueue.return_value = mock_rq_job

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.services.job_service.get_queue", return_value=mock_queue), \
             patch("app.services.job_service.uuid") as mock_uuid:
            mock_uuid.uuid4.return_value = uuid.UUID(expected_job_id)
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )

        assert response.status_code == 202, response.text
        data = response.json()
        assert data["job_id"] == expected_job_id, (
            "Response job_id must match the RQ job id to ensure the frontend polls the right job"
        )

    def test_enqueue_log_fields_present(self, client, test_loop_with_file, caplog):
        """Structured log records must contain all required enqueue-proof fields."""
        expected_job_id = str(uuid.uuid4())
        mock_rq_job = self._make_mock_rq_job(expected_job_id)
        mock_queue = MagicMock()
        mock_queue.name = "render"
        mock_queue.enqueue.return_value = mock_rq_job

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.services.job_service.get_queue", return_value=mock_queue), \
             patch("app.services.job_service.uuid") as mock_uuid, \
             caplog.at_level(logging.INFO, logger="app.services.job_service"):
            mock_uuid.uuid4.return_value = uuid.UUID(expected_job_id)
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )

        assert response.status_code == 202, response.text

        all_messages = " ".join(r.message for r in caplog.records)

        assert "render_job_db_created" in all_messages, \
            "Log must contain render_job_db_created event"
        assert "render_job_enqueue_attempt" in all_messages, \
            "Log must contain render_job_enqueue_attempt event"
        assert "render_job_enqueued_success" in all_messages, \
            "Log must contain render_job_enqueued_success event"

        # Verify required fields appear in the success log
        success_record = next(
            r for r in caplog.records if "render_job_enqueued_success" in r.message
        )
        msg = success_record.message
        assert "job_id=" in msg, "render_job_enqueued_success must include job_id"
        assert "rq_job_id=" in msg, "render_job_enqueued_success must include rq_job_id"
        assert "loop_id=" in msg, "render_job_enqueued_success must include loop_id"
        assert "queue_name=" in msg, "render_job_enqueued_success must include queue_name"

    def test_request_received_log_emitted(self, client, test_loop_with_file, caplog):
        """render_async_request_received must be logged at the route level."""
        fake_job = RenderJob(
            id=str(uuid.uuid4()),
            loop_id=test_loop_with_file.id,
            job_type="render_arrangement",
            status="queued",
            progress=0.0,
            created_at=datetime.utcnow(),
        )
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", return_value=(fake_job, False)), \
             caplog.at_level(logging.INFO, logger="app.routes.render_jobs"):
            client.post(f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={})

        assert any(
            "render_async_request_received" in r.message for r in caplog.records
        ), "render_async_request_received log must be emitted at the route level"

    def test_worker_function_is_render_loop_worker(self, client, test_loop_with_file):
        """queue.enqueue must be called with render_loop_worker as the function."""
        from app.workers.render_worker import render_loop_worker

        mock_queue = MagicMock()
        mock_queue.name = "render"
        mock_queue.enqueue.return_value = MagicMock(id=str(uuid.uuid4()))

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.services.job_service.get_queue", return_value=mock_queue):
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )

        assert response.status_code == 202, response.text
        call_args = mock_queue.enqueue.call_args
        assert call_args is not None
        # First positional arg to enqueue is the function
        enqueued_fn = call_args[0][0]
        assert enqueued_fn is render_loop_worker, (
            "Worker function passed to queue.enqueue must be render_loop_worker"
        )

    def test_queue_name_is_render(self, client, test_loop_with_file):
        """get_queue must be called with name='render'."""
        mock_queue = MagicMock()
        mock_queue.name = "render"
        mock_queue.enqueue.return_value = MagicMock(id=str(uuid.uuid4()))

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.services.job_service.get_queue", return_value=mock_queue) as mock_get_queue:
            response = client.post(
                f"/api/v1/loops/{test_loop_with_file.id}/render-async", json={}
            )

        assert response.status_code == 202, response.text
        call_kwargs = mock_get_queue.call_args
        assert call_kwargs is not None
        # get_queue is called as get_queue(name=DEFAULT_RENDER_QUEUE_NAME)
        assert call_kwargs.kwargs.get("name") == "render", (
            "Queue name passed to get_queue must be 'render'"
        )
