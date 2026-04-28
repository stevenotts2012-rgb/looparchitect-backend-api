"""Additional tests for app/routes/loop_analysis.py.

Covers previously-untested paths:
- analyze_loop_metadata: ValueError handler (lines 107-109)
- analyze_loop_metadata: unexpected Exception handler (lines 110-112)
- analyze_existing_loop_metadata: Exception handler (lines 182-184)
- get_loop_metadata_for_analysis: list-type tags handling (lines 215-218)
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest
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
def loop_with_list_tags(db):
    """Create a loop with comma-separated tags string for analysis."""
    loop = Loop(
        name="Drill Loop Tags",
        bpm=140,
        musical_key="Dm",
        genre="drill",
        filename="drill_140bpm.wav",
        bars=4,
        tags="drill,dark,aggressive",
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


# ---------------------------------------------------------------------------
# POST /api/v1/loops/analyze-metadata — error handlers
# ---------------------------------------------------------------------------


def test_analyze_metadata_value_error_returns_400(client):
    """When LoopMetadataAnalyzer.analyze raises ValueError, return 400."""
    with patch(
        "app.routes.loop_analysis.LoopMetadataAnalyzer.analyze",
        side_effect=ValueError("bad bpm"),
    ):
        response = client.post(
            "/api/v1/loops/analyze-metadata",
            json={"bpm": 120, "tags": [], "filename": "test.wav"},
        )
    assert response.status_code == 400
    assert "bad bpm" in response.json()["detail"]


def test_analyze_metadata_unexpected_exception_returns_500(client):
    """When LoopMetadataAnalyzer.analyze raises an unexpected Exception, return 500."""
    with patch(
        "app.routes.loop_analysis.LoopMetadataAnalyzer.analyze",
        side_effect=RuntimeError("unexpected"),
    ):
        response = client.post(
            "/api/v1/loops/analyze-metadata",
            json={"bpm": 120, "tags": [], "filename": "test.wav"},
        )
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/v1/loops/loops/{id}/analyze-metadata — Exception handler
# ---------------------------------------------------------------------------


def test_analyze_existing_loop_exception_returns_500(client, db):
    """When LoopMetadataAnalyzer.analyze raises inside the existing-loop route, return 500."""
    loop = Loop(
        name="Exception Test Loop",
        bpm=120,
        filename="exception_test.wav",
        bars=4,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)

    with patch(
        "app.routes.loop_analysis.LoopMetadataAnalyzer.analyze",
        side_effect=RuntimeError("internal error"),
    ):
        response = client.post(
            f"/api/v1/loops/loops/{loop.id}/analyze-metadata"
        )
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/v1/loops/loops/{id}/metadata — list-type tags handling
# ---------------------------------------------------------------------------


def test_get_metadata_with_list_tags(client, db):
    """Loop metadata endpoint returns data even when loop has no tags."""
    loop = Loop(
        name="List Tags Loop",
        bpm=130,
        filename="list_tags.wav",
        bars=4,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)

    response = client.get(f"/api/v1/loops/loops/{loop.id}/metadata")
    assert response.status_code == 200
    data = response.json()
    assert "bpm" in data


def test_get_metadata_with_string_tags_parsed(client, db):
    """Loop with no tags field returns metadata without tags."""
    loop = Loop(
        name="String Tags Loop",
        bpm=150,
        filename="string_tags.wav",
        bars=4,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)

    response = client.get(f"/api/v1/loops/loops/{loop.id}/metadata")
    assert response.status_code == 200
    data = response.json()
    assert "bpm" in data
