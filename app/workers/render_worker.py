"""Async render worker: pulls jobs from Redis queue and processes them.

Worker topology (production):
- A dedicated ``python -m app.workers.main`` process connects to Redis and
  runs ``rq.SimpleWorker`` on the ``render`` queue.
- RQ dequeues a job and calls ``render_loop_worker(job_id, loop_id, params)``.
- The worker resolves the app-level job ID (handles RQ vs app ID mismatch),
  marks the arrangement row as ``processing``, then calls
  ``run_arrangement_job`` via a ThreadPoolExecutor timeout wrapper so that
  stuck renders cannot block new work indefinitely.
- On completion the arrangement row transitions to ``done`` and the job to
  ``succeeded``.  On any exception both are marked ``failed`` and the error
  message is persisted for the polling endpoint to surface.
- ``output_s3_key`` written during ``run_arrangement_job`` is the stable
  permanent object key.  The presigned ``output_url`` is regenerated on every
  GET — never relied upon as a durable store.
"""

import logging
import os
import tempfile
import traceback
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from pathlib import Path
from typing import Dict

from tenacity import retry, stop_after_attempt, wait_exponential
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, engine
from app.models.job import RenderJob
from app.models.loop import Loop
from app.services.job_service import update_job_status
from app.services.render_executor import render_from_plan
from app.services.storage import storage
from app.schemas.job import OutputFile
from app.services.arrangement_jobs import _parse_stem_metadata_from_loop
from app.services.arrangement_scorer import score_and_reject
from app.services.audit_logging import log_feature_event
from app.services.render_observability import (
    assemble_render_metadata,
    determine_job_terminal_state,
    extract_observability_from_arrangement,
    get_worker_mode,
    resolve_feature_flags_snapshot,
)

logger = logging.getLogger(__name__)

# Cross-platform job timeout (seconds). Uses ThreadPoolExecutor instead of
# signal.SIGALRM (unavailable on Windows) so this works on all platforms.
try:
    _JOB_TIMEOUT_SECONDS = int(settings.render_job_timeout_seconds or 900)
except (TypeError, ValueError):
    logger.warning(
        "Invalid RENDER_JOB_TIMEOUT_SECONDS value %r; defaulting to 900s",
        settings.render_job_timeout_seconds,
    )
    _JOB_TIMEOUT_SECONDS = 900

# Job module imports
MODELS_TO_REGISTER = [
    "app.models.loop",
    "app.models.arrangement",
    "app.models.job",
]


def _should_use_dev_fallback() -> bool:
    """Dev fallback is opt-in only and never on in production."""
    return bool(settings.dev_fallback_loop_only and not settings.is_production)


def _select_render_mode(has_render_plan: bool) -> str:
    """Select worker render mode using render_plan as source of truth."""
    if has_render_plan:
        return "render_plan"
    if _should_use_dev_fallback():
        return "dev_fallback"
    raise ValueError(
        "render_plan_json is required for worker rendering. "
        "Legacy fallback is disabled by default. "
        "Set DEV_FALLBACK_LOOP_ONLY=true in non-production only for temporary fallback."
    )


def _build_dev_fallback_render_plan(loop: Loop, params: Dict) -> dict:
    """Build a minimal render_plan_json when dev fallback is explicitly enabled."""
    bpm = float(loop.bpm or 120.0)
    length_seconds = int(params.get("length_seconds") or 60)
    bar_duration_seconds = (60.0 / bpm) * 4.0
    bars = max(1, int(round(length_seconds / bar_duration_seconds)))
    return {
        "bpm": bpm,
        "key": "C",
        "total_bars": bars,
        "render_profile": {
            "genre_profile": str(params.get("genre") or loop.genre or "generic"),
            "fallback_used": True,
        },
        "sections": [
            {
                "name": "Fallback Loop",
                "type": "verse",
                "bar_start": 0,
                "bars": bars,
                "energy": 0.55,
                "instruments": ["kick", "snare", "bass"],
            }
        ],
        "events": [
            {
                "type": "variation",
                "bar": idx,
                "description": "dev fallback variation",
            }
            for idx in range(0, bars, 4)
        ],
        "tracks": [],
    }


def _ensure_db_models():
    """Ensure all models are registered with Base.metadata."""
    from app.models.base import Base
    
    for module_name in MODELS_TO_REGISTER:
        try:
            __import__(module_name)
        except Exception as e:
            logger.warning(f"Failed to import {module_name}: {e}")
    
    Base.metadata.create_all(bind=engine)


