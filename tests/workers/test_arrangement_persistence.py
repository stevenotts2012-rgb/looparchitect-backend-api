"""Tests for arrangement persistence fix in render_loop_worker.

Covers:
1. Completed legacy render job creates an Arrangement record.
2. GET /api/v1/jobs/{job_id} response includes arrangement_id.
3. Failed arrangement creation does NOT mark job as succeeded.
4. Arrangement-mode path stores arrangement_id on the job.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

from app.services.job_service import update_job_status, get_job_status
from app.models.job import RenderJob
from app.schemas.job import RenderJobStatusResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(job_id: str = "job-test-001", loop_id: int = 85) -> RenderJob:
    return RenderJob(
        id=job_id,
        loop_id=loop_id,
        job_type="render_arrangement",
        params_json=json.dumps({"length_seconds": 60}),
        status="processing",
        progress=50.0,
        created_at=datetime.utcnow(),
        retry_count=0,
    )


def _make_db_with_job(job: RenderJob) -> MagicMock:
    """Return a mock DB session whose query chain returns *job*."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = job
    db.commit.return_value = None
    db.refresh.return_value = None
    return db


# ===========================================================================
# 1. update_job_status persists arrangement_id
# ===========================================================================


class TestUpdateJobStatusPersistsArrangementId:
    """update_job_status must write arrangement_id onto the job row."""

    def test_arrangement_id_written_on_succeeded(self):
        job = _make_job()
        db = _make_db_with_job(job)

        update_job_status(db, "job-test-001", "succeeded", arrangement_id=42)

        assert job.arrangement_id == 42
        db.commit.assert_called()

    def test_arrangement_id_not_overwritten_when_none(self):
        job = _make_job()
        job.arrangement_id = 99  # pre-existing value
        db = _make_db_with_job(job)

        # Passing None should leave the existing value untouched.
        update_job_status(db, "job-test-001", "succeeded", arrangement_id=None)

        assert job.arrangement_id == 99

    def test_arrangement_id_absent_leaves_field_none(self):
        job = _make_job()
        db = _make_db_with_job(job)

        # No arrangement_id argument at all.
        update_job_status(db, "job-test-001", "succeeded")

        # arrangement_id should remain unset (None).
        assert job.arrangement_id is None


# ===========================================================================
# 2. GET /jobs/{job_id} response includes arrangement_id
# ===========================================================================


class TestGetJobStatusReturnsArrangementId:
    """get_job_status must propagate arrangement_id to the response schema."""

    def test_arrangement_id_present_in_response(self):
        job = _make_job()
        job.status = "succeeded"
        job.arrangement_id = 42
        job.output_files_json = None
        job.render_metadata_json = None
        job.error_message = None

        db = _make_db_with_job(job)

        with patch("app.services.storage.storage") as mock_storage:
            mock_storage.create_presigned_get_url.return_value = "https://example.com/file.wav"
            response = get_job_status(db, "job-test-001")

        assert isinstance(response, RenderJobStatusResponse)
        assert response.arrangement_id == 42
        # Status should be normalised from "succeeded" to "completed".
        assert response.status == "completed"

    def test_arrangement_id_none_when_not_set(self):
        job = _make_job()
        job.status = "processing"
        job.arrangement_id = None
        job.output_files_json = None
        job.render_metadata_json = None
        job.error_message = None

        db = _make_db_with_job(job)

        with patch("app.services.storage.storage"):
            response = get_job_status(db, "job-test-001")

        assert response.arrangement_id is None


# ===========================================================================
# 3. Legacy path: arrangement_id stored on job when succeeded
# ===========================================================================


