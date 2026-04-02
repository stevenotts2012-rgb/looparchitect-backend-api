"""Tests for render audio source resolution (file_key vs file_url)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_db
from app.models.loop import Loop


@pytest.fixture
def test_db():
    """Create a test database session."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models.base import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def client(test_db):
    """Create a FastAPI test client with mocked database."""

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_render_accepts_file_key_without_file_url(client, test_db):
    """Case A: file_key present and file_url missing should not return 400 missing-audio."""
    loop = Loop(
        name="File Key Loop",
        file_key="uploads/test-key-only.wav",
        file_url=None,
        tempo=120,
        status="pending",
    )
    test_db.add(loop)
    test_db.commit()
    test_db.refresh(loop)

    with patch(
        "app.routes.render.storage.create_presigned_get_url",
        return_value="https://example.com/audio.wav",
    ):
        response = client.post(f"/api/v1/loops/{loop.id}/render", json={})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["loop_id"] == loop.id
    assert len(payload["variations"]) > 0


def test_render_rejects_when_file_key_and_file_url_missing(client, test_db):
    """Case B: neither file_key nor file_url should return 400 with the same message."""
    loop = Loop(
        name="Missing Audio Loop",
        file_key=None,
        file_url=None,
        tempo=120,
        status="pending",
    )
    test_db.add(loop)
    test_db.commit()
    test_db.refresh(loop)

    response = client.post(f"/api/v1/loops/{loop.id}/render", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "Loop has no associated audio file"
