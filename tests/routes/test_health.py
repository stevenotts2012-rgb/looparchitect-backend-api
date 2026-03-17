"""
Tests for health check endpoints with FFmpeg validation.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    return TestClient(app)


def test_health_live(client):
    """Test basic liveness endpoint."""
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True


def test_health_ready_includes_ffmpeg(client):
    """Test readiness endpoint includes FFmpeg status."""
    response = client.get("/api/v1/health/ready")
    # May return 200 or 503 depending on environment setup
    
    # Extract data from either success or error response
    if response.status_code == 200:
        data = response.json()
    elif response.status_code == 503:
        # When health check fails, payload is in 'detail'
        data = response.json().get("detail", {})
    else:
        pytest.fail(f"Unexpected status code: {response.status_code}")
    
    # Verify structure includes ffmpeg_ok field
    assert "ffmpeg_ok" in data, f"ffmpeg_ok not in response: {data}"
    assert "db_ok" in data
    assert "redis_ok" in data
    assert "s3_ok" in data
    assert "storage_backend" in data
    assert "ok" in data
    
    # Verify ffmpeg_ok is a boolean
    assert isinstance(data["ffmpeg_ok"], bool)


def test_ffmpeg_functional():
    """Test that FFmpeg can actually decode audio."""
    import tempfile
    import shutil
    from pathlib import Path
    from pydub import AudioSegment
    from pydub.generators import Sine
    
    # Check if ffmpeg is available
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        pytest.skip("FFmpeg not available in test environment")
    
    # Generate a simple test audio segment
    try:
        # Create a 1-second sine wave tone
        tone = Sine(440).to_audio_segment(duration=1000)
        
        # Write to temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tone.export(str(tmp_path), format="wav")
        
        # Verify we can read it back
        loaded = AudioSegment.from_file(str(tmp_path))
        assert len(loaded) > 0
        assert loaded.frame_rate > 0
        
        # Clean up
        tmp_path.unlink()
        
    except Exception as e:
        pytest.fail(f"FFmpeg decode test failed: {e}")


def test_health_legacy_endpoint(client):
    """Test backward-compatible health endpoint."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_health_queue_debug_with_redis(client):
    """Queue debug endpoint should report queue depth when Redis is available."""
    mock_conn = MagicMock()
    mock_conn.ping.return_value = True

    mock_queue = MagicMock()
    mock_queue.count = 3
    mock_queue.failed_job_registry = [object()]

    with patch("app.queue.get_redis_conn", return_value=mock_conn), patch(
        "app.queue.get_queue", return_value=mock_queue
    ):
        response = client.get("/api/v1/health/queue")

    assert response.status_code == 200
    data = response.json()
    assert data["redis_ok"] is True
    assert data["queue_depth"] == 3
    assert data["failed_queue_jobs"] == 1
    assert "failed_db_jobs" in data
    assert "queued_db_jobs" in data
    assert "processing_db_jobs" in data


def test_health_queue_debug_without_redis(client):
    """Queue debug endpoint should return diagnostics even if Redis is unavailable."""
    with patch("app.queue.get_redis_conn", side_effect=RuntimeError("redis down")):
        response = client.get("/api/v1/health/queue")

    assert response.status_code == 200
    data = response.json()
    assert data["redis_ok"] is False
    assert data["queue_depth"] is None
    assert data["failed_queue_jobs"] is None
    assert "redis down" in (data["error"] or "")


def test_health_worker_endpoint(client):
    """Test /health/worker endpoint returns worker info."""
    response = client.get("/api/v1/health/worker")
    assert response.status_code == 200
    data = response.json()
    assert "ok" in data
    assert "worker_count" in data
    assert "workers" in data
    # workers should be a list
    assert isinstance(data["workers"], list)
    # If workers exist, check structure
    if data["workers"]:
        w = data["workers"][0]
        assert "name" in w
        assert "state" in w
        assert "queues" in w
        assert "pid" in w
        assert "last_heartbeat" in w
