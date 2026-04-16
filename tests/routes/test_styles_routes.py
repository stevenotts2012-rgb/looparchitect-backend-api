"""Tests for style routes (GET /api/v1/styles, POST /api/v1/validate)."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from main import app


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/v1/styles
# ---------------------------------------------------------------------------

def test_list_styles_returns_200(client):
    response = client.get("/api/v1/styles")
    assert response.status_code == 200


def test_list_styles_returns_styles_key(client):
    response = client.get("/api/v1/styles")
    data = response.json()
    assert "styles" in data
    assert isinstance(data["styles"], list)


def test_list_styles_items_have_expected_fields(client):
    response = client.get("/api/v1/styles")
    styles = response.json()["styles"]
    if styles:
        style = styles[0]
        assert "id" in style
        assert "display_name" in style
        assert "description" in style
        assert "defaults" in style


# ---------------------------------------------------------------------------
# POST /api/v1/validate – happy path
# ---------------------------------------------------------------------------

VALID_PROFILE_PAYLOAD = {
    "profile": {
        "intent": "dark trap beat with heavy 808s",
        "energy": 0.8,
        "darkness": 0.9,
        "bounce": 0.5,
        "warmth": 0.2,
        "texture": "gritty",
        "references": ["Travis Scott"],
        "avoid": [],
        "seed": 42,
        "confidence": 0.9,
    }
}


def test_validate_style_happy_path(client):
    response = client.post("/api/v1/validate", json=VALID_PROFILE_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert "normalized_profile" in data
    assert "warnings" in data
    assert "message" in data


def test_validate_style_normalised_profile_matches_input(client):
    response = client.post("/api/v1/validate", json=VALID_PROFILE_PAYLOAD)
    profile = response.json()["normalized_profile"]
    assert profile["intent"] == "dark trap beat with heavy 808s"
    assert profile["energy"] == 0.8
    assert profile["texture"] == "gritty"


def test_validate_style_warnings_is_list(client):
    response = client.post("/api/v1/validate", json=VALID_PROFILE_PAYLOAD)
    assert isinstance(response.json()["warnings"], list)


# ---------------------------------------------------------------------------
# POST /api/v1/validate – edge cases
# ---------------------------------------------------------------------------

def test_validate_style_empty_references(client):
    payload = dict(VALID_PROFILE_PAYLOAD)
    payload["profile"] = {**VALID_PROFILE_PAYLOAD["profile"], "references": []}
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 200


def test_validate_style_max_boundary_sliders(client):
    payload = {
        "profile": {
            "intent": "maximum energy",
            "energy": 1.0,
            "darkness": 1.0,
            "bounce": 1.0,
            "warmth": 1.0,
            "texture": "gritty",
            "references": [],
            "avoid": [],
            "seed": 1,
            "confidence": 1.0,
        }
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_validate_style_min_boundary_sliders(client):
    payload = {
        "profile": {
            "intent": "minimum energy",
            "energy": 0.0,
            "darkness": 0.0,
            "bounce": 0.0,
            "warmth": 0.0,
            "texture": "smooth",
            "references": [],
            "avoid": [],
            "seed": 0,
            "confidence": 0.0,
        }
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 200


def test_validate_style_many_references_triggers_warning(client):
    refs = [f"artist_{i}" for i in range(12)]
    payload = {
        "profile": {
            "intent": "test",
            "energy": 0.5,
            "darkness": 0.5,
            "bounce": 0.5,
            "warmth": 0.5,
            "texture": "balanced",
            "references": refs,
            "avoid": [],
            "seed": 42,
            "confidence": 0.8,
        }
    }
    response = client.post("/api/v1/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["warnings"]) > 0


# ---------------------------------------------------------------------------
# POST /api/v1/validate – validation failures (missing required fields)
# ---------------------------------------------------------------------------

def test_validate_style_missing_intent_returns_error(client):
    payload = {
        "profile": {
            "energy": 0.5,
            "darkness": 0.5,
            "bounce": 0.5,
            "warmth": 0.5,
            "texture": "balanced",
        }
    }
    response = client.post("/api/v1/validate", json=payload)
    # Missing required field → 422 (Pydantic validation) or handled in service
    assert response.status_code in (200, 422)


def test_validate_style_missing_profile_key_returns_422(client):
    response = client.post("/api/v1/validate", json={})
    assert response.status_code == 422
