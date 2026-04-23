"""
Tests for app/routes/arrange.py – the /arrange/{loop_id} endpoints.

Covers previously-untested paths:
- 404 when loop not found (lines 108-109)
- bars parameter path (lines 120-122)
- ValueError from duration_to_bars → 400 (lines 148-150)
- Exception from generate_arrangement → 500 (lines 168-170)
- POST /arrange/{loop_id}/bars/{bars} shorthand (lines 232-233)
- POST /arrange/{loop_id}/duration/{duration_seconds} shorthand (lines 265-266)

Note: Lines 130/136/154/159 (duplicate range checks) are unreachable in practice
because the Pydantic schema already enforces ge/le constraints and raises
RequestValidationError before the route body executes.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
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
def test_loop(db):
    """A loop with BPM=120 so duration_to_bars is predictable."""
    loop = Loop(
        name="Arrange Test Loop",
        file_key="uploads/arrange_test.wav",
        bpm=120.0,
        musical_key="C",
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


@pytest.fixture
def loop_no_bpm(db):
    """A loop with no BPM (falls back to default 120)."""
    loop = Loop(
        name="No BPM Loop",
        file_key="uploads/no_bpm.wav",
        bpm=None,
        tempo=None,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


# ---------------------------------------------------------------------------
# 404 – loop not found
# ---------------------------------------------------------------------------


class TestArrangeLoopNotFound:
    def test_nonexistent_loop_returns_404(self, client):
        response = client.post("/api/v1/arrange/999999", json={})
        assert response.status_code == 404
        assert "999999" in response.json()["detail"]


# ---------------------------------------------------------------------------
# bars parameter path
# ---------------------------------------------------------------------------


class TestArrangeWithBars:
    def test_bars_param_overrides_duration(self, client, test_loop):
        """When bars is explicitly passed, it should be used directly."""
        response = client.post(
            f"/api/v1/arrange/{test_loop.id}",
            json={"bars": 32},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        # total_bars should be >= 32 (arranger may round up)
        assert data["total_bars"] >= 32
        assert data["loop_id"] == test_loop.id


# ---------------------------------------------------------------------------
# duration_seconds validation errors
# ---------------------------------------------------------------------------


class TestArrangeValidationErrors:
    def test_duration_to_bars_value_error_returns_400(self, client, test_loop):
        """If duration_to_bars raises ValueError, endpoint returns 400."""
        with patch(
            "app.routes.arrange.duration_to_bars",
            side_effect=ValueError("BPM must be positive"),
        ):
            response = client.post(
                f"/api/v1/arrange/{test_loop.id}",
                json={"duration_seconds": 60},
            )
        assert response.status_code == 400
        assert "BPM must be positive" in response.json()["detail"]

    def test_generate_arrangement_exception_returns_500(self, client, test_loop):
        """If generate_arrangement raises an unexpected exception, return 500."""
        with patch(
            "app.routes.arrange.generate_arrangement",
            side_effect=RuntimeError("generator exploded"),
        ):
            response = client.post(
                f"/api/v1/arrange/{test_loop.id}",
                json={"duration_seconds": 60},
            )
        assert response.status_code == 500
        assert "generator exploded" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Fallback BPM when loop has no bpm/tempo
# ---------------------------------------------------------------------------


class TestArrangeDefaultBpm:
    def test_loop_without_bpm_uses_default(self, client, loop_no_bpm):
        """Loop with no BPM should default to 120 and still succeed."""
        response = client.post(
            f"/api/v1/arrange/{loop_no_bpm.id}",
            json={"duration_seconds": 60},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["bpm"] == 120.0


# ---------------------------------------------------------------------------
# Shorthand endpoints
# ---------------------------------------------------------------------------


class TestArrangeShorthandEndpoints:
    def test_bars_in_url_shorthand(self, client, test_loop):
        """POST /arrange/{loop_id}/bars/{bars} should return 200."""
        response = client.post(f"/api/v1/arrange/{test_loop.id}/bars/32")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["loop_id"] == test_loop.id
        assert data["total_bars"] >= 32

    def test_duration_in_url_shorthand(self, client, test_loop):
        """POST /arrange/{loop_id}/duration/{duration_seconds} should return 200."""
        response = client.post(f"/api/v1/arrange/{test_loop.id}/duration/60")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["loop_id"] == test_loop.id
        assert data["total_bars"] > 0

    def test_bars_shorthand_with_nonexistent_loop(self, client):
        """Shorthand endpoints should also 404 for missing loops."""
        response = client.post("/api/v1/arrange/999999/bars/32")
        assert response.status_code == 404

    def test_duration_shorthand_with_nonexistent_loop(self, client):
        response = client.post("/api/v1/arrange/999999/duration/60")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Happy-path response structure
# ---------------------------------------------------------------------------


class TestArrangeResponseStructure:
    def test_response_has_expected_fields(self, client, test_loop):
        response = client.post(
            f"/api/v1/arrange/{test_loop.id}",
            json={"duration_seconds": 60},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        for field in (
            "loop_id",
            "bpm",
            "target_duration_seconds",
            "actual_duration_seconds",
            "total_bars",
            "bars_total",
            "sections",
        ):
            assert field in data, f"Missing field '{field}'"

    def test_sections_have_required_fields(self, client, test_loop):
        response = client.post(
            f"/api/v1/arrange/{test_loop.id}",
            json={"duration_seconds": 60},
        )
        assert response.status_code == 200, response.text
        sections = response.json()["sections"]
        assert len(sections) > 0
        for section in sections:
            assert "name" in section
            assert "bars" in section
            assert "start_bar" in section
            assert "end_bar" in section
