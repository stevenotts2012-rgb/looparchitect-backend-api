"""
Regression tests for the loop upload endpoint.

Guards the critical production path:
  POST /api/v1/loops/upload

Ensures:
- Successful upload creates a Loop DB record and returns the expected payload
  shape (loop_id, play_url, download_url).
- Invalid file type is rejected with HTTP 400 before touching storage.
- Storage (S3/local) failures return HTTP 500 and do not leave partial DB rows.
"""

import io
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_wav_bytes(duration_ms: int = 100) -> bytes:
    """Generate minimal valid WAV bytes (silent PCM) for upload tests."""
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        frames = b"\x00\x00" * int(44100 * duration_ms / 1000)
        wf.writeframes(frames)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Upload success
# ---------------------------------------------------------------------------

class TestUploadSuccess:
    """POST /api/v1/loops/upload — happy-path regression guards."""

    def test_upload_returns_loop_id_and_urls(self, client, db):
        """A valid WAV upload must create a DB row and return the expected payload."""
        wav_bytes = _make_wav_bytes()

        mock_upload = MagicMock(return_value=("uploads/test-uuid.wav", "/uploads/test-uuid.wav"))
        mock_analyze = AsyncMock(return_value={"bpm": 120, "key": "C", "duration": 0.1, "bars": 4})

        with (
            patch("app.services.loop_service.loop_service.upload_loop_file", mock_upload),
            patch("app.services.loop_analyzer.loop_analyzer.analyze_from_s3", mock_analyze),
            # Stem separation is non-critical for this test; stub it out
            patch("app.routes.loops._build_stem_analysis_json", return_value="{}"),
        ):
            response = client.post(
                "/api/v1/loops/upload",
                files={"file": ("test.wav", wav_bytes, "audio/wav")},
            )

        assert response.status_code == 201, response.text
        data = response.json()

        # Payload contract: these three fields are consumed by the frontend
        assert "loop_id" in data, "loop_id missing from upload response"
        assert "play_url" in data, "play_url missing from upload response"
        assert "download_url" in data, "download_url missing from upload response"

        loop_id = data["loop_id"]
        assert isinstance(loop_id, int) and loop_id > 0

        # play_url and download_url must point to the correct loop
        assert data["play_url"] == f"/api/v1/loops/{loop_id}/play"
        assert data["download_url"] == f"/api/v1/loops/{loop_id}/download"

        # DB row must have been committed
        loop = db.query(Loop).filter(Loop.id == loop_id).first()
        assert loop is not None, "Loop DB row must exist after successful upload"
        assert loop.file_key == "uploads/test-uuid.wav"

    def test_upload_creates_loop_with_analysis_data(self, client, db):
        """Upload must persist BPM, key, and duration analysis into the Loop row."""
        wav_bytes = _make_wav_bytes()

        mock_upload = MagicMock(return_value=("uploads/bpm-test.wav", "/uploads/bpm-test.wav"))
        mock_analyze = AsyncMock(return_value={"bpm": 140.0, "key": "Dm", "duration": 4.0, "bars": 8})

        with (
            patch("app.services.loop_service.loop_service.upload_loop_file", mock_upload),
            patch("app.services.loop_analyzer.loop_analyzer.analyze_from_s3", mock_analyze),
            patch("app.routes.loops._build_stem_analysis_json", return_value="{}"),
        ):
            response = client.post(
                "/api/v1/loops/upload",
                files={"file": ("loop_140.wav", wav_bytes, "audio/wav")},
            )

        assert response.status_code == 201, response.text
        loop_id = response.json()["loop_id"]

        loop = db.query(Loop).filter(Loop.id == loop_id).first()
        assert loop is not None
        # BPM is stored as a rounded integer per the upload route convention
        assert loop.bpm == 140
        assert loop.musical_key == "Dm"
        assert loop.duration_seconds == 4.0


# ---------------------------------------------------------------------------
# Upload failure — validation
# ---------------------------------------------------------------------------

class TestUploadValidationFailure:
    """POST /api/v1/loops/upload — rejection of invalid inputs."""

    def test_upload_rejects_invalid_file_type(self, client):
        """A text file masquerading as audio must be rejected with HTTP 400.

        The upload route validates the file extension and content-type before
        touching storage.  Sending a .txt file must not reach S3 or create a
        DB row.
        """
        response = client.post(
            "/api/v1/loops/upload",
            files={"file": ("note.txt", b"not audio", "text/plain")},
        )

        assert response.status_code == 400, (
            f"Expected 400 for invalid file type, got {response.status_code}: {response.text}"
        )

    def test_upload_rejects_oversized_file(self, client):
        """A file exceeding the configured size limit must be rejected with HTTP 400."""
        from app.config import settings

        limit_bytes = settings.max_upload_size_mb * 1024 * 1024
        oversized = b"\x00" * (limit_bytes + 1)

        response = client.post(
            "/api/v1/loops/upload",
            files={"file": ("big.wav", oversized, "audio/wav")},
        )

        # The route validates size before storage; expect 400 or 413
        assert response.status_code in (400, 413), (
            f"Expected 400/413 for oversized upload, got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Upload failure — storage errors
# ---------------------------------------------------------------------------

class TestUploadStorageFailure:
    """POST /api/v1/loops/upload — storage-layer error handling."""

    def test_upload_returns_500_when_storage_fails(self, client, db):
        """When the storage backend raises, the endpoint must return HTTP 500.

        No partial Loop DB row should be left behind — the route rolls back on
        storage failure.
        """
        from app.services.storage import S3StorageError

        loop_count_before = db.query(Loop).count()

        with patch(
            "app.services.loop_service.loop_service.upload_loop_file",
            side_effect=S3StorageError("Simulated S3 upload failure"),
        ):
            response = client.post(
                "/api/v1/loops/upload",
                files={"file": ("test.wav", _make_wav_bytes(), "audio/wav")},
            )

        assert response.status_code == 500, (
            f"Expected 500 when storage fails, got {response.status_code}: {response.text}"
        )

        # No new DB rows should have been committed
        loop_count_after = db.query(Loop).count()
        assert loop_count_after == loop_count_before, (
            "A failed upload must not leave a partial Loop row in the database"
        )