class TestLegacyRenderWorkerArrangementPersistence:
    """In the legacy render path, render_loop_worker must:
    - create an Arrangement record when render succeeds
    - store _arr_record_id on the job via update_job_status
    - mark the job 'failed' if arrangement creation raises
    """

    def _base_mocks(self):
        """Return a minimal set of mocks for the legacy render path."""
        loop = MagicMock()
        loop.id = 85
        loop.bpm = 120.0
        loop.genre = "trap"
        loop.file_key = "loops/85.wav"
        loop.file_url = None

        job = _make_job(loop_id=85)
        job.status = "queued"

        db = MagicMock()
        # First query (RenderJob by id) → job; second (Loop) → loop.
        db.query.return_value.filter.return_value.first.side_effect = [job, job, loop]
        db.commit.return_value = None
        db.refresh.return_value = None

        return loop, job, db

    def test_arrangement_id_passed_to_update_job_status_on_success(self):
        """When render + upload succeed and arrangement is persisted,
        update_job_status must be called with the correct arrangement_id."""
        from app.workers import render_worker

        loop = MagicMock()
        loop.id = 85
        loop.bpm = 120.0
        loop.genre = "trap"
        loop.file_key = "loops/85.wav"
        loop.file_url = None

        render_plan = json.dumps(
            {
                "bpm": 120,
                "key": "C",
                "total_bars": 4,
                "render_profile": {"genre_profile": "trap"},
                "sections": [{"name": "A", "type": "verse", "bar_start": 0, "bars": 4}],
                "events": [],
                "tracks": [],
            }
        )

        # Build a fake arrangement that already has render_plan_json set.
        existing_arrangement = MagicMock()
        existing_arrangement.id = 7
        existing_arrangement.render_plan_json = render_plan
        existing_arrangement.status = "queued"
        existing_arrangement.output_s3_key = None

        job = _make_job(loop_id=85)
        job.status = "queued"
        job.retry_count = 0

        calls_iter = iter([job, job, loop, existing_arrangement, existing_arrangement])

        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = lambda: next(calls_iter)
        db.query.return_value.filter.return_value.order_by.return_value.first.side_effect = [
            existing_arrangement,
            None,
        ]
        db.commit.return_value = None
        db.refresh.return_value = None

        fake_audio = MagicMock()
        fake_render_result = {
            "timeline_json": "{}",
            "postprocess": {},
            "render_observability": {"fallback_triggered_count": 0},
        }
        fake_s3_key = "renders/job-test-001/arrangement.wav"

        with (
            patch.object(render_worker, "_ensure_db_models"),
            patch.object(render_worker, "SessionLocal", return_value=db),
            patch.object(render_worker, "_resolve_app_job_id", return_value="job-test-001"),
            patch.object(render_worker, "_download_loop_audio", return_value="/tmp/loop.wav"),
            patch("pydub.AudioSegment.from_file", return_value=fake_audio),
            patch.object(render_worker, "score_and_reject"),
            patch.object(render_worker, "_run_with_timeout", return_value=fake_render_result),
            patch.object(render_worker, "_upload_render_output", return_value=(fake_s3_key, "audio/wav")),
            patch.object(render_worker, "update_job_status") as mock_update,
            patch.object(render_worker, "_parse_stem_metadata_from_loop", return_value=None),
            patch.object(render_worker.storage, "create_presigned_get_url", return_value="https://cdn/file.wav"),
            patch("rq.get_current_job", side_effect=Exception("no rq")),
        ):
            render_worker.render_loop_worker("job-test-001", 85, {"length_seconds": 60})

        # Find the 'succeeded' call and verify arrangement_id was passed.
        succeeded_calls = [
            c for c in mock_update.call_args_list if c.args[2] == "succeeded"
        ]
        assert succeeded_calls, "update_job_status was never called with 'succeeded'"
        kwargs = succeeded_calls[-1].kwargs
        assert kwargs.get("arrangement_id") is not None, (
            "arrangement_id must be passed to update_job_status on success"
        )

    def test_failed_arrangement_creation_marks_job_failed(self):
        """If arrangement DB commit raises, the job must be marked 'failed'
        (not 'succeeded') because render_loop_worker catches the RuntimeError."""
        from app.workers import render_worker

        loop = MagicMock()
        loop.id = 85
        loop.bpm = 120.0
        loop.genre = "trap"
        loop.file_key = "loops/85.wav"
        loop.file_url = None

        render_plan = json.dumps(
            {
                "bpm": 120,
                "key": "C",
                "total_bars": 4,
                "render_profile": {"genre_profile": "trap"},
                "sections": [{"name": "A", "type": "verse", "bar_start": 0, "bars": 4}],
                "events": [],
                "tracks": [],
            }
        )

        existing_arrangement = MagicMock()
        existing_arrangement.id = 7
        existing_arrangement.render_plan_json = render_plan
        existing_arrangement.status = "queued"
        existing_arrangement.output_s3_key = None
        existing_arrangement.output_url = None
        existing_arrangement.arrangement_json = None
        existing_arrangement.progress = 0.0
        existing_arrangement.progress_message = None
        existing_arrangement.error_message = None

        job = _make_job(loop_id=85)
        job.status = "queued"
        job.retry_count = 0

        calls_iter = iter([job, job, loop, existing_arrangement, existing_arrangement])

        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = lambda: next(calls_iter)
        db.query.return_value.filter.return_value.order_by.return_value.first.side_effect = [
            existing_arrangement,
            None,
        ]

        # Make commit raise on the first call (arrangement persistence).
        commit_count = {"n": 0}
        def _commit_side_effect():
            commit_count["n"] += 1
            if commit_count["n"] == 1:
                raise RuntimeError("DB commit failed")
        db.commit.side_effect = _commit_side_effect
        db.refresh.return_value = None

        fake_audio = MagicMock()
        fake_render_result = {
            "timeline_json": "{}",
            "postprocess": {},
            "render_observability": {"fallback_triggered_count": 0},
        }
        fake_s3_key = "renders/job-test-001/arrangement.wav"

        with (
            patch.object(render_worker, "_ensure_db_models"),
            patch.object(render_worker, "SessionLocal", return_value=db),
            patch.object(render_worker, "_resolve_app_job_id", return_value="job-test-001"),
            patch.object(render_worker, "_download_loop_audio", return_value="/tmp/loop.wav"),
            patch("pydub.AudioSegment.from_file", return_value=fake_audio),
            patch.object(render_worker, "score_and_reject"),
            patch.object(render_worker, "_run_with_timeout", return_value=fake_render_result),
            patch.object(render_worker, "_upload_render_output", return_value=(fake_s3_key, "audio/wav")),
            patch.object(render_worker, "update_job_status") as mock_update,
            patch.object(render_worker, "_parse_stem_metadata_from_loop", return_value=None),
            patch.object(render_worker.storage, "create_presigned_get_url", return_value="https://cdn/file.wav"),
            patch("rq.get_current_job", side_effect=Exception("no rq")),
        ):
            render_worker.render_loop_worker("job-test-001", 85, {"length_seconds": 60})

        # The job must never be marked 'succeeded' when arrangement persistence fails.
        succeeded_calls = [
            c for c in mock_update.call_args_list if c.args[2] == "succeeded"
        ]
        failed_calls = [
            c for c in mock_update.call_args_list if c.args[2] == "failed"
        ]
        assert not succeeded_calls, (
            "Job must NOT be marked 'succeeded' when arrangement persistence fails"
        )
        assert failed_calls, "Job must be marked 'failed' when arrangement persistence fails"


