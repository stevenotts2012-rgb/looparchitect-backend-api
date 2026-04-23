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
