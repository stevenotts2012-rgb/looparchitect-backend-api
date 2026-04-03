import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydub import AudioSegment
from pydub.generators import Sine

import app.db as db_module
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from main import app


pytestmark = pytest.mark.usefixtures("fresh_sqlite_integration_db")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    db = db_module.SessionLocal()
    yield db
    db.close()


@pytest.fixture
def test_loop_for_export(db):
    """Minimal loop for DAW export endpoint tests that do not need a rendered file."""
    loop = Loop(
        name="DAW Export Minimal Loop",
        file_key="uploads/minimal_loop.wav",
        bpm=120.0,
        musical_key="C",
        genre="electronic",
        duration_seconds=4.0,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


@pytest.fixture
def completed_arrangement(db):
    uploads = Path("uploads")
    uploads.mkdir(exist_ok=True)

    loop = Loop(
        name="DAW Export Loop",
        file_key="uploads/test_loop.wav",
        bpm=120.0,
        musical_key="C",
        genre="electronic",
        duration_seconds=4.0,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)

    arrangement = Arrangement(
        loop_id=loop.id,
        status="done",
        target_seconds=30,
        output_s3_key=f"arrangements/{loop.id}_done.wav",
        producer_arrangement_json=(
            '{"sections":[{"name":"Intro","bar_start":0,"bars":2},'
            '{"name":"Hook","bar_start":2,"bars":2}]}'
        ),
    )
    db.add(arrangement)
    db.commit()
    db.refresh(arrangement)

    rendered = (
        Sine(70).to_audio_segment(duration=1000).apply_gain(-8)
        .overlay(Sine(260).to_audio_segment(duration=1000).apply_gain(-12))
        .overlay(Sine(1200).to_audio_segment(duration=1000).apply_gain(-16))
    )
    output_path = uploads / f"{loop.id}_done.wav"
    rendered.export(str(output_path), format="wav")

    yield arrangement


def test_daw_export_generates_zip_and_download_url(client, db, completed_arrangement):
    arrangement_id = completed_arrangement.id

    response = client.get(f"/api/v1/arrangements/{arrangement_id}/daw-export")
    assert response.status_code == 200
    data = response.json()

    assert data["ready_for_export"] is True
    assert data["download_url"] == f"/api/v1/arrangements/{arrangement_id}/daw-export/download"
    assert data["export_s3_key"] == f"exports/{arrangement_id}.zip"

    zip_local = Path("uploads") / f"{arrangement_id}.zip"
    assert zip_local.exists()
    assert zip_local.stat().st_size > 0

    dl = client.get(data["download_url"])
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("application/zip")

    archive = zipfile.ZipFile(io.BytesIO(dl.content), mode="r")
    names = set(archive.namelist())

    required = {
        "stems/kick.wav",
        "stems/bass.wav",
        "stems/snare.wav",
        "stems/hats.wav",
        "stems/melody.wav",
        "stems/pads.wav",
        "markers.csv",
        "tempo_map.json",
        "README.txt",
    }
    assert required.issubset(names)

    for stem in [
        "stems/kick.wav",
        "stems/bass.wav",
        "stems/snare.wav",
        "stems/hats.wav",
        "stems/melody.wav",
        "stems/pads.wav",
    ]:
        payload = archive.read(stem)
        assert payload
        assert len(payload) > 44

    durations = []
    for stem in [
        "stems/kick.wav",
        "stems/bass.wav",
        "stems/snare.wav",
        "stems/hats.wav",
        "stems/melody.wav",
        "stems/pads.wav",
    ]:
        durations.append(len(AudioSegment.from_wav(io.BytesIO(archive.read(stem)))))

    assert all(d > 0 for d in durations)
    assert len(set(durations)) == 1

    refreshed = db.query(Arrangement).filter(Arrangement.id == arrangement_id).first()
    assert refreshed is not None


def test_daw_export_reuses_cached_zip_on_second_call(client, db, completed_arrangement):
    """Second call to /daw-export must reuse the cached ZIP, not regenerate it.

    Phase 2 regression: the endpoint must be idempotent.  Calling it twice
    should return the same download_url and not raise an error or produce a
    different export_s3_key.
    """
    arrangement_id = completed_arrangement.id

    first = client.get(f"/api/v1/arrangements/{arrangement_id}/daw-export")
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["ready_for_export"] is True

    second = client.get(f"/api/v1/arrangements/{arrangement_id}/daw-export")
    assert second.status_code == 200
    second_data = second.json()

    assert second_data["ready_for_export"] is True
    assert second_data["download_url"] == first_data["download_url"]
    assert second_data["export_s3_key"] == first_data["export_s3_key"]


def test_daw_export_returns_not_ready_for_processing_arrangement(client, db, test_loop_for_export):
    """GET /daw-export on a processing arrangement must return ready_for_export=false.

    Phase 2 contract: the endpoint must not attempt ZIP generation when the
    arrangement is still being processed.
    """
    arrangement = Arrangement(
        loop_id=test_loop_for_export.id,
        status="processing",
        target_seconds=30,
        output_s3_key=None,
    )
    db.add(arrangement)
    db.commit()
    db.refresh(arrangement)

    response = client.get(f"/api/v1/arrangements/{arrangement.id}/daw-export")
    assert response.status_code == 200
    data = response.json()
    assert data["ready_for_export"] is False
    assert data["status"] == "processing"
    assert "message" in data


def test_daw_export_returns_404_when_arrangement_not_found(client):
    """GET /daw-export for a non-existent arrangement_id must return 404.

    Phase 2 contract: missing arrangement ID must not cause a 500.
    """
    response = client.get("/api/v1/arrangements/999999/daw-export")
    assert response.status_code == 404


def test_daw_export_download_returns_404_when_zip_not_generated(client, db, test_loop_for_export):
    """GET /daw-export/download before ZIP is generated must return 404.

    Phase 2 contract: the download endpoint must not silently return an empty
    body when the ZIP has not been generated yet.
    """
    arrangement = Arrangement(
        loop_id=test_loop_for_export.id,
        status="done",
        target_seconds=30,
        output_s3_key=f"arrangements/{test_loop_for_export.id}_no_zip.wav",
    )
    db.add(arrangement)
    db.commit()
    db.refresh(arrangement)

    response = client.get(f"/api/v1/arrangements/{arrangement.id}/daw-export/download")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


def test_daw_export_download_returns_404_for_missing_arrangement(client):
    """GET /daw-export/download for a non-existent arrangement_id must return 404."""
    response = client.get("/api/v1/arrangements/999999/daw-export/download")
    assert response.status_code == 404

