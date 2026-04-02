"""
Tests for render job status polling endpoints.

Covers:
  GET /api/v1/jobs/{job_id}          – fetch single job status
  GET /api/v1/loops/{loop_id}/jobs   – list jobs for a loop
"""

import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import app.db as db_module
from app.models.job import RenderJob
from app.models.loop import Loop
from app.main import app


pytestmark = pytest.mark.usefixtures("fresh_sqlite_integration_db")


@pytest.fixture
def client():
    """Test client backed by the root main.py FastAPI app."""
    return TestClient(app)


@pytest.fixture
def db():
    """Live DB session that shares the temp SQLite used by the fixture."""
    session = db_module.SessionLocal()
    yield session
    session.close()


@pytest.fixture
def test_loop(db):
    """Create a minimal Loop row so render jobs can reference it."""
    loop = Loop(
        name="Job Test Loop",
        file_key="uploads/job_test.wav",
        bpm=120.0,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


@pytest.fixture
def queued_job(db, test_loop):
    """A render job in the 'queued' state."""
    job = RenderJob(
        id=str(uuid.uuid4()),
        loop_id=test_loop.id,
        job_type="render_arrangement",
        status="queued",
        progress=0.0,
        created_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@pytest.fixture
def completed_job(db, test_loop):
    """A render job in the 'succeeded' state (normalised to 'completed' by schema)."""
    job = RenderJob(
        id=str(uuid.uuid4()),
        loop_id=test_loop.id,
        job_type="render_arrangement",
        status="succeeded",
        progress=100.0,
        created_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}
# ---------------------------------------------------------------------------

class TestGetJobStatus:
    """GET /api/v1/jobs/{job_id} – single job status polling endpoint."""

    def test_unknown_job_id_returns_404(self, client):
        """Endpoint must be reachable and return 404 for a non-existent job."""
        response = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_queued_job_returns_200_with_correct_fields(self, client, queued_job):
        """A queued job should return HTTP 200 with expected payload shape."""
        response = client.get(f"/api/v1/jobs/{queued_job.id}")
        assert response.status_code == 200, response.text

        data = response.json()
        assert data["job_id"] == queued_job.id
        assert data["loop_id"] == queued_job.loop_id
        assert data["status"] == "queued"
        assert data["progress"] == 0.0
        assert data["job_type"] == "render_arrangement"

    def test_succeeded_status_normalised_to_completed(self, client, completed_job):
        """Backend 'succeeded' must be exposed as 'completed' by the polling endpoint."""
        response = client.get(f"/api/v1/jobs/{completed_job.id}")
        assert response.status_code == 200, response.text

        data = response.json()
        assert data["status"] == "completed", (
            "The API must normalise internal 'succeeded' to 'completed' for the frontend."
        )
        assert data["progress"] == 100.0

    def test_response_contains_poll_fields(self, client, queued_job):
        """Response must include all fields the frontend polling code expects."""
        response = client.get(f"/api/v1/jobs/{queued_job.id}")
        assert response.status_code == 200

        data = response.json()
        # Fields consumed by looparchitect-frontend/src/api/client.ts JobStatusResponse
        for field in ("job_id", "loop_id", "job_type", "status", "progress",
                      "progress_message", "created_at", "started_at",
                      "finished_at", "error_message", "retry_count"):
            assert field in data, f"Missing expected field '{field}' in job status response"


# ---------------------------------------------------------------------------
# GET /api/v1/loops/{loop_id}/jobs
# ---------------------------------------------------------------------------

class TestListLoopJobs:
    """GET /api/v1/loops/{loop_id}/jobs – job history for a loop."""

    def test_unknown_loop_returns_404(self, client):
        """Non-existent loop ID should return 404."""
        response = client.get("/api/v1/loops/999999/jobs")
        assert response.status_code == 404

    def test_returns_jobs_for_loop(self, client, queued_job, test_loop):
        """Should return a list containing the queued job for the test loop."""
        response = client.get(f"/api/v1/loops/{test_loop.id}/jobs")
        assert response.status_code == 200, response.text

        data = response.json()
        assert data["loop_id"] == test_loop.id
        job_ids = [j["job_id"] for j in data["jobs"]]
        assert queued_job.id in job_ids
