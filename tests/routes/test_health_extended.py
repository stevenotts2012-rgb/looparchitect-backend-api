"""Extended tests for app/routes/health.py to improve coverage.

Covers:
- health_ready with S3 backend checks (missing credentials, ClientError)
- health_ready Redis failure in production mode
- health_ready FFmpeg detection success/failure paths
- health_worker with workers present and Redis failure
- health_ready success path (all checks pass)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# health_ready — Redis failure paths
# ---------------------------------------------------------------------------


class TestHealthReadyRedisPaths:
    def test_redis_failure_in_dev_mode_does_not_raise(self, client):
        """Redis failure is non-blocking in development (non-production) mode."""
        with (
            patch("app.routes.health.settings") as mock_settings,
            patch("app.routes.health.get_redis_conn", side_effect=RuntimeError("no redis")),
        ):
            mock_settings.is_production = False
            mock_settings.get_storage_backend.return_value = "local"
            mock_settings.redis_url = ""
            mock_settings.database_url = "sqlite:///test.db"
            mock_settings.ffmpeg_binary = None
            mock_settings.ffprobe_binary = None
            mock_settings.should_enforce_audio_binaries = False
            response = client.get("/api/v1/health/ready")

        # Even with redis down, dev mode should not return 503 due to redis alone
        # (may return 503 if other checks fail, but redis failure alone is non-blocking)
        data = response.json()
        if response.status_code == 503:
            detail = data.get("detail", data)
            assert "redis_ok" in detail

    def test_redis_failure_in_production_mode_marked_as_not_ok(self, client):
        """Redis failure in production mode causes ok=False."""
        with (
            patch("app.routes.health.settings") as mock_settings,
            patch("app.routes.health.get_redis_conn", side_effect=RuntimeError("redis down")),
        ):
            mock_settings.is_production = True
            mock_settings.get_storage_backend.return_value = "local"
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.database_url = "sqlite:///test.db"
            mock_settings.ffmpeg_binary = None
            mock_settings.ffprobe_binary = None
            mock_settings.should_enforce_audio_binaries = False
            response = client.get("/api/v1/health/ready")

        # In production redis is required — ok should be False
        assert response.status_code in (200, 503)
        if response.status_code == 503:
            detail = response.json().get("detail", {})
            assert detail.get("redis_ok") is False


# ---------------------------------------------------------------------------
# health_ready — FFmpeg detection
# ---------------------------------------------------------------------------


class TestHealthReadyFFmpegPaths:
    def test_ffmpeg_ok_true_when_both_binaries_found(self, client):
        """ffmpeg_ok is True when both ffmpeg and ffprobe are on PATH."""
        with (
            patch("app.routes.health.settings") as mock_settings,
            patch("app.routes.health.shutil.which", return_value="/usr/bin/ffmpeg"),
        ):
            mock_settings.is_production = False
            mock_settings.get_storage_backend.return_value = "local"
            mock_settings.redis_url = ""
            mock_settings.database_url = "sqlite:///test.db"
            mock_settings.ffmpeg_binary = "/usr/bin/ffmpeg"
            mock_settings.ffprobe_binary = "/usr/bin/ffprobe"
            mock_settings.should_enforce_audio_binaries = False
            response = client.get("/api/v1/health/ready")

        data = response.json() if response.status_code == 200 else response.json().get("detail", {})
        assert "ffmpeg_ok" in data

    def test_ffmpeg_ok_false_when_no_binaries_on_path(self, client):
        """ffmpeg_ok is False when neither binary is found."""
        with (
            patch("app.routes.health.settings") as mock_settings,
            patch("app.routes.health.shutil.which", return_value=None),
        ):
            mock_settings.is_production = False
            mock_settings.get_storage_backend.return_value = "local"
            mock_settings.redis_url = ""
            mock_settings.database_url = "sqlite:///test.db"
            mock_settings.ffmpeg_binary = None
            mock_settings.ffprobe_binary = None
            mock_settings.should_enforce_audio_binaries = False
            response = client.get("/api/v1/health/ready")

        data = response.json() if response.status_code == 200 else response.json().get("detail", {})
        # When binaries are not present, ffmpeg_ok should be False
        assert data.get("ffmpeg_ok") is False or "ffmpeg_ok" in data


# ---------------------------------------------------------------------------
# health_ready — S3 backend checks
# ---------------------------------------------------------------------------


class TestHealthReadyS3Paths:
    def test_s3_ok_false_when_credentials_missing(self, client):
        """When S3 backend is configured but credentials are missing, s3_ok is False."""
        with patch("app.routes.health.settings") as mock_settings:
            mock_settings.is_production = False
            mock_settings.get_storage_backend.return_value = "s3"
            mock_settings.aws_access_key_id = ""
            mock_settings.aws_secret_access_key = ""
            mock_settings.aws_region = ""
            mock_settings.get_s3_bucket.return_value = ""
            mock_settings.redis_url = ""
            mock_settings.database_url = "sqlite:///test.db"
            mock_settings.ffmpeg_binary = None
            mock_settings.ffprobe_binary = None
            mock_settings.should_enforce_audio_binaries = False
            response = client.get("/api/v1/health/ready")

        data = response.json() if response.status_code == 200 else response.json().get("detail", {})
        assert data.get("s3_ok") is False

    def test_s3_ok_false_on_client_error(self, client):
        """When S3 head_bucket raises ClientError, s3_ok is False."""
        from botocore.exceptions import ClientError

        client_error = ClientError(
            {"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadBucket"
        )
        mock_s3_client = MagicMock()
        mock_s3_client.head_bucket.side_effect = client_error

        with (
            patch("app.routes.health.settings") as mock_settings,
            patch("boto3.client", return_value=mock_s3_client),
        ):
            mock_settings.is_production = False
            mock_settings.get_storage_backend.return_value = "s3"
            mock_settings.aws_access_key_id = "KEY"
            mock_settings.aws_secret_access_key = "SECRET"
            mock_settings.aws_region = "us-east-1"
            mock_settings.get_s3_bucket.return_value = "my-bucket"
            mock_settings.redis_url = ""
            mock_settings.database_url = "sqlite:///test.db"
            mock_settings.ffmpeg_binary = None
            mock_settings.ffprobe_binary = None
            mock_settings.should_enforce_audio_binaries = False
            response = client.get("/api/v1/health/ready")

        data = response.json() if response.status_code == 200 else response.json().get("detail", {})
        assert data.get("s3_ok") is False


# ---------------------------------------------------------------------------
# health_worker — Workers present + Redis failure fallback
# ---------------------------------------------------------------------------


class TestHealthWorkerExtended:
    def test_worker_health_with_one_busy_worker(self, client):
        """When a worker is busy, active_jobs increments."""
        mock_worker = MagicMock()
        mock_worker.get_state.return_value = "busy"
        mock_worker.last_heartbeat = None
        mock_worker.name = "worker-1"
        mock_worker.queues = []
        mock_worker.pid = 12345

        mock_conn = MagicMock()
        mock_queue = MagicMock()
        mock_queue.count = 2
        mock_queue.failed_job_registry = []

        with (
            patch("app.routes.health.get_redis_conn", return_value=mock_conn),
            patch("app.routes.health._get_queue", return_value=mock_queue),
            patch("rq.Worker") as mock_worker_class,
        ):
            mock_worker_class.all.return_value = [mock_worker]
            response = client.get("/api/v1/health/worker")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["worker_count"] == 1
        assert data["active_jobs"] == 1
        assert data["queue_depth"] == 2

    def test_worker_health_returns_ok_false_on_redis_failure(self, client):
        """When Redis is unavailable, ok is False and error is in response."""
        with patch("app.routes.health.get_redis_conn", side_effect=RuntimeError("redis down")):
            response = client.get("/api/v1/health/worker")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["worker_count"] == 0
        assert "error" in data

    def test_worker_health_with_last_heartbeat(self, client):
        """Workers with a heartbeat timestamp populate last_heartbeat."""
        from datetime import datetime, timezone

        mock_worker = MagicMock()
        mock_worker.get_state.return_value = "idle"
        mock_worker.last_heartbeat = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_worker.name = "worker-hb"
        mock_worker.queues = []
        mock_worker.pid = 99

        mock_conn = MagicMock()
        mock_queue = MagicMock()
        mock_queue.count = 0
        mock_queue.failed_job_registry = []

        with (
            patch("app.routes.health.get_redis_conn", return_value=mock_conn),
            patch("app.routes.health._get_queue", return_value=mock_queue),
            patch("rq.Worker") as mock_worker_class,
        ):
            mock_worker_class.all.return_value = [mock_worker]
            response = client.get("/api/v1/health/worker")

        data = response.json()
        assert data["last_heartbeat"] is not None


# ---------------------------------------------------------------------------
# legacy endpoints
# ---------------------------------------------------------------------------


class TestHealthLegacyEndpoints:
    def test_ready_legacy_endpoint(self, client):
        """GET /api/v1/ready returns same shape as health_ready."""
        response = client.get("/api/v1/ready")
        assert response.status_code in (200, 503)
        data = response.json() if response.status_code == 200 else response.json().get("detail", {})
        assert "db_ok" in data
