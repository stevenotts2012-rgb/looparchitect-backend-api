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
