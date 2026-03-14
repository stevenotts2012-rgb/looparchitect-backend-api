"""
Integration tests for async render pipeline.
Tests job creation, deduplication, status polling, and worker processing.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from app.services.job_service import (
    create_render_job,
    get_job_status,
    list_loop_jobs,
    _compute_dedupe_hash,
)
from app.models.job import RenderJob
from app.schemas.job import RenderJobRequest


pytestmark = pytest.mark.usefixtures("fresh_sqlite_integration_db")


@pytest.fixture
def mock_db():
    """Mock database session."""
    return MagicMock()


@pytest.fixture
def mock_redis():
    """Mock Redis queue."""
    return MagicMock()


@pytest.fixture
def render_params():
    """Sample render parameters."""
    return {
        "genre": "pop",
        "length_seconds": 30,
        "variations": ["Commercial", "Creative"],
        "intensity": "medium",
    }


class TestJobService:
    """Test job service layer."""

    def test_compute_dedupe_hash_consistent(self, render_params):
        """Test that dedupe hash is consistent for same inputs."""
        hash1 = _compute_dedupe_hash(loop_id=1, params=render_params)
        hash2 = _compute_dedupe_hash(loop_id=1, params=render_params)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex is 64 chars

    def test_compute_dedupe_hash_different_params(self, render_params):
        """Test that different params produce different hashes."""
        params2 = render_params.copy()
        params2["genre"] = "rock"
        
        hash1 = _compute_dedupe_hash(loop_id=1, params=render_params)
        hash2 = _compute_dedupe_hash(loop_id=1, params=params2)
        assert hash1 != hash2

    def test_compute_dedupe_hash_different_loop(self, render_params):
        """Test that different loops produce different hashes."""
        hash1 = _compute_dedupe_hash(loop_id=1, params=render_params)
        hash2 = _compute_dedupe_hash(loop_id=2, params=render_params)
        assert hash1 != hash2

    def test_job_model_status_transitions(self):
        """Test RenderJob model status field transitions."""
        job = RenderJob(
            id="test-id",
            loop_id=1,
            job_type="render",
            status="queued",
            progress=0,
            params_json='{"genre": "pop"}',
            created_at=datetime.utcnow(),
        )
        
        assert job.status == "queued"
        assert job.progress == 0
        assert job.retry_count == 0

    def test_job_model_timestamps(self):
        """Test RenderJob timestamp fields."""
        now = datetime.utcnow()
        job = RenderJob(
            id="test-id",
            loop_id=1,
            job_type="render",
            status="processing",
            progress=50,
            params_json='{}',
            started_at=now,
            created_at=now,
        )
        
        assert job.started_at is not None
        assert job.finished_at is None
        assert job.error_message is None

    def test_job_model_error_state(self):
        """Test RenderJob error handling fields."""
        job = RenderJob(
            id="test-id",
            loop_id=1,
            job_type="render",
            status="failed",
            progress=30,
            params_json='{}',
            error_message="S3 upload timeout",
            retry_count=2,
            created_at=datetime.utcnow(),
        )
        
        assert job.status == "failed"
        assert job.error_message == "S3 upload timeout"
        assert job.retry_count == 2

    @patch("app.services.job_service.get_queue")
    @patch("app.services.job_service._find_existing_job", return_value=None)
    def test_create_render_job_uses_app_job_id_for_worker_and_rq_job(
        self,
        _mock_find_existing,
        mock_get_queue,
        render_params,
    ):
        """Enqueue must pass app job_id to worker and as explicit RQ job id."""
        from app.models.loop import Loop

        mock_db = MagicMock()
        loop = Loop(id=123, file_key="loops/test.wav")

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = loop
        mock_db.query.return_value = mock_query

        mock_queue = MagicMock()
        mock_rq_job = MagicMock()
        mock_rq_job.id = "rq-job-id-123"
        mock_queue.enqueue.return_value = mock_rq_job
        mock_get_queue.return_value = mock_queue

        job, _ = create_render_job(mock_db, loop_id=123, params=render_params)

        enqueue_call = mock_queue.enqueue.call_args
        assert enqueue_call is not None
        enqueue_args, enqueue_kwargs = enqueue_call

        assert enqueue_args[1] == job.id
        assert enqueue_args[2] == 123
        assert enqueue_args[3] == render_params
        assert enqueue_kwargs["job_id"] == job.id

    @patch("app.services.job_service.get_queue")
    @patch("app.services.job_service._find_existing_job", return_value=None)
    def test_create_render_job_marks_failed_when_enqueue_errors(
        self,
        _mock_find_existing,
        mock_get_queue,
        render_params,
    ):
        """If Redis enqueue fails, DB job must not remain queued."""
        from app.models.loop import Loop

        mock_db = MagicMock()
        loop = Loop(id=123, file_key="loops/test.wav")

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = loop
        mock_db.query.return_value = mock_query

        mock_get_queue.side_effect = RuntimeError("redis unavailable")

        with pytest.raises(RuntimeError):
            create_render_job(mock_db, loop_id=123, params=render_params)

        created_job = mock_db.add.call_args[0][0]
        assert created_job.status == "failed"
        assert created_job.progress_message == "Queue unavailable"
        assert "Queue enqueue failed" in (created_job.error_message or "")
        assert mock_db.commit.call_count >= 2


class TestAsyncRenderSchemas:
    """Test Pydantic request/response schemas."""

    def test_render_job_request_validation(self):
        """Test RenderJobRequest schema validation."""
        req = RenderJobRequest(
            genre="pop",
            length_seconds=30,
            variations=["Commercial", "Creative"],
            intensity="medium",
        )
        assert req.genre == "pop"
        assert req.length_seconds == 30
        assert len(req.variations) == 2

    def test_render_job_request_defaults(self):
        """Test RenderJobRequest defaults."""
        req = RenderJobRequest(
            genre="pop",
            length_seconds=30,
        )
        assert req.variations == ["Commercial", "Creative", "Experimental"]
        assert req.intensity == "medium"


class TestQueueInitialization:
    """Test Redis queue initialization."""

    @patch("app.queue.redis.from_url")
    def test_redis_connection_from_env(self, mock_redis_from_url):
        """Test Redis connection uses environment variable."""
        from app.queue import get_redis_conn
        
        mock_conn = MagicMock()
        mock_redis_from_url.return_value = mock_conn
        
        with patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379/0"}):
            conn = get_redis_conn()
            mock_redis_from_url.assert_called_once_with("redis://localhost:6379/0")

    @patch("app.queue.redis.from_url")
    def test_redis_connection_default(self, mock_redis_from_url):
        """Test Redis connection uses default when env var not set."""
        from app.queue import get_redis_conn
        
        mock_conn = MagicMock()
        mock_redis_from_url.return_value = mock_conn
        
        with patch.dict("os.environ", {}, clear=True):
            conn = get_redis_conn()
            # Should use default redis://localhost:6379/0
            assert mock_redis_from_url.called


class TestRouteRegistration:
    """Test that render_jobs routes are properly registered."""

    def test_render_jobs_in_route_config(self):
        """Test that render_jobs is in ROUTE_CONFIG."""
        from app.routes import ROUTE_CONFIG
        
        assert "render_jobs" in ROUTE_CONFIG
        assert ROUTE_CONFIG["render_jobs"]["prefix"] == "/api/v1"
        assert "jobs" in ROUTE_CONFIG["render_jobs"]["tags"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
