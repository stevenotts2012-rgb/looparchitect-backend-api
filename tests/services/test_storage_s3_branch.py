"""Tests for S3 branch of app/services/storage.py using mocked boto3."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.storage import S3Storage, S3StorageError, StorageNotConfiguredError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_s3_storage() -> S3Storage:
    """Create an S3Storage instance with a fully mocked S3 client."""
    from botocore.exceptions import ClientError  # available via boto3

    storage = S3Storage.__new__(S3Storage)
    storage.storage_backend = "s3"
    storage.bucket = "test-bucket"
    storage.access_key = "AKIA_TEST"
    storage.secret_key = "secret"
    storage.region = "us-east-1"
    storage.use_s3 = True
    storage.s3_client = MagicMock()
    storage.ClientError = ClientError
    return storage


def _client_error(code: str, message: str = "Error"):
    """Build a botocore ClientError with the given error code."""
    from botocore.exceptions import ClientError

    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        operation_name="TestOp",
    )


# ===========================================================================
# S3Storage initialisation
# ===========================================================================


class TestS3StorageInit:
    def test_raises_when_bucket_missing(self):
        with patch("app.services.storage.settings") as m:
            m.get_storage_backend.return_value = "s3"
            m.get_s3_bucket.return_value = ""
            m.aws_access_key_id = "key"
            m.aws_secret_access_key = "secret"
            m.aws_region = "us-east-1"
            with pytest.raises(StorageNotConfiguredError):
                S3Storage()

    def test_raises_when_access_key_missing(self):
        with patch("app.services.storage.settings") as m:
            m.get_storage_backend.return_value = "s3"
            m.get_s3_bucket.return_value = "bucket"
            m.aws_access_key_id = ""
            m.aws_secret_access_key = "secret"
            m.aws_region = "us-east-1"
            with pytest.raises(StorageNotConfiguredError):
                S3Storage()

    def test_local_mode_initialises_upload_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("app.services.storage.settings") as m:
            m.get_storage_backend.return_value = "local"
            m.get_s3_bucket.return_value = ""
            m.aws_access_key_id = ""
            m.aws_secret_access_key = ""
            m.aws_region = ""
            storage = S3Storage()
        assert storage.use_s3 is False
        assert hasattr(storage, "upload_dir")


# ===========================================================================
# _upload_to_s3
# ===========================================================================


class TestUploadToS3:
    def test_calls_put_object(self):
        storage = _make_s3_storage()
        storage._upload_to_s3(b"audio", "audio/wav", "uploads/test.wav")
        storage.s3_client.put_object.assert_called_once()

    def test_returns_key(self):
        storage = _make_s3_storage()
        result = storage._upload_to_s3(b"audio", "audio/wav", "uploads/test.wav")
        assert result == "uploads/test.wav"

    def test_raises_s3_storage_error_on_client_error(self):
        storage = _make_s3_storage()
        storage.s3_client.put_object.side_effect = _client_error("AccessDenied")
        with pytest.raises(S3StorageError):
            storage._upload_to_s3(b"audio", "audio/wav", "uploads/test.wav")

    def test_raises_s3_storage_error_on_unexpected_error(self):
        storage = _make_s3_storage()
        storage.s3_client.put_object.side_effect = RuntimeError("unexpected")
        with pytest.raises(S3StorageError):
            storage._upload_to_s3(b"audio", "audio/wav", "uploads/test.wav")

    def test_upload_file_routes_to_s3(self):
        storage = _make_s3_storage()
        storage.upload_file(b"audio", "audio/wav", "uploads/test.wav")
        storage.s3_client.put_object.assert_called_once()


# ===========================================================================
# _delete_from_s3
# ===========================================================================


class TestDeleteFromS3:
    def test_calls_delete_object(self):
        storage = _make_s3_storage()
        storage._delete_from_s3("uploads/test.wav")
        storage.s3_client.delete_object.assert_called_once()

    def test_ignores_no_such_key_error(self):
        storage = _make_s3_storage()
        storage.s3_client.delete_object.side_effect = _client_error("NoSuchKey")
        # Should not raise
        storage._delete_from_s3("uploads/ghost.wav")

    def test_raises_on_access_denied(self):
        storage = _make_s3_storage()
        storage.s3_client.delete_object.side_effect = _client_error("AccessDenied")
        with pytest.raises(S3StorageError):
            storage._delete_from_s3("uploads/restricted.wav")

    def test_raises_on_unexpected_error(self):
        storage = _make_s3_storage()
        storage.s3_client.delete_object.side_effect = RuntimeError("boom")
        with pytest.raises(S3StorageError):
            storage._delete_from_s3("uploads/test.wav")

    def test_delete_file_routes_to_s3(self):
        storage = _make_s3_storage()
        storage.delete_file("uploads/test.wav")
        storage.s3_client.delete_object.assert_called_once()


# ===========================================================================
# _s3_file_exists
# ===========================================================================


class TestS3FileExists:
    def test_returns_true_when_head_object_succeeds(self):
        storage = _make_s3_storage()
        storage.s3_client.head_object.return_value = {}
        assert storage._s3_file_exists("uploads/exists.wav") is True

    def test_returns_false_on_404(self):
        storage = _make_s3_storage()
        storage.s3_client.head_object.side_effect = _client_error("404")
        assert storage._s3_file_exists("uploads/missing.wav") is False

    def test_returns_false_on_no_such_key(self):
        storage = _make_s3_storage()
        storage.s3_client.head_object.side_effect = _client_error("NoSuchKey")
        assert storage._s3_file_exists("uploads/missing.wav") is False

    def test_re_raises_other_client_errors(self):
        storage = _make_s3_storage()
        storage.s3_client.head_object.side_effect = _client_error("AccessDenied")
        with pytest.raises(Exception):
            storage._s3_file_exists("uploads/restricted.wav")

    def test_file_exists_routes_to_s3(self):
        storage = _make_s3_storage()
        storage.s3_client.head_object.return_value = {}
        result = storage.file_exists("uploads/test.wav")
        assert result is True


# ===========================================================================
# _generate_s3_presigned_url
# ===========================================================================


class TestGenerateS3PresignedUrl:
    def test_returns_presigned_url(self):
        storage = _make_s3_storage()
        storage.s3_client.generate_presigned_url.return_value = "https://s3.example.com/signed"
        url = storage._generate_s3_presigned_url("uploads/test.wav", 3600, None)
        assert url == "https://s3.example.com/signed"

    def test_passes_content_disposition_when_filename_given(self):
        storage = _make_s3_storage()
        storage.s3_client.generate_presigned_url.return_value = "https://s3.example.com/signed"
        storage._generate_s3_presigned_url("uploads/test.wav", 3600, "my_track.wav")
        call_kwargs = storage.s3_client.generate_presigned_url.call_args
        params = call_kwargs[1]["Params"] if call_kwargs[1] else call_kwargs[0][1]["Params"]
        assert "ResponseContentDisposition" in params
        assert "my_track.wav" in params["ResponseContentDisposition"]

    def test_raises_on_client_error(self):
        storage = _make_s3_storage()
        storage.s3_client.generate_presigned_url.side_effect = _client_error("InvalidRequest")
        with pytest.raises(S3StorageError):
            storage._generate_s3_presigned_url("uploads/test.wav", 3600, None)

    def test_raises_on_unexpected_error(self):
        storage = _make_s3_storage()
        storage.s3_client.generate_presigned_url.side_effect = RuntimeError("boom")
        with pytest.raises(S3StorageError):
            storage._generate_s3_presigned_url("uploads/test.wav", 3600, None)

    def test_create_presigned_get_url_routes_to_s3(self):
        storage = _make_s3_storage()
        storage.s3_client.generate_presigned_url.return_value = "https://s3.example.com/signed"
        url = storage.create_presigned_get_url("uploads/test.wav")
        assert "https://" in url
