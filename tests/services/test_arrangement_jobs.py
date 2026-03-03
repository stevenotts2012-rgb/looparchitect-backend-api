"""
Tests for arrangement background job pipeline.
"""

from unittest.mock import patch, MagicMock

import pytest
from pydub import AudioSegment

from app.db import SessionLocal
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.services.arrangement_jobs import run_arrangement_job


@pytest.fixture
def db():
    """Get a test database session."""
    db = SessionLocal()
    yield db
    db.close()


def test_run_arrangement_job_updates_record(db):
    """Background job should set status=done and store S3 fields."""
    loop = Loop(
        name="Test Loop",
        file_key="uploads/test_loop.wav",
        bpm=120.0,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)

    arrangement = Arrangement(
        loop_id=loop.id,
        status="queued",
        target_seconds=180,
    )
    db.add(arrangement)
    db.commit()
    db.refresh(arrangement)

    fake_audio = AudioSegment.silent(duration=1000)

    def fake_export(self, out_f, format="wav"):
        with open(out_f, "wb") as handle:
            handle.write(b"RIFF0000WAVE")
        return None

    with patch("app.services.arrangement_jobs.storage.create_presigned_get_url") as mock_url:
        with patch("app.services.arrangement_jobs.storage.upload_file") as mock_upload:
            with patch("app.services.arrangement_jobs.httpx.Client") as mock_client:
                with patch("app.services.arrangement_jobs.render_phase_b_arrangement") as mock_render:
                    with patch("app.services.arrangement_jobs.AudioSegment.export", new=fake_export):
                        with patch("app.services.arrangement_jobs.storage.use_s3", True):
                            mock_url.return_value = "https://example.com/loop.wav"
                            mock_upload.return_value = None

                            mock_response = MagicMock()
                            mock_response.content = b"fake-wav-bytes"
                            mock_response.raise_for_status.return_value = None

                            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
                            mock_render.return_value = (fake_audio, "{\"sections\": []}")

                            run_arrangement_job(arrangement.id)

    db.expire_all()
    updated = db.query(Arrangement).filter_by(id=arrangement.id).first()
    assert updated.status == "done"
    assert updated.output_s3_key == f"arrangements/{arrangement.id}.wav"
    assert updated.output_url is not None
    assert updated.error_message is None
