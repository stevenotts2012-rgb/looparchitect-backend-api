"""Tests for S3Storage in local (development) mode (app/services/storage.py).

These tests exercise the local-fallback branch of S3Storage so they run
without any AWS credentials or network access.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_local_storage(tmp_path: Path):
    """Return an S3Storage instance configured for local mode."""
    from app.services.storage import S3Storage
    with patch("app.config.settings") as mock_settings:
        mock_settings.get_storage_backend.return_value = "local"
        mock_settings.get_s3_bucket.return_value = ""
        mock_settings.aws_access_key_id = ""
        mock_settings.aws_secret_access_key = ""
        mock_settings.aws_region = ""
        storage = S3Storage.__new__(S3Storage)
        storage.storage_backend = "local"
        storage.bucket = ""
        storage.access_key = ""
        storage.secret_key = ""
        storage.region = ""
        storage.use_s3 = False
        storage.upload_dir = tmp_path
    return storage


# ---------------------------------------------------------------------------
# upload_file – local mode
# ---------------------------------------------------------------------------

def test_upload_to_local_creates_file(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path

    key = "uploads/my_audio.wav"
    storage.upload_file(b"fake audio bytes", "audio/wav", key)

    expected = tmp_path / "my_audio.wav"
    assert expected.exists()
    assert expected.read_bytes() == b"fake audio bytes"


def test_upload_to_local_returns_key(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path
    key = "uploads/return_test.wav"
    returned_key = storage.upload_file(b"bytes", "audio/wav", key)
    assert returned_key == key


def test_upload_nested_key_extracts_filename(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path
    storage.upload_file(b"data", "audio/wav", "arrangements/sub/nested.wav")
    assert (tmp_path / "nested.wav").exists()


# ---------------------------------------------------------------------------
# file_exists – local mode
# ---------------------------------------------------------------------------

def test_file_exists_returns_true_when_file_present(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path

    (tmp_path / "exists.wav").write_bytes(b"data")
    assert storage.file_exists("uploads/exists.wav") is True


def test_file_exists_returns_false_when_missing(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path
    assert storage.file_exists("uploads/missing.wav") is False


# ---------------------------------------------------------------------------
# delete_file – local mode
# ---------------------------------------------------------------------------

def test_delete_file_removes_local_file(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path

    target = tmp_path / "to_delete.wav"
    target.write_bytes(b"audio")
    storage.delete_file("uploads/to_delete.wav")
    assert not target.exists()


def test_delete_file_missing_file_does_not_raise(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path
    # Should not raise even if file doesn't exist
    storage.delete_file("uploads/ghost.wav")


# ---------------------------------------------------------------------------
# create_presigned_get_url – local mode
# ---------------------------------------------------------------------------

def test_local_presigned_url_returns_uploads_path(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path

    url = storage.create_presigned_get_url("uploads/audio_file.wav")
    assert url == "/uploads/audio_file.wav"


def test_local_presigned_url_extracts_filename_from_nested_key(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path

    url = storage.create_presigned_get_url("arrangements/some/path/track.wav")
    assert url == "/uploads/track.wav"


def test_local_presigned_url_ignores_expires_seconds(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path
    # expires_seconds is ignored for local storage; should not raise
    url = storage.create_presigned_get_url("uploads/test.wav", expires_seconds=60)
    assert "/uploads/" in url


def test_local_presigned_url_ignores_download_filename(tmp_path):
    storage = _make_local_storage(tmp_path)
    storage.upload_dir = tmp_path
    url = storage.create_presigned_get_url(
        "uploads/test.wav", download_filename="custom_name.wav"
    )
    # In local mode, Content-Disposition is not appended to the URL
    assert "/uploads/test.wav" == url


# ---------------------------------------------------------------------------
# StorageNotConfiguredError when S3 creds missing
# ---------------------------------------------------------------------------

def test_s3_storage_raises_when_creds_missing():
    """S3Storage should raise StorageNotConfiguredError when backend=s3 but creds absent."""
    from app.services.storage import StorageNotConfiguredError, S3Storage
    with patch("app.services.storage.settings") as mock_settings:
        mock_settings.get_storage_backend.return_value = "s3"
        mock_settings.get_s3_bucket.return_value = ""
        mock_settings.aws_access_key_id = ""
        mock_settings.aws_secret_access_key = ""
        mock_settings.aws_region = ""
        with pytest.raises(StorageNotConfiguredError):
            S3Storage()