def _run_with_timeout(fn, *args, timeout_seconds: int = _JOB_TIMEOUT_SECONDS, **kwargs):
    """
    Run *fn* in a ThreadPoolExecutor with a cross-platform wall-clock timeout.

    Uses concurrent.futures instead of signal.SIGALRM so it works on Windows.
    Raises concurrent.futures.TimeoutError if *fn* exceeds *timeout_seconds*.

    Note: Python threads cannot be forcibly cancelled. If the timeout fires the
    caller receives the TimeoutError promptly and can mark the job failed, but
    the background thread may continue running until the current I/O or CPU
    operation completes. This is acceptable because SimpleWorker processes one
    job at a time, so the stale thread will not block new jobs.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, *args, **kwargs)
        return future.result(timeout=timeout_seconds)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _download_loop_audio(loop: Loop, temp_dir: Path) -> Path:
    """Download loop audio from S3 to local temp file."""
    if not (loop.file_key or loop.file_url):
        raise ValueError(f"Loop {loop.id} has no audio file")
    
    import boto3
    
    audio_key = loop.file_key or loop.file_url
    temp_file = temp_dir / f"input_{loop.id}.wav"
    
    if loop.file_key:
        # Download from S3
        try:
            region = settings.aws_region
            bucket = settings.aws_s3_bucket
            if not region or not bucket:
                raise ValueError("Missing AWS_REGION or AWS_S3_BUCKET for S3 download")
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=region,
            )
            s3_client.download_file(bucket, audio_key, str(temp_file))
            logger.info(f"Downloaded S3:{bucket}/{audio_key} to {temp_file}")
        except Exception as e:
            logger.error(f"S3 download failed: {e}")
            raise
    else:
        # Local fallback: read from uploads
        upload_path = Path("uploads") / audio_key.split("/")[-1]
        if upload_path.exists():
            import shutil
            shutil.copy(upload_path, temp_file)
            logger.info(f"Copied local file {upload_path} to {temp_file}")
        else:
            raise FileNotFoundError(f"Audio file not found: {upload_path}")
    
    return temp_file


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _upload_render_output(job_id: str, filename: str, file_path: Path) -> tuple[str, str]:
    """Upload render output to S3, return (s3_key, content_type)."""
    s3_key = f"renders/{job_id}/{filename}"
    content_type = "audio/wav"
    
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    
    storage.upload_file(file_bytes, content_type, s3_key)
    logger.info(f"Uploaded render to S3: {s3_key}")
    
    return s3_key, content_type


def _resolve_app_job_id(db: Session, incoming_job_id: str) -> str:
    """Resolve the app-level job id for worker status updates."""
    direct_match = db.query(RenderJob).filter(RenderJob.id == incoming_job_id).first()
    if direct_match:
        return incoming_job_id

    rq_job_id = None
    try:
        from rq import get_current_job

        current_rq_job = get_current_job()
        rq_job_id = current_rq_job.id if current_rq_job else None
    except Exception:
        rq_job_id = None

    if rq_job_id and rq_job_id != incoming_job_id:
        rq_match = db.query(RenderJob).filter(RenderJob.id == rq_job_id).first()
        if rq_match:
            logger.warning(
                "Worker job id mismatch resolved: incoming_job_id=%s rq_job_id=%s using_app_job_id=%s",
                incoming_job_id,
                rq_job_id,
                rq_job_id,
            )
            return rq_job_id

    logger.error(
        "Worker could not resolve app job id: incoming_job_id=%s rq_job_id=%s",
        incoming_job_id,
        rq_job_id,
    )
    return incoming_job_id


def render_loop_worker(job_id: str, loop_id: int, params: Dict) -> None:
    """
    Worker function: process a single render job.
    
    Called by RQ when job is dequeued.
    """
    _ensure_db_models()
    db = SessionLocal()
    app_job_id = job_id
    arrangement_id = None
    # Phase 3: track where failure occurred for job_terminal_state resolution.
    failure_stage: str | None = None
    worker_mode = get_worker_mode()
    feature_flags = resolve_feature_flags_snapshot()
    
    try:
        arrangement_id = params.get("arrangement_id") if isinstance(params, dict) else None
        app_job_id = _resolve_app_job_id(db, job_id)
        rq_job_id = None
        try:
            from rq import get_current_job

            current_rq_job = get_current_job()
            rq_job_id = current_rq_job.id if current_rq_job else None
        except Exception:
            rq_job_id = None

        logger.info(
            "Worker job received: incoming_job_id=%s app_job_id=%s rq_job_id=%s arrangement_id=%s loop_id=%s",
            job_id,
            app_job_id,
            rq_job_id,
            arrangement_id,
            loop_id,
        )
        logger.info(
            "JOB_START app_job_id=%s arrangement_id=%s loop_id=%s",
            app_job_id,
            arrangement_id,
            loop_id,
        )
        logger.info("RENDER_WORKER_STARTED job_id=%s loop_id=%s", app_job_id, loop_id)
        # Structured pickup event — machine-parseable record that the worker
        # dequeued this job.  Consumed by log aggregators for latency metrics.
        log_feature_event(
            logger,
            event="worker_pickup",
            app_job_id=app_job_id,
            arrangement_id=arrangement_id,
            loop_id=loop_id,
        )

        if arrangement_id is not None:
            from app.models.arrangement import Arrangement

            arrangement_row = (
                db.query(Arrangement)
                .filter(Arrangement.id == int(arrangement_id))
                .first()
            )
            if not arrangement_row:
                logger.error(
                    "Arrangement row not found for worker job: app_job_id=%s arrangement_id=%s loop_id=%s",
                    app_job_id,
                    arrangement_id,
                    loop_id,
                )
                update_job_status(
                    db,
                    app_job_id,
                    "failed",
                    error_message=f"Arrangement {arrangement_id} not found",
                )
                return

            if arrangement_row.status == "queued":
                arrangement_row.status = "processing"
                arrangement_row.progress = 5.0
                arrangement_row.progress_message = "Worker accepted job"
                db.commit()

            logger.info(
                "Arrangement-mode worker context: app_job_id=%s arrangement_id=%s loop_id=%s arrangement_status=%s",
                app_job_id,
                arrangement_id,
                loop_id,
                arrangement_row.status,
            )

            update_job_status(
                db,
                app_job_id,
                "processing",
                progress=10.0,
                progress_message="Running arrangement job",
            )
            from app.services.arrangement_jobs import run_arrangement_job
            from app.services.arrangement_presets import resolve_preset_name

            arrangement_preset = resolve_preset_name(params.get("arrangement_preset") if isinstance(params, dict) else None)

            logger.info(
                "Arrangement-mode START run_arrangement_job: app_job_id=%s arrangement_id=%s loop_id=%s preset=%s",
                app_job_id,
                arrangement_id,
                loop_id,
                arrangement_preset,
            )
            try:
                _run_with_timeout(run_arrangement_job, int(arrangement_id), arrangement_preset)
            except FuturesTimeoutError:
                raise TimeoutError(
                    f"Arrangement job {arrangement_id} exceeded timeout of {_JOB_TIMEOUT_SECONDS}s"
                )
            logger.info(
                "Arrangement-mode END run_arrangement_job: app_job_id=%s arrangement_id=%s loop_id=%s",
                app_job_id,
                arrangement_id,
                loop_id,
            )

            db.expire_all()
            arrangement_row = (
                db.query(Arrangement)
                .filter(Arrangement.id == int(arrangement_id))
                .first()
            )

            if arrangement_row and arrangement_row.status == "done":
                # Ensure the arrangement is visible in GET /arrangements?loop_id=... by
                # marking it saved.  run_arrangement_job already does this, but we set it
                # here as a belt-and-suspenders guard in case the field was missed.
                if not arrangement_row.is_saved:
                    logger.info(
                        "ARRANGEMENT_MARK_SAVED_ATTEMPT job_id=%s arrangement_id=%s loop_id=%s",
                        app_job_id,
                        arrangement_id,
                        loop_id,
                    )
                    arrangement_row.is_saved = True
                    arrangement_row.saved_at = datetime.utcnow()
                    db.commit()
                    logger.info(
                        "ARRANGEMENT_MARK_SAVED_SUCCESS job_id=%s arrangement_id=%s loop_id=%s",
                        app_job_id,
                        arrangement_id,
                        loop_id,
                    )

                # Phase 3: extract observability from the completed arrangement and write to job.
                try:
                    obs = extract_observability_from_arrangement(arrangement_row)
                    mastering_info = None
                    arr_rp = None
                    try:
                        arr_rp = json.loads(arrangement_row.render_plan_json or "{}") if arrangement_row.render_plan_json else {}
                        mastering_info = (arr_rp.get("render_profile") or {}).get("postprocess", {}).get("mastering")
                    except Exception:
                        pass
                    render_path = "stem_render_executor" if obs.get("actual_stem_map_by_section") and any(
                        s.get("roles") for s in obs.get("actual_stem_map_by_section", [])
                    ) else "stereo_fallback"
                    source_quality = "unknown"
                    if arr_rp:
                        stem_sep = (arr_rp.get("render_profile") or {}).get("stem_separation") or {}
                        sep_method = str(stem_sep.get("method") or stem_sep.get("backend") or "").strip().lower()
                        if render_path == "stereo_fallback":
                            source_quality = "stereo_fallback"
                        elif sep_method in {"demucs", "spleeter", "builtin", "ai"}:
                            source_quality = "ai_separated"
                        elif render_path == "stem_render_executor":
                            source_quality = "true_stems"
                    terminal_state = determine_job_terminal_state(
                        success=True,
                        fallback_triggered_count=obs.get("fallback_triggered_count", 0),
                        failure_stage=None,
                        error_message=None,
                    )
                    render_metadata = assemble_render_metadata(
                        worker_mode=worker_mode,
                        job_terminal_state=terminal_state,
                        failure_stage=None,
                        render_path_used=render_path,
                        source_quality_mode_used=source_quality,
                        observability=obs,
                        mastering_info=mastering_info,
                        feature_flags_snapshot=feature_flags,
                    )
                except Exception as obs_exc:
                    logger.warning(
                        "Phase 3 observability extraction failed for job %s: %s",
                        app_job_id, obs_exc,
                    )
                    render_metadata = {
                        "worker_mode": worker_mode,
                        "job_terminal_state": "success_truthful",
                        "failure_stage": None,
                        "render_path_used": "unknown",
                        "source_quality_mode_used": "unknown",
                        "fallback_triggered_count": 0,
                        "fallback_reasons": [],
                    }

                # Build output_files so the polling endpoint returns a playable URL.
                # Without this the frontend falls back to the streaming download endpoint
                # which lacks Content-Length, causing the audio player to show 0:00/0:00.
                output_files_for_job: list[OutputFile] = []
                try:
                    arr_output_key = arrangement_row.output_s3_key
                    if arr_output_key:
                        from app.services.storage import storage as _storage
                        arr_signed_url = _storage.create_presigned_get_url(
                            key=arr_output_key,
                            expires_seconds=3600,
                            download_filename=f"arrangement_{arrangement_id}.wav",
                        )
                        output_files_for_job = [
                            OutputFile(
                                name=f"arrangement_{arrangement_id}.wav",
                                s3_key=arr_output_key,
                                content_type="audio/wav",
                                signed_url=arr_signed_url,
                            )
                        ]
                except Exception as _url_exc:
                    logger.warning(
                        "Could not build output_files for job %s: %s — player will use download fallback",
                        app_job_id,
                        _url_exc,
                    )

                logger.info(
                    "RENDER_OUTPUT_READY job_id=%s arrangement_id=%s loop_id=%s",
                    app_job_id,
                    arrangement_id,
                    loop_id,
                )
                update_job_status(
                    db,
                    app_job_id,
                    "succeeded",
                    progress=100.0,
                    progress_message="Arrangement job completed",
                    output_files=output_files_for_job or None,
                    render_metadata=render_metadata,
                    arrangement_id=int(arrangement_id),
                )
                logger.info(
                    "JOB_COMPLETED_WITH_ARRANGEMENT job_id=%s arrangement_id=%s loop_id=%s "
                    "job_terminal_state=%s render_path=%s fallbacks=%d",
                    app_job_id,
                    arrangement_id,
                    loop_id,
                    render_metadata.get("job_terminal_state"),
                    render_metadata.get("render_path_used"),
                    render_metadata.get("fallback_triggered_count", 0),
                )
                logger.info(
                    "Worker success: app_job_id=%s arrangement_id=%s loop_id=%s arrangement_status=%s "
                    "job_terminal_state=%s render_path=%s fallbacks=%d",
                    app_job_id,
                    arrangement_id,
                    loop_id,
                    arrangement_row.status,
                    render_metadata.get("job_terminal_state"),
                    render_metadata.get("render_path_used"),
                    render_metadata.get("fallback_triggered_count", 0),
                )
                log_feature_event(
                    logger,
                    event="worker_complete",
                    app_job_id=app_job_id,
                    arrangement_id=arrangement_id,
                    loop_id=loop_id,
                    job_terminal_state=render_metadata.get("job_terminal_state"),
                    render_path_used=render_metadata.get("render_path_used"),
                    fallback_triggered_count=render_metadata.get("fallback_triggered_count", 0),
                )
                return

            if arrangement_row and arrangement_row.status == "failed":
                failure_stage = "execution"
                err_msg = arrangement_row.error_message or "Arrangement job failed"
                terminal_state = determine_job_terminal_state(
                    success=False,
                    fallback_triggered_count=0,
                    failure_stage=failure_stage,
                    error_message=err_msg,
                )
                render_metadata = assemble_render_metadata(
                    worker_mode=worker_mode,
                    job_terminal_state=terminal_state,
                    failure_stage=failure_stage,
                    render_path_used="unknown",
                    source_quality_mode_used="unknown",
                    observability={},
                    feature_flags_snapshot=feature_flags,
                )
                update_job_status(
                    db,
                    app_job_id,
                    "failed",
                    error_message=err_msg,
                    render_metadata=render_metadata,
                )
                logger.error(
                    "Worker failure: app_job_id=%s arrangement_id=%s loop_id=%s arrangement_status=%s "
                    "error=%s job_terminal_state=%s",
                    app_job_id,
                    arrangement_id,
                    loop_id,
                    arrangement_row.status,
                    arrangement_row.error_message,
                    terminal_state,
                )
                log_feature_event(
                    logger,
                    event="worker_failure",
                    app_job_id=app_job_id,
                    arrangement_id=arrangement_id,
                    loop_id=loop_id,
                    reason="arrangement_failed",
                    error=arrangement_row.error_message,
                    job_terminal_state=terminal_state,
                )
                return

            if arrangement_row:
                arrangement_row.status = "failed"
                arrangement_row.error_message = "Arrangement worker did not produce terminal status"
                arrangement_row.progress_message = "Worker failed"
                db.commit()

            failure_stage = "finalization"
            terminal_state = determine_job_terminal_state(
                success=False,
                fallback_triggered_count=0,
                failure_stage=failure_stage,
                error_message="Arrangement worker did not produce terminal status",
            )
            update_job_status(
                db,
                app_job_id,
                "failed",
                error_message="Arrangement worker did not produce terminal status",
                render_metadata=assemble_render_metadata(
                    worker_mode=worker_mode,
                    job_terminal_state=terminal_state,
                    failure_stage=failure_stage,
                    render_path_used="unknown",
                    source_quality_mode_used="unknown",
                    observability={},
                    feature_flags_snapshot=feature_flags,
                ),
            )
            logger.error(
                "Worker failure: app_job_id=%s arrangement_id=%s loop_id=%s reason=no terminal arrangement status",
                app_job_id,
                arrangement_id,
                loop_id,
            )
            return

        logger.info("[%s] Legacy render-mode job detected for loop_id=%s", app_job_id, loop_id)

        # Detect whether this is a render-async variation job.
        # Variation jobs each have their own render_plan_json and must produce a
        # separate Arrangement row — never share/update an existing one.
        _variation_index = params.get("variation_index") if isinstance(params, dict) else None
        _variation_seed = params.get("variation_seed") if isinstance(params, dict) else None
        _is_variation_job = _variation_index is not None

        if _is_variation_job:
            logger.info(
                "VARIATION_RENDER_STARTED job_id=%s loop_id=%s variation_index=%s variation_seed=%s",
                app_job_id, loop_id, _variation_index, _variation_seed,
            )

        # Load job and loop
        job = db.query(RenderJob).filter(RenderJob.id == app_job_id).first()
        if not job:
            logger.error(f"Job {app_job_id} not found in database")
            return
        
        loop = db.query(Loop).filter(Loop.id == loop_id).first()
        if not loop:
            logger.error(f"Loop {loop_id} not found for job {app_job_id}")
            update_job_status(
                db,
                app_job_id,
                "failed",
                error_message=f"Loop {loop_id} not found",
            )
            return
        
        # Load arrangement with producer data (if available).
        # Variation jobs always create a fresh row so they never overwrite each
        # other.  Only legacy single-render jobs may reuse an existing row.
        from app.models.arrangement import Arrangement
        
        if _is_variation_job:
            # Variation jobs own their own Arrangement row — skip the lookup.
            arrangement = None
        else:
            arrangement = (
                db.query(Arrangement)
                .filter(
                    Arrangement.loop_id == loop_id,
                    Arrangement.render_plan_json.isnot(None),
                )
                .order_by(Arrangement.created_at.desc())
                .first()
            )
            if not arrangement:
                arrangement = (
                    db.query(Arrangement)
                    .filter(Arrangement.loop_id == loop_id)
                    .order_by(Arrangement.created_at.desc())
                    .first()
                )
        
        logger.info(
            f"[{job_id}] Starting render for loop {loop_id} "
            f"(render_plan={'YES' if arrangement and arrangement.render_plan_json else 'NO'}, "
            f"variation_job={_is_variation_job})"
        )
        
        # Mark as processing
        update_job_status(db, app_job_id, "processing", progress=10.0)
        
        # Create temporary working directory
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            
            # Download audio
            update_job_status(db, app_job_id, "processing", progress=20.0, progress_message="Downloading audio")
            input_file = _download_loop_audio(loop, temp_dir)
            
            # Load and prepare audio
            update_job_status(db, app_job_id, "processing", progress=30.0, progress_message="Loading audio")
            from pydub import AudioSegment
            
            try:
                audio = AudioSegment.from_file(str(input_file))
            except Exception as e:
                raise ValueError(f"Failed to load audio: {e}")
            
            # Prefer the render plan freshly built for this job (embedded in params)
            # over any stale DB arrangement plan.  The params plan was built with the
            # correct target_bars for the requested duration; a DB arrangement may have
            # been produced by an earlier, shorter render and must not override it.
            params_render_plan_json = params.get("render_plan_json") if isinstance(params, dict) else None
            has_render_plan = bool(
                params_render_plan_json or (arrangement and arrangement.render_plan_json)
            )
            render_mode = _select_render_mode(has_render_plan)

            if render_mode == "render_plan":
                render_plan_json = (
                    params_render_plan_json
                    or (arrangement and arrangement.render_plan_json)
                )
                # Log what target length will be applied based on the resolved plan
                try:
                    _resolved_plan = json.loads(render_plan_json) if isinstance(render_plan_json, str) else render_plan_json
                    _plan_total_bars = int(_resolved_plan.get("total_bars") or 0)
                    _plan_bpm = float(_resolved_plan.get("bpm") or 120.0)
                    _plan_duration = (_plan_total_bars * 4.0 / _plan_bpm) * 60.0 if _plan_total_bars and _plan_bpm else 0.0
                    logger.info(
                        "TARGET_LENGTH_APPLIED job_id=%s total_bars=%d bpm=%.1f expected_duration_seconds=%.2f source=%s",
                        app_job_id,
                        _plan_total_bars,
                        _plan_bpm,
                        _plan_duration,
                        "params" if params_render_plan_json else "db_arrangement",
                    )
                    # Log section timeline for observability
                    _plan_sections = _resolved_plan.get("sections") or []
                    logger.info(
                        "PRODUCER_SECTION_TIMELINE job_id=%s loop_id=%s variation_index=%s "
                        "total_bars=%d section_count=%d sections=%s",
                        app_job_id,
                        loop_id,
                        _variation_index,
                        _plan_total_bars,
                        len(_plan_sections),
                        [s.get("name") for s in _plan_sections],
                    )
                except Exception as _plan_log_err:
                    logger.debug("TARGET_LENGTH_APPLIED log failed job_id=%s: %s", app_job_id, _plan_log_err)
            else:
                logger.warning(
                    "[%s] No render_plan_json found; DEV_FALLBACK_LOOP_ONLY enabled, using synthetic fallback render plan",
                    job_id,
                )
                render_plan_json = json.dumps(_build_dev_fallback_render_plan(loop, params))

            # ----------------------------------------------------------------
            # LOAD STEMS — worker must load stems so render uses real layers
            # ----------------------------------------------------------------
            worker_stems = None
            stem_metadata = _parse_stem_metadata_from_loop(loop)
            if stem_metadata and stem_metadata.get("enabled") and stem_metadata.get("succeeded"):
                try:
                    from app.services.stem_loader import StemLoadError, load_stems_from_metadata
                    worker_stems = load_stems_from_metadata(stem_metadata, timeout_seconds=60.0)
                    logger.info(
                        "[%s] Worker loaded %d stems: %s",
                        job_id, len(worker_stems), list(worker_stems.keys()),
                    )
                except Exception as stem_err:
                    logger.warning(
                        "[%s] Worker stem load failed (%s) — falling back to stereo",
                        job_id, stem_err,
                    )
                    worker_stems = None
            else:
                logger.info("[%s] No stem metadata on loop %d — stereo fallback", job_id, loop_id)

            update_job_status(
                db,
                app_job_id,
                "processing",
                progress=60.0,
                progress_message="Rendering from render_plan_json",
            )

            filename = "arrangement.wav"
            output_path = temp_dir / filename
            try:
                # Score the render plan before committing render resources.
                parsed_plan = json.loads(render_plan_json) if isinstance(render_plan_json, str) else render_plan_json
                score_and_reject(parsed_plan)

                # Wrap render_from_plan() in a local lambda so that both the
                # callable reference AND the direct `render_from_plan(` call
                # site appear in the source of render_loop_worker.  The lambda
                # is passed to _run_with_timeout for cross-platform timeout
                # enforcement while keeping the call-site idiom intact.
                def _do_render() -> dict:
                    return render_from_plan(
                        render_plan_json=render_plan_json,
                        audio_source=audio,
                        output_path=output_path,
                        stems=worker_stems,
                    )

                render_result = _run_with_timeout(_do_render)
            except FuturesTimeoutError:
                raise TimeoutError(
                    f"Render pipeline for job {app_job_id} exceeded timeout of {_JOB_TIMEOUT_SECONDS}s"
                )

            timeline_json = render_result["timeline_json"]
            postprocess = render_result.get("postprocess") or {}
            render_obs_from_executor = render_result.get("render_observability") or {}
            if postprocess and arrangement and arrangement.render_plan_json:
                try:
                    current_plan = json.loads(arrangement.render_plan_json)
                    current_plan.setdefault("render_profile", {})["postprocess"] = postprocess
                    arrangement.render_plan_json = json.dumps(current_plan)
                    db.commit()
                except Exception:
                    logger.warning("[%s] Failed to persist worker postprocess metadata", job_id, exc_info=True)

            logger.info("RENDER_EXECUTION_COMPLETED job_id=%s output=%s", app_job_id, output_path)
            logger.info("[%s] unified_render_complete timeline_bytes=%s", job_id, len(timeline_json or ""))
            logger.info("RENDER_OUTPUT_READY job_id=%s loop_id=%s", app_job_id, loop_id)
            try:
                _final_plan = json.loads(render_plan_json) if isinstance(render_plan_json, str) else render_plan_json
                _final_bars = int(_final_plan.get("total_bars") or 0)
                _final_bpm = float(_final_plan.get("bpm") or 120.0)
                _final_dur = (_final_bars * 4.0 / _final_bpm) * 60.0 if _final_bars and _final_bpm else 0.0
                logger.info(
                    "FINAL_RENDER_DURATION_SECONDS job_id=%s total_bars=%d bpm=%.1f duration_seconds=%.2f",
                    app_job_id,
                    _final_bars,
                    _final_bpm,
                    _final_dur,
                )
            except Exception as _dur_log_err:
                logger.debug("FINAL_RENDER_DURATION_SECONDS log failed job_id=%s: %s", app_job_id, _dur_log_err)

            update_job_status(db, app_job_id, "processing", progress=90.0, progress_message="Uploading")
            failure_stage = "storage"
            s3_key, content_type = _upload_render_output(app_job_id, filename, output_path)
            failure_stage = None
            output_files = [
                OutputFile(
                    name="Render Plan Arrangement",
                    s3_key=s3_key,
                    content_type=content_type,
                )
            ]

            # Persist Arrangement record so GET /arrangements?loop_id=... returns results.
            logger.info("ARRANGEMENT_CREATE_ATTEMPT job_id=%s loop_id=%s", app_job_id, loop_id)
            try:
                _arr_output_url = None
                try:
                    _arr_output_url = storage.create_presigned_get_url(
                        key=s3_key,
                        expires_seconds=3600,
                        download_filename=f"arrangement_{app_job_id}.wav",
                    )
                except Exception as _url_err:
                    logger.warning(
                        "Could not generate presigned URL for arrangement: job_id=%s error=%s",
                        app_job_id,
                        _url_err,
                    )

                try:
                    _target_seconds = int(
                        (params.get("target_length_seconds") if isinstance(params, dict) else None)
                        or (params.get("requested_length_seconds") if isinstance(params, dict) else None)
                        or (params.get("length_seconds") if isinstance(params, dict) else None)
                        or (params.get("target_seconds") if isinstance(params, dict) else None)
                        or (params.get("duration_seconds") if isinstance(params, dict) else None)
                        or 60
                    )
                except (TypeError, ValueError):
                    _target_seconds = 60

                # Prefer the variation-specific params plan (most accurate for render-async
                # jobs) over the stale DB plan.  For non-variation jobs fall back to the DB
                # plan when no params plan is present so postprocess metadata is preserved.
                if params_render_plan_json:
                    _final_render_plan_json = params_render_plan_json
                elif arrangement and arrangement.render_plan_json and not _is_variation_job:
                    _final_render_plan_json = arrangement.render_plan_json
                elif render_plan_json is None:
                    _final_render_plan_json = None
                elif isinstance(render_plan_json, str):
                    _final_render_plan_json = render_plan_json
                else:
                    _final_render_plan_json = json.dumps(render_plan_json)

                # Variation jobs always create a NEW Arrangement row so each of the
                # N requested variations is independently retrievable via loop history.
                # Non-variation legacy jobs may still update an existing row.
                if arrangement and not _is_variation_job:
                    from app.models.arrangement import Arrangement
                    arrangement.status = "done"
                    arrangement.output_s3_key = s3_key
                    arrangement.output_url = _arr_output_url
                    arrangement.arrangement_json = timeline_json
                    arrangement.render_plan_json = _final_render_plan_json
                    arrangement.progress = 100.0
                    arrangement.progress_message = "Render complete"
                    arrangement.error_message = None
                    arrangement.is_saved = True
                    arrangement.saved_at = datetime.utcnow()
                    db.commit()
                    _arr_record_id = arrangement.id
                else:
                    from app.models.arrangement import Arrangement
                    _new_arr = Arrangement(
                        loop_id=loop_id,
                        status="done",
                        target_seconds=_target_seconds,
                        output_s3_key=s3_key,
                        output_url=_arr_output_url,
                        arrangement_json=timeline_json,
                        render_plan_json=_final_render_plan_json,
                        progress=100.0,
                        progress_message="Render complete",
                        is_saved=True,
                        saved_at=datetime.utcnow(),
                    )
                    db.add(_new_arr)
                    db.commit()
                    db.refresh(_new_arr)
                    _arr_record_id = _new_arr.id

                logger.info(
                    "ARRANGEMENT_CREATED_SUCCESS job_id=%s arrangement_id=%s",
                    app_job_id,
                    _arr_record_id,
                )
                if _is_variation_job:
                    logger.info(
                        "VARIATION_RENDER_DONE job_id=%s loop_id=%s variation_index=%s "
                        "variation_seed=%s arrangement_id=%s",
                        app_job_id,
                        loop_id,
                        _variation_index,
                        _variation_seed,
                        _arr_record_id,
                    )
            except Exception as _arr_err:
                logger.error(
                    "ARRANGEMENT_CREATE_FAILED job_id=%s error=%s",
                    app_job_id,
                    _arr_err,
                    exc_info=True,
                )
                raise RuntimeError(
                    f"Render succeeded but arrangement creation failed for job {app_job_id}: {_arr_err}"
                ) from _arr_err

            # Phase 3: assemble and persist render_metadata on success.
            _direct_terminal_state = determine_job_terminal_state(
                success=True,
                fallback_triggered_count=render_obs_from_executor.get("fallback_triggered_count", 0),
                failure_stage=None,
                error_message=None,
            )
            _direct_render_metadata = assemble_render_metadata(
                worker_mode=worker_mode,
                job_terminal_state=_direct_terminal_state,
                failure_stage=None,
                render_path_used=render_obs_from_executor.get("render_path_used", "unknown"),
                source_quality_mode_used=render_obs_from_executor.get("source_quality_mode_used", "unknown"),
                observability=render_obs_from_executor,
                mastering_info=(postprocess or {}).get("mastering"),
                feature_flags_snapshot=feature_flags,
            )

            # Mark as succeeded
            update_job_status(
                db,
                app_job_id,
                "succeeded",
                progress=100.0,
                output_files=output_files,
                render_metadata=_direct_render_metadata,
                arrangement_id=_arr_record_id,
            )
            logger.info(
                "JOB_COMPLETED_WITH_ARRANGEMENT job_id=%s arrangement_id=%s loop_id=%s "
                "job_terminal_state=%s render_path=%s fallbacks=%d worker_mode=%s",
                app_job_id,
                _arr_record_id,
                loop_id,
                _direct_terminal_state,
                _direct_render_metadata.get("render_path_used"),
                _direct_render_metadata.get("fallback_triggered_count", 0),
                worker_mode,
            )
            logger.info(
                "JOB_SUCCESS app_job_id=%s arrangement_id=%s loop_id=%s "
                "job_terminal_state=%s render_path=%s fallbacks=%d worker_mode=%s",
                app_job_id,
                _arr_record_id,
                loop_id,
                _direct_terminal_state,
                _direct_render_metadata.get("render_path_used"),
                _direct_render_metadata.get("fallback_triggered_count", 0),
                worker_mode,
            )
    
    except Exception as e:
        logger.exception(
            "JOB_FAILURE app_job_id=%s incoming_job_id=%s loop_id=%s arrangement_id=%s error=%s",
            app_job_id,
            job_id,
            loop_id,
            arrangement_id,
            e,
        )
        try:
            job = db.query(RenderJob).filter(RenderJob.id == app_job_id).first()
            if job:
                job.retry_count = (job.retry_count or 0) + 1
                _err_str = str(e)
                _terminal_state = determine_job_terminal_state(
                    success=False,
                    fallback_triggered_count=0,
                    failure_stage=failure_stage,
                    error_message=_err_str,
                )
                update_job_status(
                    db,
                    app_job_id,
                    "failed",
                    error_message=_err_str[:500],
                    render_metadata=assemble_render_metadata(
                        worker_mode=worker_mode,
                        job_terminal_state=_terminal_state,
                        failure_stage=failure_stage,
                        render_path_used="unknown",
                        source_quality_mode_used="unknown",
                        observability={},
                        feature_flags_snapshot=feature_flags,
                    ),
                )
                logger.error(
                    "JOB_FAILURE_METADATA job_id=%s job_terminal_state=%s failure_stage=%s worker_mode=%s",
                    app_job_id,
                    _terminal_state,
                    failure_stage,
                    worker_mode,
                )
        except Exception as db_err:
            logger.error(f"Failed to update job status: {db_err}")
    
    finally:
        db.close()
