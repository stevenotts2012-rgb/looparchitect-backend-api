"""
Tests for Phase B arrangement routes.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.db as db_module
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from main import app


pytestmark = pytest.mark.usefixtures("fresh_sqlite_integration_db")


@pytest.fixture
def client():
    """Create a test client for each test."""
    return TestClient(app)


@pytest.fixture
def db():
    """Get a test database session."""
    db = db_module.SessionLocal()
    yield db
    db.close()


@pytest.fixture
def test_loop(db):
    """Create a test loop with S3 key."""
    loop = Loop(
        name="Test Loop",
        file_key="uploads/test_loop.wav",
        bpm=120.0,
        musical_key="C",
        genre="electronic",
        duration_seconds=4.0,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


class TestArrangementCreation:
    """Test arrangement creation endpoint."""

    def test_create_arrangement_creates_row(self, test_loop, client, db):
        """POST /arrangements should create a queued arrangement row."""
        fake_job = SimpleNamespace(id="job-create-123")
        with patch("app.routes.arrangements.is_redis_available", return_value=True), patch("app.routes.arrangements.create_render_job", return_value=(fake_job, False)) as mock_enqueue:
            response = client.post(
                "/api/v1/arrangements/",
                json={
                    "loop_id": test_loop.id,
                    "target_duration_seconds": 180,
                },
            )

        assert response.status_code == 202
        data = response.json()
        assert data["loop_id"] == test_loop.id
        assert data["status"] == "queued"

        arrangement = db.query(Arrangement).filter_by(id=data["id"]).first()
        assert arrangement is not None
        assert arrangement.target_seconds == 180
        assert arrangement.status == "queued"
        mock_enqueue.assert_called_once()

    def test_generate_arrangement_enqueues_redis_job(self, test_loop, client, db):
        """POST /arrangements/generate should enqueue through create_render_job and return render_job_ids."""
        fake_job = SimpleNamespace(id="job-123")

        with patch("app.routes.arrangements.is_redis_available", return_value=True), patch("app.routes.arrangements.create_render_job", return_value=(fake_job, False)) as mock_enqueue:
            response = client.post(
                "/api/v1/arrangements/generate",
                json={
                    "loop_id": test_loop.id,
                    "target_seconds": 60,
                    "genre": "electronic",
                    "use_ai_parsing": False,
                },
            )

        assert response.status_code == 202, response.text
        payload = response.json()
        assert payload["arrangement_id"] > 0
        assert payload["loop_id"] == test_loop.id
        assert payload["render_job_ids"] == ["job-123"]
        # New fields: job_id and poll_url should point to the primary render job
        assert payload["job_id"] == "job-123"
        assert payload["poll_url"] == "/api/v1/jobs/job-123"
        assert len(payload["candidates"]) == 1
        assert payload["candidates"][0]["arrangement_id"] == payload["arrangement_id"]

        # Ensure enqueue path is used and arrangement_id is passed to worker params
        assert mock_enqueue.called
        call_args, _ = mock_enqueue.call_args
        assert call_args[1] == test_loop.id
        assert call_args[2]["arrangement_id"] == payload["arrangement_id"]

    def test_generate_arrangement_marks_arrangement_failed_when_enqueue_runtime_error(self, test_loop, client, db):
        """POST /arrangements/generate should not leave arrangement stuck in queued when enqueue fails."""
        with patch("app.routes.arrangements.is_redis_available", return_value=True), patch("app.routes.arrangements.create_render_job", side_effect=RuntimeError("redis unavailable")):
            response = client.post(
                "/api/v1/arrangements/generate",
                json={
                    "loop_id": test_loop.id,
                    "target_seconds": 60,
                    "genre": "electronic",
                    "use_ai_parsing": False,
                },
            )

        assert response.status_code == 503

        arrangement = (
            db.query(Arrangement)
            .filter(Arrangement.loop_id == test_loop.id)
            .order_by(Arrangement.id.desc())
            .first()
        )
        assert arrangement is not None
        assert arrangement.status == "failed"
        assert arrangement.progress_message == "Queue unavailable"
        assert arrangement.error_message is not None
        assert "Queue enqueue failed" in arrangement.error_message

    def test_generate_arrangement_rejects_when_redis_unavailable_before_row_creation(self, test_loop, client, db):
        """POST /arrangements/generate should return 503 without creating an arrangement row when Redis is down."""
        with patch("app.routes.arrangements.is_redis_available", return_value=False):
            response = client.post(
                "/api/v1/arrangements/generate",
                json={
                    "loop_id": test_loop.id,
                    "target_seconds": 60,
                    "genre": "electronic",
                    "use_ai_parsing": False,
                },
            )

        assert response.status_code == 503
        assert "Background job queue is unavailable" in response.text

        arrangement_count = db.query(Arrangement).filter(Arrangement.loop_id == test_loop.id).count()
        assert arrangement_count == 0

    def test_generate_preview_candidates_are_unsaved_until_explicit_save(self, test_loop, client, db):
        """POST /arrangements/generate with auto_save=false should create unsaved previews excluded from list endpoint."""
        fake_jobs = [
            SimpleNamespace(id="job-preview-1"),
            SimpleNamespace(id="job-preview-2"),
            SimpleNamespace(id="job-preview-3"),
        ]

        with patch("app.routes.arrangements.is_redis_available", return_value=True), patch(
            "app.routes.arrangements.create_render_job",
            side_effect=[(fake_jobs[0], False), (fake_jobs[1], False), (fake_jobs[2], False)],
        ):
            response = client.post(
                "/api/v1/arrangements/generate",
                json={
                    "loop_id": test_loop.id,
                    "target_seconds": 60,
                    "variation_count": 3,
                    "auto_save": False,
                    "use_ai_parsing": False,
                },
            )

        assert response.status_code == 202, response.text
        payload = response.json()
        assert len(payload["candidates"]) == 3
        assert payload["render_job_ids"] == ["job-preview-1", "job-preview-2", "job-preview-3"]
        # job_id and poll_url must point to the first (primary) job
        assert payload["job_id"] == "job-preview-1"
        assert payload["poll_url"] == "/api/v1/jobs/job-preview-1"

        created_ids = [c["arrangement_id"] for c in payload["candidates"]]
        created_rows = db.query(Arrangement).filter(Arrangement.id.in_(created_ids)).all()
        assert len(created_rows) == 3
        assert all(row.is_saved is False for row in created_rows)
        assert all(row.saved_at is None for row in created_rows)

        list_response = client.get(f"/api/v1/arrangements/?loop_id={test_loop.id}")
        assert list_response.status_code == 200
        assert list_response.json() == []

        include_unsaved = client.get(f"/api/v1/arrangements/?loop_id={test_loop.id}&include_unsaved=true")
        assert include_unsaved.status_code == 200
        include_ids = [item["id"] for item in include_unsaved.json()]
        assert set(include_ids) == set(created_ids)

    def test_save_preview_marks_arrangement_saved_and_visible_in_history(self, test_loop, client, db):
        """POST /arrangements/{id}/save should persist a preview arrangement into list endpoint results."""
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="queued",
            target_seconds=60,
            is_saved=False,
        )
        db.add(arrangement)
        db.commit()
        db.refresh(arrangement)

        before = client.get(f"/api/v1/arrangements/?loop_id={test_loop.id}")
        assert before.status_code == 200
        assert all(item["id"] != arrangement.id for item in before.json())

        save_response = client.post(f"/api/v1/arrangements/{arrangement.id}/save", json={})
        assert save_response.status_code == 200
        assert save_response.json()["id"] == arrangement.id

        db.refresh(arrangement)
        assert arrangement.is_saved is True
        assert arrangement.saved_at is not None

        after = client.get(f"/api/v1/arrangements/?loop_id={test_loop.id}")
        assert after.status_code == 200
        after_ids = [item["id"] for item in after.json()]
        assert arrangement.id in after_ids


class TestArrangementRetrieval:
    """Test arrangement GET endpoints."""

    def test_get_arrangement_returns_record(self, test_loop, db, client):
        """GET /arrangements/{id} should return arrangement record.

        When the arrangement is done and has an output_s3_key, the endpoint must
        regenerate a fresh presigned URL (in local storage mode this is
        /uploads/<filename>) rather than returning the stale URL that was baked
        into output_url at completion time.  Both output_url and output_file_url
        must be populated and non-null so the audio player can load the file.
        """
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="done",
            target_seconds=180,
            output_s3_key="arrangements/1.wav",
            # This is the stale URL that was baked in at job-completion time.
            output_url="https://expired-presigned-url.example.com/stale",
        )
        db.add(arrangement)
        db.commit()
        db.refresh(arrangement)

        response = client.get(f"/api/v1/arrangements/{arrangement.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == arrangement.id
        assert data["status"] == "done"
        assert data["output_s3_key"] == "arrangements/1.wav"
        # The endpoint must return a *fresh* URL derived from output_s3_key, not
        # the stale stored value.  In local mode the storage backend returns a
        # /uploads/<filename> path.
        assert data["output_url"] is not None
        assert data["output_url"] != "https://expired-presigned-url.example.com/stale"
        # output_file_url must mirror output_url so both field names work.
        assert data["output_file_url"] == data["output_url"]

    def test_get_done_arrangement_audio_url_is_not_null(self, test_loop, db, client):
        """Completed arrangement response must include a playable audio URL.

        This is the regression guard for the 0:00/0:00 preview bug: when status
        is DONE, both output_url and output_file_url must be non-null so the
        frontend audio player can load the file.
        """
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="done",
            target_seconds=60,
            output_s3_key="arrangements/42.wav",
            output_url=None,  # Simulate a row where the stored URL is missing/cleared
        )
        db.add(arrangement)
        db.commit()
        db.refresh(arrangement)

        response = client.get(f"/api/v1/arrangements/{arrangement.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"
        # Both audio URL fields must be non-null for a completed arrangement
        assert data["output_url"] is not None, (
            "output_url must not be null when status=done (frontend audio player field)"
        )
        assert data["output_file_url"] is not None, (
            "output_file_url must not be null when status=done (frontend audio player alias)"
        )

    def test_list_arrangements_filters_by_loop_id(self, test_loop, db, client):
        """GET /arrangements?loop_id should filter results."""
        arrangement_a = Arrangement(
            loop_id=test_loop.id,
            status="queued",
            target_seconds=120,
            is_saved=True,
            saved_at=datetime.utcnow(),
        )
        arrangement_b = Arrangement(
            loop_id=test_loop.id + 1,
            status="queued",
            target_seconds=120,
            is_saved=True,
            saved_at=datetime.utcnow(),
        )
        db.add_all([arrangement_a, arrangement_b])
        db.commit()

        response = client.get(f"/api/v1/arrangements/?loop_id={test_loop.id}")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["loop_id"] == test_loop.id

    def test_list_arrangements_returns_fresh_url_for_done_arrangement(self, test_loop, db, client):
        """GET /arrangements list must regenerate a fresh presigned URL for done items.

        Phase 1 + Phase 3 regression: list_arrangements must not return the
        stale URL baked in at job-completion time.  Both output_url and
        output_file_url must be non-null and point to the same fresh URL.
        """
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="done",
            target_seconds=60,
            output_s3_key="arrangements/list_test.wav",
            output_url="https://expired.example.com/stale-list-url",
            is_saved=True,
            saved_at=datetime.utcnow(),
        )
        db.add(arrangement)
        db.commit()
        db.refresh(arrangement)

        response = client.get(f"/api/v1/arrangements/?loop_id={test_loop.id}&include_unsaved=true")
        assert response.status_code == 200
        items = response.json()
        done_items = [i for i in items if i["id"] == arrangement.id]
        assert len(done_items) == 1
        item = done_items[0]

        assert item["output_url"] is not None
        assert item["output_url"] != "https://expired.example.com/stale-list-url"
        assert item["output_file_url"] == item["output_url"]

    def test_get_processing_arrangement_has_null_audio_url(self, test_loop, db, client):
        """GET /arrangements/{id} for a processing arrangement must return null audio URLs.

        Phase 1 schema contract: output_url and output_file_url must be None
        when the arrangement is still being processed — there is no audio to
        play yet and the frontend must not attempt to load it.
        """
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="processing",
            target_seconds=60,
            output_s3_key=None,
            output_url=None,
        )
        db.add(arrangement)
        db.commit()
        db.refresh(arrangement)

        response = client.get(f"/api/v1/arrangements/{arrangement.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"
        assert data["output_url"] is None, "output_url must be null while processing"
        assert data["output_file_url"] is None, "output_file_url must be null while processing"

    def test_get_failed_arrangement_has_null_audio_url_and_error_message(self, test_loop, db, client):
        """GET /arrangements/{id} for a failed arrangement must include error_message and null audio.

        Phase 1 schema contract: failed arrangements expose error_message and
        have null audio URL fields so the frontend can show an actionable error
        instead of a broken player.
        """
        arrangement = Arrangement(
            loop_id=test_loop.id,
            status="failed",
            target_seconds=60,
            output_s3_key=None,
            output_url=None,
            error_message="Render job timed out after 900s",
        )
        db.add(arrangement)
        db.commit()
        db.refresh(arrangement)

        response = client.get(f"/api/v1/arrangements/{arrangement.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["error_message"] is not None
        assert "timed out" in data["error_message"]
        assert data["output_url"] is None, "output_url must be null for failed arrangement"
        assert data["output_file_url"] is None, "output_file_url must be null for failed arrangement"

    def test_arrangement_response_schema_has_required_fields_for_all_statuses(self, test_loop, db, client):
        """Arrangement GET response must include status, progress, progress_message for all states.

        Phase 1 contract validation: the response schema must be consistent
        regardless of whether the arrangement is queued, processing, done, or
        failed.  The frontend relies on these fields to drive state transitions.
        """
        required_fields = {"id", "loop_id", "status", "progress", "progress_message",
                           "error_message", "output_url", "output_file_url", "created_at", "updated_at"}

        for arrangement_status in ("queued", "processing", "done", "failed"):
            arrangement = Arrangement(
                loop_id=test_loop.id,
                status=arrangement_status,
                target_seconds=60,
                output_s3_key="arrangements/schema_test.wav" if arrangement_status == "done" else None,
                output_url=None,
                error_message="Schema test error" if arrangement_status == "failed" else None,
            )
            db.add(arrangement)
            db.commit()
            db.refresh(arrangement)

            response = client.get(f"/api/v1/arrangements/{arrangement.id}")
            assert response.status_code == 200, f"Expected 200 for status={arrangement_status}"
            data = response.json()
            for field in required_fields:
                assert field in data, f"Missing field '{field}' for status={arrangement_status}"
