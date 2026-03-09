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
        # Create a minimal valid WAV file with proper header
        with open(out_f, "wb") as handle:
            # WAV header (44 bytes minimum)
            handle.write(b"RIFF")  # Chunk ID
            handle.write(b"\x24\x00\x00\x00")  # Chunk size (36 bytes for minimal wave)
            handle.write(b"WAVE")  # Format
            handle.write(b"fmt ")  # Subchunk1 ID
            handle.write(b"\x10\x00\x00\x00")  # Subchunk1 size (16 bytes)
            handle.write(b"\x01\x00")  # AudioFormat (1 for PCM)
            handle.write(b"\x02\x00")  # NumChannels (2 for stereo)
            handle.write(b"\x44\xac\x00\x00")  # SampleRate (44100 Hz)
            handle.write(b"\x10\xb1\x02\x00")  # ByteRate
            handle.write(b"\x04\x00")  # BlockAlign
            handle.write(b"\x10\x00")  # BitsPerSample (16)
            handle.write(b"data")  # Subchunk2 ID
            handle.write(b"\x00\x00\x00\x00")  # Subchunk2 size (0 bytes of audio data)
        return None

    with patch("app.services.arrangement_jobs.storage.create_presigned_get_url") as mock_url:
        with patch("app.services.arrangement_jobs.storage.upload_file") as mock_upload:
            with patch("app.services.arrangement_jobs.httpx.Client") as mock_client:
                with patch("app.services.arrangement_jobs.generate_loop_variations") as mock_variations:
                    with patch("app.services.arrangement_jobs._build_pre_render_plan") as mock_build_plan:
                        with patch("app.services.arrangement_jobs._validate_render_plan_quality") as mock_validate:
                            with patch("app.services.arrangement_jobs.render_from_plan") as mock_render:
                                with patch("app.services.arrangement_jobs.AudioSegment.export", new=fake_export):
                                    with patch("app.services.arrangement_jobs.storage.use_s3", True):
                                        mock_url.return_value = "https://example.com/loop.wav"
                                        mock_upload.return_value = None

                                        # Create proper WAV bytes for S3 response
                                        wav_bytes = bytearray()
                                        wav_bytes.extend(b"RIFF")  # Chunk ID
                                        wav_bytes.extend(b"\x24\x00\x00\x00")  # Chunk size
                                        wav_bytes.extend(b"WAVE")  # Format
                                        wav_bytes.extend(b"fmt ")  # Subchunk1 ID
                                        wav_bytes.extend(b"\x10\x00\x00\x00")  # Subchunk1 size
                                        wav_bytes.extend(b"\x01\x00")  # AudioFormat
                                        wav_bytes.extend(b"\x02\x00")  # NumChannels
                                        wav_bytes.extend(b"\x44\xac\x00\x00")  # SampleRate
                                        wav_bytes.extend(b"\x10\xb1\x02\x00")  # ByteRate
                                        wav_bytes.extend(b"\x04\x00")  # BlockAlign
                                        wav_bytes.extend(b"\x10\x00")  # BitsPerSample
                                        wav_bytes.extend(b"data")  # Subchunk2 ID
                                        wav_bytes.extend(b"\x00\x00\x00\x00")  # Subchunk2 size

                                        mock_response = MagicMock()
                                        mock_response.content = bytes(wav_bytes)
                                        mock_response.raise_for_status.return_value = None

                                        mock_client.return_value.__enter__.return_value.get.return_value = mock_response
                                        mock_variations.return_value = ({}, {"active": False, "count": 0})
                                        mock_build_plan.return_value = {"sections": [], "sections_count": 0, "events_count": 0}
                                        mock_validate.return_value = None
                                        mock_render.return_value = {"timeline_json": "{\"sections\": []}", "postprocess": {}}

                                        run_arrangement_job(arrangement.id)

    db.expire_all()
    updated = db.query(Arrangement).filter_by(id=arrangement.id).first()
    assert updated.status == "done"
    assert updated.output_s3_key == f"arrangements/{arrangement.id}.wav"
    assert updated.output_url is not None
    assert updated.error_message is None
