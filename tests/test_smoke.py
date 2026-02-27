"""Smoke tests for the LoopArchitect API.

These tests exercise the main endpoints end-to-end using an in-process
TestClient so no real server or database is required (SQLite is used).

Run with:
    pytest tests/test_smoke.py -v
"""

import io
import json
import wave

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wav_bytes() -> bytes:
    """Return a tiny but valid mono WAV file as bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        # 0.1 s of silence
        wf.writeframes(b"\x00\x00" * 4410)
    return buf.getvalue()


WAV_BYTES = _make_wav_bytes()


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_status(client):
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "environment" in data


# ---------------------------------------------------------------------------
# Loops CRUD
# ---------------------------------------------------------------------------

def test_create_loop(client):
    response = client.post(
        "/api/v1/loops",
        json={"name": "Smoke Test Loop", "tempo": 120.0, "key": "C", "genre": "Trap"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "Smoke Test Loop"
    assert data["id"] > 0


def test_list_loops(client):
    response = client.get("/api/v1/loops")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_loop_not_found(client):
    response = client.get("/api/v1/loops/999999")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# File upload endpoints
# ---------------------------------------------------------------------------

def test_upload_audio(client):
    response = client.post(
        "/api/v1/loops/upload",
        files={"file": ("test.wav", WAV_BYTES, "audio/wav")},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert "loop_id" in data
    assert "file_url" in data
    assert data["file_url"].startswith("/uploads/")


def test_upload_file_only(client):
    response = client.post(
        "/api/v1/upload",
        files={"file": ("test.wav", WAV_BYTES, "audio/wav")},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert "file_url" in data
    assert data["file_url"].startswith("/uploads/")


def test_upload_invalid_mime(client):
    response = client.post(
        "/api/v1/loops/upload",
        files={"file": ("test.txt", b"not audio", "text/plain")},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v1/loops/with-file  (the primary bug fix)
# ---------------------------------------------------------------------------

def test_create_loop_with_file_success(client):
    loop_meta = json.dumps({"name": "WithFile Loop", "tempo": 140.0, "key": "Am", "genre": "Lofi"})
    response = client.post(
        "/api/v1/loops/with-file",
        data={"loop_in": loop_meta},
        files={"file": ("test.wav", WAV_BYTES, "audio/wav")},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "WithFile Loop"
    assert data["file_url"] is not None
    assert data["file_url"].startswith("/uploads/")


def test_create_loop_with_file_invalid_json(client):
    """Malformed JSON in loop_in should return 422 with a clear message."""
    response = client.post(
        "/api/v1/loops/with-file",
        data={"loop_in": "this is not json"},
        files={"file": ("test.wav", WAV_BYTES, "audio/wav")},
    )
    assert response.status_code == 422, response.text


def test_create_loop_with_file_missing_required_field(client):
    """JSON that is valid but missing required 'name' field should return 422."""
    loop_meta = json.dumps({"tempo": 140.0})
    response = client.post(
        "/api/v1/loops/with-file",
        data={"loop_in": loop_meta},
        files={"file": ("test.wav", WAV_BYTES, "audio/wav")},
    )
    assert response.status_code == 422, response.text


def test_create_loop_with_file_invalid_mime(client):
    loop_meta = json.dumps({"name": "Bad MIME", "tempo": 100.0})
    response = client.post(
        "/api/v1/loops/with-file",
        data={"loop_in": loop_meta},
        files={"file": ("test.txt", b"not audio", "text/plain")},
    )
    assert response.status_code == 400, response.text


# ---------------------------------------------------------------------------
# Arrange + Render pipeline
# ---------------------------------------------------------------------------

def _create_loop_with_file(client) -> int:
    """Helper: create a loop with an uploaded file and return its id."""
    loop_meta = json.dumps({"name": "Pipeline Loop", "tempo": 120.0})
    resp = client.post(
        "/api/v1/loops/with-file",
        data={"loop_in": loop_meta},
        files={"file": ("pipeline.wav", WAV_BYTES, "audio/wav")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_arrange_loop(client):
    loop_id = _create_loop_with_file(client)
    response = client.post(
        f"/api/v1/loops/{loop_id}/arrange",
        json={"genre": "Trap", "length_seconds": 30},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["loop_id"] == loop_id
    assert len(data["sections"]) > 0


def test_arrange_endpoint(client):
    loop_id = _create_loop_with_file(client)
    response = client.post(
        f"/api/v1/arrange/{loop_id}",
        json={"length_seconds": 30},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["loop_id"] == loop_id
    assert data["bars_total"] > 0


def test_delete_loop(client):
    loop_id = _create_loop_with_file(client)
    response = client.delete(f"/api/v1/loops/{loop_id}")
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] is True
