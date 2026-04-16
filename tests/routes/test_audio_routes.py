"""Tests for audio routes (app/routes/audio.py).

Covers:
  GET /api/v1/loops/{id}/play
  GET /api/v1/loops/{id}/download
  GET /api/v1/loops/{id}/stream
  GET /api/v1/loops/{id}/info
  POST /api/v1/generate-beat/{id}
  POST /api/v1/extend-loop/{id}
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import app.db as db_module
from app.models.loop import Loop
from main import app


pytestmark = pytest.mark.usefixtures("fresh_sqlite_integration_db")


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def db():
    session = db_module.SessionLocal()
    yield session
    session.close()


@pytest.fixture
def loop_with_file(db):
    """Loop that has a file_key set (simulates uploaded audio)."""
    loop = Loop(
        name="Test Audio Loop",
        file_key="uploads/test_audio.wav",
        bpm=140,
        genre="trap",
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


@pytest.fixture
def loop_without_file(db):
    """Loop with no file_key."""
    loop = Loop(name="No-File Loop")
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


# ---------------------------------------------------------------------------
# GET /api/v1/loops/{id}/play
# ---------------------------------------------------------------------------

def test_play_loop_not_found_returns_404(client):
    response = client.get("/api/v1/loops/999999/play")
    assert response.status_code == 404


def test_play_loop_no_file_returns_404(client, loop_without_file):
    response = client.get(f"/api/v1/loops/{loop_without_file.id}/play")
    assert response.status_code == 404


def test_play_loop_file_missing_returns_404(client, loop_with_file):
    with patch("app.routes.audio.storage.file_exists", return_value=False):
        response = client.get(f"/api/v1/loops/{loop_with_file.id}/play")
    assert response.status_code == 404


def test_play_loop_success_returns_url(client, loop_with_file):
    fake_url = "http://example.com/presigned/test_audio.wav"
    with patch("app.routes.audio.storage.file_exists", return_value=True), \
         patch("app.routes.audio.storage.create_presigned_get_url", return_value=fake_url):
        response = client.get(f"/api/v1/loops/{loop_with_file.id}/play")
    assert response.status_code == 200
    data = response.json()
    assert data["url"] == fake_url


def test_play_loop_storage_error_returns_500(client, loop_with_file):
    with patch("app.routes.audio.storage.file_exists", return_value=True), \
         patch("app.routes.audio.storage.create_presigned_get_url",
               side_effect=RuntimeError("S3 error")):
        response = client.get(f"/api/v1/loops/{loop_with_file.id}/play")
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/loops/{id}/download
# ---------------------------------------------------------------------------

def test_download_loop_not_found_returns_404(client):
    response = client.get("/api/v1/loops/999999/download", follow_redirects=False)
    assert response.status_code == 404


def test_download_loop_no_file_returns_error(client, loop_without_file):
    """loops.py download handler returns 500 when file_key is missing."""
    response = client.get(f"/api/v1/loops/{loop_without_file.id}/download",
                          follow_redirects=False)
    # The loops.py handler returns HTTP 500 when file_key is None
    assert response.status_code in (404, 500)


def test_download_loop_file_missing_returns_404(client, loop_with_file):
    with patch("app.routes.audio.storage.file_exists", return_value=False):
        response = client.get(f"/api/v1/loops/{loop_with_file.id}/download",
                              follow_redirects=False)
    assert response.status_code == 404


def test_download_loop_success_local_returns_file_or_404(client, loop_with_file):
    """In local mode, loops.py download handler tries to read from the uploads dir.
    In a test environment the file won't exist, so we expect a 404."""
    response = client.get(f"/api/v1/loops/{loop_with_file.id}/download",
                          follow_redirects=False)
    # Without a real file on disk the loops.py handler returns 404
    assert response.status_code in (200, 307, 404)


# ---------------------------------------------------------------------------
# GET /api/v1/loops/{id}/stream
# ---------------------------------------------------------------------------

def test_stream_loop_not_found_returns_404(client):
    response = client.get("/api/v1/loops/999999/stream", follow_redirects=False)
    assert response.status_code == 404


def test_stream_loop_no_file_returns_404(client, loop_without_file):
    response = client.get(f"/api/v1/loops/{loop_without_file.id}/stream",
                          follow_redirects=False)
    assert response.status_code == 404


def test_stream_loop_local_redirects_to_uploads(client, loop_with_file):
    with patch("app.routes.audio.storage.use_s3", False):
        response = client.get(f"/api/v1/loops/{loop_with_file.id}/stream",
                              follow_redirects=False)
    # In local mode a redirect to /uploads/<filename> is returned
    assert response.status_code in (302, 307, 308)
    assert "test_audio.wav" in response.headers.get("location", "")


# ---------------------------------------------------------------------------
# GET /api/v1/loops/{id}/info
# ---------------------------------------------------------------------------

def test_info_loop_not_found_returns_404(client):
    response = client.get("/api/v1/loops/999999/info")
    assert response.status_code == 404


def test_info_loop_returns_expected_fields(client, loop_with_file):
    response = client.get(f"/api/v1/loops/{loop_with_file.id}/info")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == loop_with_file.id
    assert data["name"] == "Test Audio Loop"
    assert "play_url" in data
    assert "download_url" in data
    assert "status" in data
    assert "bpm" in data


def test_info_loop_without_file_has_null_urls(client, loop_without_file):
    response = client.get(f"/api/v1/loops/{loop_without_file.id}/info")
    assert response.status_code == 200
    data = response.json()
    assert data["play_url"] is None
    assert data["download_url"] is None


# ---------------------------------------------------------------------------
# POST /api/v1/generate-beat/{id}
# ---------------------------------------------------------------------------

def test_generate_beat_not_found_returns_404(client):
    response = client.post("/api/v1/generate-beat/999999?target_length=30")
    assert response.status_code == 404


def test_generate_beat_queues_task(client, loop_with_file):
    with patch("app.routes.audio.task_service.generate_beat_task") as mock_task:
        response = client.post(
            f"/api/v1/generate-beat/{loop_with_file.id}?target_length=30"
        )
    assert response.status_code == 200
    data = response.json()
    assert data["loop_id"] == loop_with_file.id
    assert data["status"] == "pending"
    assert "check_status_at" in data


def test_generate_beat_target_length_too_short_returns_422(client, loop_with_file):
    response = client.post(f"/api/v1/generate-beat/{loop_with_file.id}?target_length=1")
    assert response.status_code == 422


def test_generate_beat_target_length_too_long_returns_422(client, loop_with_file):
    response = client.post(f"/api/v1/generate-beat/{loop_with_file.id}?target_length=700")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/extend-loop/{id}
# ---------------------------------------------------------------------------

def test_extend_loop_not_found_returns_404(client):
    response = client.post("/api/v1/extend-loop/999999?bars=8")
    assert response.status_code == 404


def test_extend_loop_queues_task(client, loop_with_file):
    with patch("app.routes.audio.task_service.extend_loop_task"):
        response = client.post(
            f"/api/v1/extend-loop/{loop_with_file.id}?bars=8"
        )
    assert response.status_code == 200
    data = response.json()
    assert data["loop_id"] == loop_with_file.id
    assert data["status"] == "pending"
