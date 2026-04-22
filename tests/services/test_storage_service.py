"""Tests for app/services/storage_service.py — local backend (no S3)."""

import pytest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Factory: create a StorageService instance through normal __init__,
# with _should_use_s3 patched to return False so no S3 credentials are needed.
# Using monkeypatch.chdir() means Path("uploads") resolves inside tmp_path.
# ---------------------------------------------------------------------------

def _make_local_service(tmp_path: Path, monkeypatch):
    """Return a real StorageService instance using local storage in tmp_path."""
    from app.services.storage_service import StorageService

    monkeypatch.chdir(tmp_path)
    with patch.object(StorageService, "_should_use_s3", return_value=False):
        svc = StorageService()

    # Redirect upload_dir to tmp_path itself so test files are directly accessible
    svc.upload_dir = tmp_path
    return svc


# ===========================================================================
# _should_use_s3
# ===========================================================================

class TestShouldUseS3:
    def test_local_backend_returns_false(self, tmp_path, monkeypatch):
        from app.config import settings
        from app.services.storage_service import StorageService

        monkeypatch.chdir(tmp_path)
        with patch.object(StorageService, "_should_use_s3", return_value=False):
            svc = StorageService()
        with patch.object(settings, "get_storage_backend", return_value="local"):
            result = svc._should_use_s3()
        assert result is False

    def test_invalid_backend_raises_runtime_error(self, tmp_path, monkeypatch):
        from app.config import settings
        from app.services.storage_service import StorageService

        monkeypatch.chdir(tmp_path)
        with patch.object(StorageService, "_should_use_s3", return_value=False):
            svc = StorageService()
        with patch.object(settings, "get_storage_backend", return_value="gcs"):
            with pytest.raises(RuntimeError, match="Invalid STORAGE_BACKEND"):
                svc._should_use_s3()


# ===========================================================================
# _init_local — verifies the constructor creates an uploads directory
# ===========================================================================

class TestInitLocal:
    def test_creates_uploads_dir(self, tmp_path, monkeypatch):
        from app.services.storage_service import StorageService

        monkeypatch.chdir(tmp_path)
        with patch.object(StorageService, "_should_use_s3", return_value=False):
            svc = StorageService()
        assert svc.upload_dir.exists()


# ===========================================================================
# upload_file — local backend
# ===========================================================================

class TestUploadFileLocal:
    def test_upload_writes_bytes(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        svc.upload_file(b"hello-audio", "test.wav", "audio/wav")
        assert (tmp_path / "test.wav").read_bytes() == b"hello-audio"

    def test_upload_returns_url_path(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        url = svc.upload_file(b"data", "my_loop.wav")
        assert url == "/uploads/my_loop.wav"

    def test_upload_creates_file(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        svc.upload_file(b"audio-bytes", "new_file.mp3", "audio/mpeg")
        assert (tmp_path / "new_file.mp3").exists()


# ===========================================================================
# generate_download_url — local backend
# ===========================================================================

class TestGenerateDownloadUrlLocal:
    def test_url_key_starting_with_uploads(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        url = svc.generate_download_url("/uploads/track.wav")
        assert url == "/uploads/track.wav"

    def test_plain_filename_gets_uploads_prefix(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        url = svc.generate_download_url("track.wav")
        assert url == "/uploads/track.wav"

    def test_nested_path_uses_basename(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        url = svc.generate_download_url("some/path/to/track.wav")
        assert url == "/uploads/track.wav"


# ===========================================================================
# delete_file — local backend
# ===========================================================================

class TestDeleteFileLocal:
    def test_delete_existing_file_returns_true(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        (tmp_path / "to_delete.wav").write_bytes(b"data")
        result = svc.delete_file("/uploads/to_delete.wav")
        assert result is True
        assert not (tmp_path / "to_delete.wav").exists()

    def test_delete_nonexistent_file_returns_false(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        result = svc.delete_file("/uploads/ghost.wav")
        assert result is False

    def test_delete_strips_uploads_prefix(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        (tmp_path / "strip.wav").write_bytes(b"data")
        result = svc.delete_file("/uploads/strip.wav")
        assert result is True


# ===========================================================================
# file_exists — local backend
# ===========================================================================

class TestFileExistsLocal:
    def test_existing_file_returns_true(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        (tmp_path / "exists.wav").write_bytes(b"x")
        assert svc.file_exists("/uploads/exists.wav") is True

    def test_missing_file_returns_false(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        assert svc.file_exists("/uploads/missing.wav") is False

    def test_strips_uploads_prefix(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        (tmp_path / "check.wav").write_bytes(b"x")
        assert svc.file_exists("/uploads/check.wav") is True


# ===========================================================================
# get_file_path — local backend
# ===========================================================================

class TestGetFilePath:
    def test_returns_path_object(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        path = svc.get_file_path("/uploads/audio.wav")
        assert isinstance(path, Path)

    def test_path_uses_upload_dir(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        path = svc.get_file_path("/uploads/audio.wav")
        assert path == tmp_path / "audio.wav"

    def test_s3_returns_none(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        svc.use_s3 = True
        result = svc.get_file_path("some-key")
        assert result is None


# ===========================================================================
# get_file_stream — local backend
# ===========================================================================

class TestGetFileStreamLocal:
    def test_returns_file_object(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        (tmp_path / "stream.wav").write_bytes(b"stream-data")
        stream = svc.get_file_stream("/uploads/stream.wav")
        try:
            content = stream.read()
            assert content == b"stream-data"
        finally:
            stream.close()

    def test_raises_file_not_found_for_missing(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        with pytest.raises(FileNotFoundError):
            svc.get_file_stream("/uploads/no_such_file.wav")


# ===========================================================================
# _generate_local_url helper
# ===========================================================================

class TestGenerateLocalUrl:
    def test_already_prefixed_unchanged(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        assert svc._generate_local_url("/uploads/x.wav") == "/uploads/x.wav"

    def test_plain_key_prefixed(self, tmp_path, monkeypatch):
        svc = _make_local_service(tmp_path, monkeypatch)
        assert svc._generate_local_url("x.wav") == "/uploads/x.wav"
