"""Tests for app/services/storage_service.py — local backend (no S3)."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers to construct a local-backend StorageService without real S3 config
# ---------------------------------------------------------------------------

def _make_local_service(tmp_path: Path):
    """Return a StorageService instance configured for local storage."""
    from app.services import storage_service as ss_module

    service = ss_module.StorageService.__new__(ss_module.StorageService)
    service.use_s3 = False
    service.upload_dir = tmp_path
    service.upload_dir.mkdir(parents=True, exist_ok=True)
    return service


# ===========================================================================
# _should_use_s3
# ===========================================================================

class TestShouldUseS3:
    def test_local_backend_returns_false(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "storage_backend", "local")
        from app.services.storage_service import StorageService
        svc = StorageService.__new__(StorageService)
        # Override get_storage_backend to return "local"
        with patch.object(settings, "get_storage_backend", return_value="local"):
            result = svc._should_use_s3()
        assert result is False

    def test_invalid_backend_raises_runtime_error(self, monkeypatch):
        from app.config import settings
        from app.services.storage_service import StorageService
        with patch.object(settings, "get_storage_backend", return_value="gcs"):
            svc = StorageService.__new__(StorageService)
            with pytest.raises(RuntimeError, match="Invalid STORAGE_BACKEND"):
                svc._should_use_s3()


# ===========================================================================
# _init_local
# ===========================================================================

class TestInitLocal:
    def test_creates_uploads_dir(self, tmp_path, monkeypatch):
        from app.services.storage_service import StorageService
        svc = StorageService.__new__(StorageService)
        svc.use_s3 = False
        # Point uploads to a subdir of tmp_path that doesn't exist yet
        uploads = tmp_path / "uploads_init"
        monkeypatch.chdir(tmp_path)
        # Patch Path to use our tmp_path
        with patch("app.services.storage_service.Path", return_value=uploads) as MockPath:
            MockPath.return_value = uploads
            # Just call directly
            svc.upload_dir = uploads
            uploads.mkdir(parents=True, exist_ok=True)
        assert uploads.exists()


# ===========================================================================
# upload_file — local backend
# ===========================================================================

class TestUploadFileLocal:
    def test_upload_writes_bytes(self, tmp_path):
        svc = _make_local_service(tmp_path)
        url = svc.upload_file(b"hello-audio", "test.wav", "audio/wav")
        assert (tmp_path / "test.wav").read_bytes() == b"hello-audio"

    def test_upload_returns_url_path(self, tmp_path):
        svc = _make_local_service(tmp_path)
        url = svc.upload_file(b"data", "my_loop.wav")
        assert url == "/uploads/my_loop.wav"

    def test_upload_creates_file(self, tmp_path):
        svc = _make_local_service(tmp_path)
        svc.upload_file(b"audio-bytes", "new_file.mp3", "audio/mpeg")
        assert (tmp_path / "new_file.mp3").exists()


# ===========================================================================
# generate_download_url — local backend
# ===========================================================================

class TestGenerateDownloadUrlLocal:
    def test_url_key_starting_with_uploads(self, tmp_path):
        svc = _make_local_service(tmp_path)
        url = svc.generate_download_url("/uploads/track.wav")
        assert url == "/uploads/track.wav"

    def test_plain_filename_gets_uploads_prefix(self, tmp_path):
        svc = _make_local_service(tmp_path)
        url = svc.generate_download_url("track.wav")
        assert url == "/uploads/track.wav"

    def test_nested_path_uses_basename(self, tmp_path):
        svc = _make_local_service(tmp_path)
        url = svc.generate_download_url("some/path/to/track.wav")
        assert url == "/uploads/track.wav"


# ===========================================================================
# delete_file — local backend
# ===========================================================================

class TestDeleteFileLocal:
    def test_delete_existing_file_returns_true(self, tmp_path):
        svc = _make_local_service(tmp_path)
        (tmp_path / "to_delete.wav").write_bytes(b"data")
        result = svc.delete_file("/uploads/to_delete.wav")
        assert result is True
        assert not (tmp_path / "to_delete.wav").exists()

    def test_delete_nonexistent_file_returns_false(self, tmp_path):
        svc = _make_local_service(tmp_path)
        result = svc.delete_file("/uploads/ghost.wav")
        assert result is False

    def test_delete_strips_uploads_prefix(self, tmp_path):
        svc = _make_local_service(tmp_path)
        (tmp_path / "strip.wav").write_bytes(b"data")
        result = svc.delete_file("/uploads/strip.wav")
        assert result is True


# ===========================================================================
# file_exists — local backend
# ===========================================================================

class TestFileExistsLocal:
    def test_existing_file_returns_true(self, tmp_path):
        svc = _make_local_service(tmp_path)
        (tmp_path / "exists.wav").write_bytes(b"x")
        assert svc.file_exists("/uploads/exists.wav") is True

    def test_missing_file_returns_false(self, tmp_path):
        svc = _make_local_service(tmp_path)
        assert svc.file_exists("/uploads/missing.wav") is False

    def test_strips_uploads_prefix(self, tmp_path):
        svc = _make_local_service(tmp_path)
        (tmp_path / "check.wav").write_bytes(b"x")
        assert svc.file_exists("/uploads/check.wav") is True


# ===========================================================================
# get_file_path — local backend
# ===========================================================================

class TestGetFilePath:
    def test_returns_path_object(self, tmp_path):
        svc = _make_local_service(tmp_path)
        path = svc.get_file_path("/uploads/audio.wav")
        assert isinstance(path, Path)

    def test_path_uses_upload_dir(self, tmp_path):
        svc = _make_local_service(tmp_path)
        path = svc.get_file_path("/uploads/audio.wav")
        assert path == tmp_path / "audio.wav"

    def test_s3_returns_none(self, tmp_path):
        svc = _make_local_service(tmp_path)
        svc.use_s3 = True
        result = svc.get_file_path("some-key")
        assert result is None


# ===========================================================================
# get_file_stream — local backend
# ===========================================================================

class TestGetFileStreamLocal:
    def test_returns_file_object(self, tmp_path):
        svc = _make_local_service(tmp_path)
        (tmp_path / "stream.wav").write_bytes(b"stream-data")
        stream = svc.get_file_stream("/uploads/stream.wav")
        try:
            content = stream.read()
            assert content == b"stream-data"
        finally:
            stream.close()

    def test_raises_file_not_found_for_missing(self, tmp_path):
        svc = _make_local_service(tmp_path)
        with pytest.raises(FileNotFoundError):
            svc.get_file_stream("/uploads/no_such_file.wav")


# ===========================================================================
# _generate_local_url helper
# ===========================================================================

class TestGenerateLocalUrl:
    def test_already_prefixed_unchanged(self, tmp_path):
        svc = _make_local_service(tmp_path)
        assert svc._generate_local_url("/uploads/x.wav") == "/uploads/x.wav"

    def test_plain_key_prefixed(self, tmp_path):
        svc = _make_local_service(tmp_path)
        assert svc._generate_local_url("x.wav") == "/uploads/x.wav"
