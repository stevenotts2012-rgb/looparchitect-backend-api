"""
Tests for audio arrangement generation routes.
"""

import json
from unittest.mock import patch, MagicMock
from pathlib import Path

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
    """Create a test loop."""
    loop = Loop(
        name="Test Loop",
        file_url="/uploads/test_loop.wav",
        bpm=120.0,
        musical_key="C",
        genre="electronic",
        duration_seconds=4.0,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


class TestArrangementGeneration:
    """Test arrangement generation endpoint."""

    def test_generate_arrangement_creates_queued_job(self, test_loop, client):
        """POST /arrangements/generate should create arrangement with status=queued."""
        response = client.post(
            "/api/v1/arrangements/generate",
            json={
                "loop_id": test_loop.id,
                "target_seconds": 60,
                "genre": "electronic",
                "intensity": "medium",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "arrangement_id" in data
        assert data["loop_id"] == test_loop.id
        assert data["status"] == "queued"

    def test_generate_arrangement_validates_loop_exists(self, client):
        """POST /arrangements/generate should return 404 for non-existent loop."""
        response = client.post(
            "/api/v1/arrangements/generate",
            json={
                "loop_id": 999,
                "target_seconds": 60,
            },
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_generate_arrangement_validates_target_seconds(self, test_loop, client):
        """POST /arrangements/generate should validate target_seconds range."""
        # Too short
        response = client.post(
            "/api/v1/arrangements/generate",
            json={
                "loop_id": test_loop.id,
                "target_seconds": 5,  # Min is 10
            },
        )
        assert response.status_code == 422

        # Too long
        response = client.post(
            "/api/v1/arrangements/generate",
            json={
                "loop_id": test_loop.id,
                "target_seconds": 3601,  # Max is 3600
            },
        )
        assert response.status_code == 422

    def test_generate_arrangement_stores_metadata(self, test_loop, db, client):
        """POST /arrangements/generate should store all metadata in DB."""
        response = client.post(
            "/api/v1/arrangements/generate",
            json={
                "loop_id": test_loop.id,
                "target_seconds": 120,
                "genre": "electronic",
                "intensity": "high",
                "include_stems": True,
            },
        )

        assert response.status_code == 202
        arrangement_id = response.json()["arrangement_id"]

        # Check database record
        arrangement = db.query(Arrangement).filter_by(id=arrangement_id).first()
        assert arrangement is not None
        assert arrangement.loop_id == test_loop.id
        assert arrangement.target_seconds == 120
        assert arrangement.genre == "electronic"
        assert arrangement.intensity == "high"
        assert arrangement.include_stems is True


class TestArrangementStatus:
    """Test arrangement status retrieval."""

    def test_get_arrangement_returns_details(self, test_loop, db, client):
        """GET /arrangements/{id} should return full arrangement details."""
        # Create an arrangement
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="processing",
            target_seconds=60,
            genre="electronic",
            intensity="medium",
        )
        db.add(arrangement)
        db.commit()
        db.refresh(arrangement)

        response = client.get(
            f"/api/v1/arrangements/{arrangement.id}",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == arrangement.id
        assert data["status"] == "processing"
        assert data["target_seconds"] == 60
        assert data["genre"] == "electronic"
        assert data["loop_id"] == test_loop.id

    def test_get_arrangement_not_found(self, client):
        """GET /arrangements/{id} should return 404 for non-existent arrangement."""
        response = client.get("/api/v1/arrangements/999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_arrangement_includes_output_url_when_complete(self, test_loop, db, client):
        """GET /arrangements/{id} should include output_file_url when complete."""
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="complete",
            target_seconds=60,
            output_file_url="/renders/arrangements/abc123.wav",
            arrangement_json='{"sections": []}',
        )
        db.add(arrangement)
        db.commit()
        db.refresh(arrangement)

        response = client.get(f"/api/v1/arrangements/{arrangement.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["output_file_url"] == "/renders/arrangements/abc123.wav"
        assert data["arrangement_json"] == '{"sections": []}'


class TestArrangementDownload:
    """Test arrangement file download."""

    def test_download_queued_arrangement_returns_409(self, test_loop, db, client):
        """GET /arrangements/{id}/download should return 409 if status=queued."""
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="queued",
            target_seconds=60,
        )
        db.add(arrangement)
        db.commit()

        response = client.get(
            f"/api/v1/arrangements/{arrangement.id}/download",
        )

        assert response.status_code == 409
        assert "still" in response.json()["detail"].lower()

    def test_download_processing_arrangement_returns_409(self, test_loop, db, client):
        """GET /arrangements/{id}/download should return 409 if status=processing."""
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="processing",
            target_seconds=60,
        )
        db.add(arrangement)
        db.commit()

        response = client.get(
            f"/api/v1/arrangements/{arrangement.id}/download",
        )

        assert response.status_code == 409

    def test_download_failed_arrangement_returns_400(self, test_loop, db, client):
        """GET /arrangements/{id}/download should return 400 if status=failed."""
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="failed",
            target_seconds=60,
            error_message="Audio processing failed",
        )
        db.add(arrangement)
        db.commit()

        response = client.get(
            f"/api/v1/arrangements/{arrangement.id}/download",
        )

        assert response.status_code == 400
        assert "failed" in response.json()["detail"].lower()

    def test_download_not_found(self, client):
        """GET /arrangements/{id}/download should return 404 if arrangement doesn't exist."""
        response = client.get("/api/v1/arrangements/999/download")

        assert response.status_code == 404

    @patch("pathlib.Path.exists")
    def test_download_complete_arrangement_returns_file(
        self,
        mock_exists,
        test_loop,
        db,
        tmp_path,
        client,
    ):
        """GET /arrangements/{id}/download should return file if status=complete."""
        # Create a test WAV file
        test_file = tmp_path / "renders" / "arrangements" / "test.wav"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt \x00\x00\x00\x00")

        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="complete",
            target_seconds=60,
            output_file_url="/renders/arrangements/test.wav",
        )
        db.add(arrangement)
        db.commit()

        # Mock Path.exists to return True for our test file
        mock_exists.return_value = True

        response = client.get(
            f"/api/v1/arrangements/{arrangement.id}/download",
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert "arrangement_" in response.headers.get(
            "content-disposition", ""
        )


class TestArrangementIntegration:
    """Integration tests for arrangement workflow."""

    @patch("app.services.arrangement_engine.generate_arrangement")
    def test_arrangement_workflow(self, mock_generate, test_loop, db, client):
        """Test complete workflow: generate -> poll status -> download."""
        # Mock the generation service
        mock_generate.return_value = (
            "/renders/arrangements/mock_uuid.wav",
            '{"sections": []}',
        )

        # 1. Create arrangement
        response = client.post(
            "/api/v1/arrangements/generate",
            json={
                "loop_id": test_loop.id,
                "target_seconds": 60,
            },
        )
        assert response.status_code == 202
        arrangement_id = response.json()["arrangement_id"]

        # 2. Check initial status is queued
        response = client.get(f"/api/v1/arrangements/{arrangement_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

        # 3. Download should fail while queued
        response = client.get(
            f"/api/v1/arrangements/{arrangement_id}/download",
        )
        assert response.status_code == 409

        # 4. Simulate job completion
        arrangement = db.query(Arrangement).filter_by(id=arrangement_id).first()
        arrangement.status = "complete"
        arrangement.output_file_url = "/renders/arrangements/mock_uuid.wav"
        arrangement.arrangement_json = '{"sections": []}'
        db.commit()

        # 5. Check status is now complete
        response = client.get(f"/api/v1/arrangements/{arrangement_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "complete"
        assert response.json()["output_file_url"] is not None
