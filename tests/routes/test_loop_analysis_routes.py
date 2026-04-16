"""Tests for loop analysis routes (app/routes/loop_analysis.py).

Covers:
  POST /api/v1/loops/analyze-metadata
  POST /api/v1/loops/loops/{id}/analyze-metadata
  GET  /api/v1/loops/loops/{id}/metadata
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
    return TestClient(app)


@pytest.fixture
def db():
    session = db_module.SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sample_loop(db):
    loop = Loop(
        name="Dark Trap Loop",
        bpm=145,
        musical_key="Am",
        genre="dark_trap",
        filename="dark_trap_145bpm.wav",
        bars=4,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


MINIMAL_ANALYZE_PAYLOAD = {
    "bpm": 145,
    "tags": ["dark", "trap"],
    "filename": "dark_trap_loop_145bpm.wav",
    "mood_keywords": ["aggressive"],
    "bars": 4,
    "musical_key": "Am",
}

EXPECTED_RESPONSE_KEYS = {
    "detected_genre",
    "detected_mood",
    "energy_level",
    "recommended_template",
    "confidence",
    "suggested_instruments",
    "analysis_version",
}


# ---------------------------------------------------------------------------
# POST /api/v1/loops/analyze-metadata
# ---------------------------------------------------------------------------

def test_analyze_metadata_happy_path(client):
    response = client.post("/api/v1/loops/analyze-metadata", json=MINIMAL_ANALYZE_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    for key in EXPECTED_RESPONSE_KEYS:
        assert key in data, f"Missing key: {key}"


def test_analyze_metadata_returns_genre(client):
    response = client.post("/api/v1/loops/analyze-metadata", json=MINIMAL_ANALYZE_PAYLOAD)
    data = response.json()
    assert isinstance(data["detected_genre"], str)
    assert len(data["detected_genre"]) > 0


def test_analyze_metadata_energy_in_range(client):
    response = client.post("/api/v1/loops/analyze-metadata", json=MINIMAL_ANALYZE_PAYLOAD)
    energy = response.json()["energy_level"]
    assert 0.0 <= energy <= 1.0


def test_analyze_metadata_confidence_in_range(client):
    response = client.post("/api/v1/loops/analyze-metadata", json=MINIMAL_ANALYZE_PAYLOAD)
    confidence = response.json()["confidence"]
    assert 0.0 <= confidence <= 1.0


def test_analyze_metadata_suggested_instruments_is_list(client):
    response = client.post("/api/v1/loops/analyze-metadata", json=MINIMAL_ANALYZE_PAYLOAD)
    assert isinstance(response.json()["suggested_instruments"], list)


def test_analyze_metadata_with_drill_tags(client):
    payload = {
        "bpm": 140,
        "tags": ["drill", "uk"],
        "filename": "uk_drill_140.wav",
        "mood_keywords": [],
    }
    response = client.post("/api/v1/loops/analyze-metadata", json=payload)
    assert response.status_code == 200


def test_analyze_metadata_minimal_fields(client):
    """Only BPM – other fields optional."""
    response = client.post("/api/v1/loops/analyze-metadata", json={"bpm": 120})
    assert response.status_code == 200


def test_analyze_metadata_with_genre_hint(client):
    payload = {**MINIMAL_ANALYZE_PAYLOAD, "genre_hint": "melodic_trap"}
    response = client.post("/api/v1/loops/analyze-metadata", json=payload)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/loops/loops/{id}/analyze-metadata
# ---------------------------------------------------------------------------

def test_analyze_existing_loop_not_found_returns_404(client):
    response = client.post("/api/v1/loops/loops/999999/analyze-metadata")
    assert response.status_code == 404


def test_analyze_existing_loop_happy_path(client, sample_loop):
    response = client.post(f"/api/v1/loops/loops/{sample_loop.id}/analyze-metadata")
    assert response.status_code == 200
    data = response.json()
    assert "detected_genre" in data


def test_analyze_existing_loop_with_genre_hint(client, sample_loop):
    response = client.post(
        f"/api/v1/loops/loops/{sample_loop.id}/analyze-metadata?genre_hint=dark_trap"
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/loops/loops/{id}/metadata
# ---------------------------------------------------------------------------

def test_get_loop_metadata_not_found_returns_404(client):
    response = client.get("/api/v1/loops/loops/999999/metadata")
    assert response.status_code == 404


def test_get_loop_metadata_happy_path(client, sample_loop):
    response = client.get(f"/api/v1/loops/loops/{sample_loop.id}/metadata")
    assert response.status_code == 200
    data = response.json()
    assert "bpm" in data
    assert "filename" in data


def test_get_loop_metadata_returns_correct_values(client, sample_loop):
    response = client.get(f"/api/v1/loops/loops/{sample_loop.id}/metadata")
    data = response.json()
    assert data["bpm"] == sample_loop.bpm
    assert data["filename"] == sample_loop.filename
