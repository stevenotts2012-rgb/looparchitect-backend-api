"""Tests for the database health endpoint (GET /api/v1/db/health)."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_db_health_ok(client):
    """Healthy database returns status 200 with ok status."""
    response = client.get("/api/v1/db/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_db_health_error_returns_500(client):
    """When the database query raises an exception the endpoint returns 500."""
    from app.db import get_db

    def broken_db():
        mock_session = MagicMock()
        mock_session.execute.side_effect = OperationalError(
            "SELECT 1", {}, Exception("connection refused")
        )
        yield mock_session

    app.dependency_overrides[get_db] = broken_db
    try:
        response = client.get("/api/v1/db/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    data = response.json()
    assert data["status"] == "error"
    assert "detail" in data
