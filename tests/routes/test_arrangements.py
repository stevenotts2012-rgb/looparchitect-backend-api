"""
Tests for Phase B arrangement routes.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from main import app


@pytest.fixture
def client():
    """Create a test client for each test."""
    return TestClient(app)


@pytest.fixture
def db():
    """Get a test database session."""
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def test_loop(db):
    """Create a test loop with S3 key."""
    loop = Loop(
        name="Test Loop",
        file_key="uploads/test_loop.wav",
        bpm=120.0,
        musical_key="C",
        genre="electronic",
        duration_seconds=4.0,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


class TestArrangementCreation:
    """Test arrangement creation endpoint."""

    def test_create_arrangement_creates_row(self, test_loop, client, db):
        """POST /arrangements should create a queued arrangement row."""
        fake_job = SimpleNamespace(id="job-create-123")
        with patch("app.routes.arrangements.is_redis_available", return_value=True), patch("app.routes.arrangements.create_render_job", return_value=(fake_job, False)) as mock_enqueue:
            response = client.post(
                "/api/v1/arrangements/",
                json={
                    "loop_id": test_loop.id,
                    "target_duration_seconds": 180,
                },
            )

        assert response.status_code == 202
        data = response.json()
        assert data["loop_id"] == test_loop.id
        assert data["status"] == "queued"

        arrangement = db.query(Arrangement).filter_by(id=data["id"]).first()
        assert arrangement is not None
        assert arrangement.target_seconds == 180
        assert arrangement.status == "queued"
        mock_enqueue.assert_called_once()

    def test_generate_arrangement_enqueues_redis_job(self, test_loop, client, db):
        """POST /arrangements/generate should enqueue through create_render_job and return render_job_ids."""
        fake_job = SimpleNamespace(id="job-123")

        with patch("app.routes.arrangements.is_redis_available", return_value=True), patch("app.routes.arrangements.create_render_job", return_value=(fake_job, False)) as mock_enqueue:
            response = client.post(
                "/api/v1/arrangements/generate",
                json={
                    "loop_id": test_loop.id,
                    "target_seconds": 60,
                    "genre": "electronic",
                    "use_ai_parsing": False,
                },
            )

        assert response.status_code == 202, response.text
        payload = response.json()
        assert payload["arrangement_id"] > 0
        assert payload["loop_id"] == test_loop.id
        assert payload["render_job_ids"] == ["job-123"]

        # Ensure enqueue path is used and arrangement_id is passed to worker params
        assert mock_enqueue.called
        call_args, _ = mock_enqueue.call_args
        assert call_args[1] == test_loop.id
        assert call_args[2]["arrangement_id"] == payload["arrangement_id"]

    def test_generate_arrangement_marks_arrangement_failed_when_enqueue_runtime_error(self, test_loop, client, db):
        """POST /arrangements/generate should not leave arrangement stuck in queued when enqueue fails."""
        with patch("app.routes.arrangements.is_redis_available", return_value=True), patch("app.routes.arrangements.create_render_job", side_effect=RuntimeError("redis unavailable")):
            response = client.post(
                "/api/v1/arrangements/generate",
                json={
                    "loop_id": test_loop.id,
                    "target_seconds": 60,
                    "genre": "electronic",
                    "use_ai_parsing": False,
                },
            )

        assert response.status_code == 503

        arrangement = (
            db.query(Arrangement)
            .filter(Arrangement.loop_id == test_loop.id)
            .order_by(Arrangement.id.desc())
            .first()
        )
        assert arrangement is not None
        assert arrangement.status == "failed"
        assert arrangement.progress_message == "Queue unavailable"
        assert arrangement.error_message is not None
        assert "Queue enqueue failed" in arrangement.error_message

    def test_generate_arrangement_rejects_when_redis_unavailable_before_row_creation(self, test_loop, client, db):
        """POST /arrangements/generate should return 503 without creating an arrangement row when Redis is down."""
        with patch("app.routes.arrangements.is_redis_available", return_value=False):
            response = client.post(
                "/api/v1/arrangements/generate",
                json={
                    "loop_id": test_loop.id,
                    "target_seconds": 60,
                    "genre": "electronic",
                    "use_ai_parsing": False,
                },
            )

        assert response.status_code == 503
        assert "Background job queue is unavailable" in response.text

        arrangement_count = db.query(Arrangement).filter(Arrangement.loop_id == test_loop.id).count()
        assert arrangement_count == 0


class TestArrangementRetrieval:
    """Test arrangement GET endpoints."""

    def test_get_arrangement_returns_record(self, test_loop, db, client):
        """GET /arrangements/{id} should return arrangement record."""
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="done",
            target_seconds=180,
            output_s3_key="arrangements/1.wav",
            output_url="https://example.com/arrangements/1.wav",
        )
        db.add(arrangement)
        db.commit()
        db.refresh(arrangement)

        response = client.get(f"/api/v1/arrangements/{arrangement.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == arrangement.id
        assert data["status"] == "done"
        assert data["output_s3_key"] == "arrangements/1.wav"
        assert data["output_url"] == "https://example.com/arrangements/1.wav"

    def test_list_arrangements_filters_by_loop_id(self, test_loop, db, client):
        """GET /arrangements?loop_id should filter results."""
        arrangement_a = Arrangement(loop_id=test_loop.id, status="queued", target_seconds=120)
        arrangement_b = Arrangement(loop_id=test_loop.id + 1, status="queued", target_seconds=120)
        db.add_all([arrangement_a, arrangement_b])
        db.commit()

        response = client.get(f"/api/v1/arrangements/?loop_id={test_loop.id}")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["loop_id"] == test_loop.id