# ===========================================================================
# 4. Arrangement-mode path stores arrangement_id on the job
# ===========================================================================


class TestArrangementModePathStoresArrangementId:
    """In the arrangement-mode path (params has arrangement_id),
    update_job_status must receive arrangement_id when marking succeeded."""

    def test_arrangement_mode_passes_arrangement_id_to_update_job_status(self):
        from app.workers import render_worker

        arrangement_id = 42

        arrangement_row = MagicMock()
        arrangement_row.id = arrangement_id
        arrangement_row.status = "done"
        arrangement_row.output_s3_key = "arrangements/42.wav"
        arrangement_row.render_plan_json = json.dumps({"render_profile": {}})
        arrangement_row.error_message = None
        arrangement_row.stem_arrangement_json = None

        job = _make_job(loop_id=85)
        job.status = "queued"
        job.retry_count = 0

        db = MagicMock()
        # Sequence of DB lookups inside render_loop_worker arrangement path:
        # 1. _resolve_app_job_id → job (RenderJob by id)
        # 2. Arrangement by id (first lookup, before run_arrangement_job)
        # 3. Arrangement by id (after db.expire_all(), post run_arrangement_job)
        db.query.return_value.filter.return_value.first.side_effect = [
            job,          # _resolve_app_job_id
            arrangement_row,  # pre-run check
            arrangement_row,  # post-run status check
        ]
        db.commit.return_value = None
        db.refresh.return_value = None

        params = {"arrangement_id": arrangement_id, "arrangement_preset": None}

        with (
            patch.object(render_worker, "_ensure_db_models"),
            patch.object(render_worker, "SessionLocal", return_value=db),
            patch.object(render_worker, "_resolve_app_job_id", return_value="job-test-001"),
            patch.object(render_worker, "update_job_status") as mock_update,
            patch("app.workers.render_worker.run_arrangement_job", create=True),
            patch("app.services.arrangement_jobs.run_arrangement_job"),
            patch("app.services.arrangement_presets.resolve_preset_name", return_value="default"),
            patch.object(render_worker, "_run_with_timeout"),
            patch.object(render_worker.storage, "create_presigned_get_url", return_value="https://cdn/arr.wav"),
            patch("rq.get_current_job", side_effect=Exception("no rq")),
        ):
            render_worker.render_loop_worker("job-test-001", 85, params)

        succeeded_calls = [
            c for c in mock_update.call_args_list if len(c.args) >= 3 and c.args[2] == "succeeded"
        ]
        assert succeeded_calls, "update_job_status must be called with 'succeeded'"
        kwargs = succeeded_calls[-1].kwargs
        assert kwargs.get("arrangement_id") == arrangement_id, (
            f"Expected arrangement_id={arrangement_id} but got {kwargs.get('arrangement_id')}"
        )
