"""Tests for S3 branch of app/services/storage_service.py using mocked boto3."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_s3_service():
    """Return a StorageService with a mocked S3 client."""
    from app.services.storage_service import StorageService

    svc = StorageService.__new__(StorageService)
    svc.use_s3 = True
    svc.bucket_name = "test-bucket"
    svc.region = "us-east-1"
    svc.s3_client = MagicMock()
    return svc


def _make_local_service(tmp_path: Path, monkeypatch):
    from app.services.storage_service import StorageService

    monkeypatch.chdir(tmp_path)
    with patch.object(StorageService, "_should_use_s3", return_value=False):
        svc = StorageService()
    svc.upload_dir = tmp_path
    return svc


# ===========================================================================
# _should_use_s3 — S3 path
# ===========================================================================


class TestShouldUseS3WithS3Config:
    def test_local_returns_false_directly(self, tmp_path, monkeypatch):
        """Verify _should_use_s3 returns False when backend is local."""
        from app.config import settings
        from app.services.storage_service import StorageService

        monkeypatch.chdir(tmp_path)
        with patch.object(StorageService, "_should_use_s3", return_value=False):
            svc = StorageService()

        with patch.object(settings, "get_storage_backend", return_value="local"):
            result = svc._should_use_s3()
        assert result is False

    def test_raises_when_s3_selected_but_creds_missing(self, tmp_path, monkeypatch):
        from app.config import settings
        from app.services.storage_service import StorageService

        monkeypatch.chdir(tmp_path)
        with patch.object(StorageService, "_should_use_s3", return_value=False):
            svc = StorageService.__new__(StorageService)
            svc.use_s3 = False
            svc.upload_dir = tmp_path
        with (
            patch.object(settings, "get_storage_backend", return_value="s3"),
            patch.object(settings, "get_s3_bucket", return_value=""),
            patch.object(settings, "aws_access_key_id", "", create=True),
            patch.object(settings, "aws_secret_access_key", "", create=True),
            patch.object(settings, "aws_region", "", create=True),
        ):
            with pytest.raises(RuntimeError):
                svc._should_use_s3()


# ===========================================================================
# upload_file — S3 branch
# ===========================================================================


class TestUploadToS3Service:
    def test_calls_put_object(self):
        svc = _make_s3_service()
        svc.upload_file(b"audio-data", "test.wav", "audio/wav")
        svc.s3_client.put_object.assert_called_once()

    def test_returns_filename_as_key(self):
        svc = _make_s3_service()
        result = svc.upload_file(b"audio-data", "my_loop.wav", "audio/wav")
        assert result == "my_loop.wav"

    def test_raises_on_upload_failure(self):
        svc = _make_s3_service()
        svc.s3_client.put_object.side_effect = RuntimeError("S3 error")
        with pytest.raises(RuntimeError):
            svc.upload_file(b"audio", "fail.wav", "audio/wav")

    def test_upload_uses_provided_content_type(self):
        svc = _make_s3_service()
        svc.upload_file(b"data", "track.mp3", "audio/mpeg")
        call_kwargs = svc.s3_client.put_object.call_args
        kwargs = call_kwargs[1] if call_kwargs[1] else call_kwargs[0][0]
        assert kwargs.get("ContentType") == "audio/mpeg"


# ===========================================================================
# generate_download_url — S3 branch
# ===========================================================================


class TestGenerateS3DownloadUrl:
    def test_returns_presigned_url(self):
        svc = _make_s3_service()
        svc.s3_client.generate_presigned_url.return_value = "https://s3.example.com/signed"
        url = svc.generate_download_url("my_loop.wav")
        assert url == "https://s3.example.com/signed"

    def test_passes_expiration(self):
        svc = _make_s3_service()
        svc.s3_client.generate_presigned_url.return_value = "https://s3.example.com/signed"
        svc.generate_download_url("my_loop.wav", expiration=7200)
        call_kwargs = svc.s3_client.generate_presigned_url.call_args[1]
        assert call_kwargs["ExpiresIn"] == 7200

    def test_raises_on_presign_failure(self):
        svc = _make_s3_service()
        svc.s3_client.generate_presigned_url.side_effect = RuntimeError("S3 error")
        with pytest.raises(RuntimeError):
            svc.generate_download_url("bad_key.wav")


# ===========================================================================
# delete_file — S3 branch
# ===========================================================================


class TestDeleteFromS3Service:
    def test_calls_delete_object(self):
        svc = _make_s3_service()
        result = svc.delete_file("my_loop.wav")
        svc.s3_client.delete_object.assert_called_once()
        assert result is True

    def test_returns_false_on_exception(self):
        svc = _make_s3_service()
        svc.s3_client.delete_object.side_effect = RuntimeError("oops")
        result = svc.delete_file("bad.wav")
        assert result is False


# ===========================================================================
# file_exists — S3 branch
# ===========================================================================


class TestS3FileExistsService:
    def test_returns_true_when_file_exists(self):
        svc = _make_s3_service()
        svc.s3_client.head_object.return_value = {}
        assert svc.file_exists("my_loop.wav") is True

    def test_returns_false_on_any_exception(self):
        svc = _make_s3_service()
        svc.s3_client.head_object.side_effect = RuntimeError("404")
        assert svc.file_exists("missing.wav") is False


# ===========================================================================
# get_file_path — S3 branch
# ===========================================================================


class TestGetFilePathS3:
    def test_returns_none_for_s3(self):
        svc = _make_s3_service()
        result = svc.get_file_path("any-key")
        assert result is None


# ===========================================================================
# get_file_stream — S3 branch
# ===========================================================================


class TestGetFileStreamS3:
    def test_returns_stream_body(self):
        svc = _make_s3_service()
        mock_body = MagicMock()
        svc.s3_client.get_object.return_value = {"Body": mock_body}
        result = svc.get_file_stream("loops/track.wav")
        assert result is mock_body

    def test_raises_on_s3_error(self):
        svc = _make_s3_service()
        svc.s3_client.get_object.side_effect = RuntimeError("NoSuchKey")
        with pytest.raises(RuntimeError):
            svc.get_file_stream("missing/track.wav")

    def test_get_file_stream_local_raises_file_not_found(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        with pytest.raises(FileNotFoundError):
            svc.get_file_stream("/uploads/nonexistent_file.wav")

    def test_get_file_stream_local_success(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        (tmp_path / "track.wav").write_bytes(b"audio-bytes")
        stream = svc.get_file_stream("/uploads/track.wav")
        try:
            assert stream.read() == b"audio-bytes"
        finally:
            stream.close()


# ===========================================================================
# _upload_to_local — exception path
# ===========================================================================


class TestUploadToLocalException:
    def test_upload_to_local_raises_on_write_error(self, tmp_path, monkeypatch):
        from app.services.storage_service import StorageService

        svc = _make_local_service(tmp_path, monkeypatch)
        # Make upload_dir read-only to cause write failure
        svc.upload_dir = Path("/nonexistent/dir_that_does_not_exist")
        with pytest.raises(Exception):
            svc._upload_to_local(b"data", "fail.wav")
