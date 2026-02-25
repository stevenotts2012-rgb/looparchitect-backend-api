"""
Tests for Phase B arrangement routes.
"""

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
        with patch("app.routes.arrangements.run_arrangement_job") as mock_job:
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
        mock_job.assert_called_once()


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
