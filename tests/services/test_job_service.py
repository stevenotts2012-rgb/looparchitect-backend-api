"""Tests for job_service (app/services/job_service.py).

Covers:
  _compute_dedupe_hash
  _find_existing_job
  create_render_job (deduplication, validation, enqueue error)
  update_job_status
  get_job_status
  list_loop_jobs
"""

import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.job import RenderJob
from app.models.loop import Loop
from app.services import job_service
from app.services.job_service import (
    _compute_dedupe_hash,
    _find_existing_job,
    update_job_status,
    get_job_status,
    list_loop_jobs,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine_and_session(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("job_svc_db")
    db_path = tmp_dir / "job_svc.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    yield engine, Session
    engine.dispose()


@pytest.fixture
def db(engine_and_session):
    _, Session = engine_and_session
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def test_loop(db):
    loop = Loop(
        name="Job Service Test Loop",
        file_key="uploads/job_svc_test.wav",
        bpm=130,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


def _make_job(db, loop_id, status="queued", dedupe_hash=None, minutes_ago=0):
    """Helper: insert a RenderJob directly."""
    created_at = datetime.utcnow() - timedelta(minutes=minutes_ago)
    job = RenderJob(
        id=str(uuid.uuid4()),
        loop_id=loop_id,
        status=status,
        dedupe_hash=dedupe_hash or "abc123",
        created_at=created_at,
        queued_at=created_at,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# _compute_dedupe_hash
# ---------------------------------------------------------------------------

def test_dedupe_hash_is_deterministic():
    h1 = _compute_dedupe_hash(1, {"genre": "trap", "length": 180})
    h2 = _compute_dedupe_hash(1, {"genre": "trap", "length": 180})
    assert h1 == h2


def test_dedupe_hash_differs_for_different_params():
    h1 = _compute_dedupe_hash(1, {"genre": "trap"})
    h2 = _compute_dedupe_hash(1, {"genre": "drill"})
    assert h1 != h2


def test_dedupe_hash_differs_for_different_loop_ids():
    h1 = _compute_dedupe_hash(1, {"genre": "trap"})
    h2 = _compute_dedupe_hash(2, {"genre": "trap"})
    assert h1 != h2


def test_dedupe_hash_is_sha256_hex_string():
    h = _compute_dedupe_hash(1, {})
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# _find_existing_job
# ---------------------------------------------------------------------------

def test_find_existing_job_returns_none_when_no_match(db, test_loop):
    result = _find_existing_job(db, test_loop.id, "nonexistent_hash", window_minutes=5)
    assert result is None


def test_find_existing_job_finds_recent_job(db, test_loop):
    hash_val = "recent_hash_" + uuid.uuid4().hex[:8]
    job = _make_job(db, test_loop.id, status="queued", dedupe_hash=hash_val, minutes_ago=1)
    result = _find_existing_job(db, test_loop.id, hash_val, window_minutes=5)
    assert result is not None
    assert result.id == job.id


def test_find_existing_job_ignores_old_jobs(db, test_loop):
    hash_val = "old_hash_" + uuid.uuid4().hex[:8]
    _make_job(db, test_loop.id, status="queued", dedupe_hash=hash_val, minutes_ago=10)
    result = _find_existing_job(db, test_loop.id, hash_val, window_minutes=5)
    assert result is None


def test_find_existing_job_ignores_failed_status(db, test_loop):
    hash_val = "failed_hash_" + uuid.uuid4().hex[:8]
    _make_job(db, test_loop.id, status="failed", dedupe_hash=hash_val, minutes_ago=1)
    result = _find_existing_job(db, test_loop.id, hash_val, window_minutes=5)
    assert result is None


# ---------------------------------------------------------------------------
# create_render_job
# ---------------------------------------------------------------------------

def test_create_render_job_raises_if_loop_not_found(db):
    with pytest.raises(ValueError, match="not found"):
        job_service.create_render_job(db, loop_id=999999, params={})


def test_create_render_job_raises_if_no_audio_file(db):
    loop = Loop(name="No Audio Loop")
    db.add(loop)
    db.commit()
    db.refresh(loop)
    with pytest.raises(ValueError, match="no audio"):
        job_service.create_render_job(db, loop_id=loop.id, params={})


def test_create_render_job_returns_deduplicated_job(db, test_loop):
    params = {"genre": "trap", "length_seconds": 60}
    dedupe_hash = _compute_dedupe_hash(test_loop.id, params)
    existing = _make_job(db, test_loop.id, status="queued",
                         dedupe_hash=dedupe_hash, minutes_ago=1)
    job, was_deduped = job_service.create_render_job(db, test_loop.id, params)
    assert was_deduped is True
    assert job.id == existing.id


def test_create_render_job_enqueue_failure_marks_failed(db, test_loop):
    params = {"genre": "trap_enqueue_fail_" + uuid.uuid4().hex[:4]}
    with patch("app.services.job_service.get_queue",
               side_effect=RuntimeError("Redis unavailable")):
        with pytest.raises(RuntimeError, match="Redis unavailable"):
            job_service.create_render_job(db, test_loop.id, params)
    # The job should now be in failed state
    hash_val = _compute_dedupe_hash(test_loop.id, params)
    failed = (
        db.query(RenderJob)
        .filter(RenderJob.loop_id == test_loop.id,
                RenderJob.dedupe_hash == hash_val)
        .first()
    )
    assert failed is not None
    assert failed.status == "failed"


# ---------------------------------------------------------------------------
# update_job_status
# ---------------------------------------------------------------------------

def test_update_job_status_changes_status(db, test_loop):
    job = _make_job(db, test_loop.id)
    updated = update_job_status(db, job.id, status="processing", progress=25.0)
    assert updated.status == "processing"
    assert updated.progress == 25.0


def test_update_job_status_sets_started_at_on_processing(db, test_loop):
    job = _make_job(db, test_loop.id)
    assert job.started_at is None
    updated = update_job_status(db, job.id, status="processing")
    assert updated.started_at is not None


def test_update_job_status_sets_finished_at_on_succeeded(db, test_loop):
    job = _make_job(db, test_loop.id)
    updated = update_job_status(db, job.id, status="succeeded")
    assert updated.finished_at is not None


def test_update_job_status_sets_error_message(db, test_loop):
    job = _make_job(db, test_loop.id)
    updated = update_job_status(db, job.id, status="failed", error_message="oops")
    assert updated.error_message == "oops"


def test_update_job_status_raises_if_not_found(db):
    with pytest.raises(ValueError, match="not found"):
        update_job_status(db, "nonexistent-job-id", status="processing")


def test_update_job_status_stores_render_metadata(db, test_loop):
    job = _make_job(db, test_loop.id)
    metadata = {"render_path_used": "stem", "mastering_applied": True}
    updated = update_job_status(db, job.id, status="succeeded",
                                render_metadata=metadata)
    assert updated.render_metadata_json is not None
    assert json.loads(updated.render_metadata_json)["render_path_used"] == "stem"


# ---------------------------------------------------------------------------
# get_job_status
# ---------------------------------------------------------------------------

def test_get_job_status_returns_response(db, test_loop):
    job = _make_job(db, test_loop.id, status="queued")
    response = get_job_status(db, job.id)
    assert response.job_id == job.id
    assert response.status == "queued"
    assert response.loop_id == test_loop.id


def test_get_job_status_raises_if_not_found(db):
    with pytest.raises(ValueError, match="not found"):
        get_job_status(db, "nonexistent-job-id")


def test_get_job_status_parses_render_metadata(db, test_loop):
    job = _make_job(db, test_loop.id)
    metadata = {"worker_mode": "embedded"}
    update_job_status(db, job.id, status="succeeded", render_metadata=metadata)
    response = get_job_status(db, job.id)
    assert response.render_metadata is not None
    assert response.render_metadata["worker_mode"] == "embedded"


# ---------------------------------------------------------------------------
# list_loop_jobs
# ---------------------------------------------------------------------------

def test_list_loop_jobs_returns_list(db, test_loop):
    _make_job(db, test_loop.id)
    results = list_loop_jobs(db, test_loop.id)
    assert isinstance(results, list)
    assert len(results) >= 1


def test_list_loop_jobs_respects_limit(db, test_loop):
    for _ in range(5):
        _make_job(db, test_loop.id)
    results = list_loop_jobs(db, test_loop.id, limit=2)
    assert len(results) <= 2


def test_list_loop_jobs_empty_for_unknown_loop(db):
    results = list_loop_jobs(db, loop_id=999999)
    assert results == []
