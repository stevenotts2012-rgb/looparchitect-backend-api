"""Async render worker: pulls jobs from Redis queue and processes them."""

import logging
import os
import tempfile
import traceback
import json
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

logger = logging.getLogger(__name__)

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
            "Worker start processing: app_job_id=%s arrangement_id=%s loop_id=%s",
            app_job_id,
            arrangement_id,
            loop_id,
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

            logger.info(
                "Arrangement-mode START run_arrangement_job: app_job_id=%s arrangement_id=%s loop_id=%s",
                app_job_id,
                arrangement_id,
                loop_id,
            )
            run_arrangement_job(int(arrangement_id))
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
                update_job_status(
                    db,
                    app_job_id,
                    "succeeded",
                    progress=100.0,
                    progress_message="Arrangement job completed",
                )
                logger.info(
                    "Worker success: app_job_id=%s arrangement_id=%s loop_id=%s arrangement_status=%s",
                    app_job_id,
                    arrangement_id,
                    loop_id,
                    arrangement_row.status,
                )
                return

            if arrangement_row and arrangement_row.status == "failed":
                update_job_status(
                    db,
                    app_job_id,
                    "failed",
                    error_message=arrangement_row.error_message or "Arrangement job failed",
                )
                logger.error(
                    "Worker failure: app_job_id=%s arrangement_id=%s loop_id=%s arrangement_status=%s error=%s",
                    app_job_id,
                    arrangement_id,
                    loop_id,
                    arrangement_row.status,
                    arrangement_row.error_message,
                )
                return

            if arrangement_row:
                arrangement_row.status = "failed"
                arrangement_row.error_message = "Arrangement worker did not produce terminal status"
                arrangement_row.progress_message = "Worker failed"
                db.commit()

            update_job_status(
                db,
                app_job_id,
                "failed",
                error_message="Arrangement worker did not produce terminal status",
            )
            logger.error(
                "Worker failure: app_job_id=%s arrangement_id=%s loop_id=%s reason=no terminal arrangement status",
                app_job_id,
                arrangement_id,
                loop_id,
            )
            return

        logger.info("[%s] Legacy render-mode job detected for loop_id=%s", app_job_id, loop_id)

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
        
        # Load arrangement with producer data (if available)
        from app.models.arrangement import Arrangement
        
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
            f"(render_plan={'YES' if arrangement and arrangement.render_plan_json else 'NO'})"
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
            
            render_mode = _select_render_mode(bool(arrangement and arrangement.render_plan_json))

            if render_mode == "render_plan":
                render_plan_json = arrangement.render_plan_json
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
            render_result = render_from_plan(
                render_plan_json=render_plan_json,
                audio_source=audio,
                output_path=output_path,
                stems=worker_stems,
            )

            timeline_json = render_result["timeline_json"]
            postprocess = render_result.get("postprocess") or {}
            if postprocess and arrangement and arrangement.render_plan_json:
                try:
                    current_plan = json.loads(arrangement.render_plan_json)
                    current_plan.setdefault("render_profile", {})["postprocess"] = postprocess
                    arrangement.render_plan_json = json.dumps(current_plan)
                    db.commit()
                except Exception:
                    logger.warning("[%s] Failed to persist worker postprocess metadata", job_id, exc_info=True)

            logger.info("[%s] unified_render_complete timeline_bytes=%s", job_id, len(timeline_json or ""))

            update_job_status(db, app_job_id, "processing", progress=90.0, progress_message="Uploading")
            s3_key, content_type = _upload_render_output(app_job_id, filename, output_path)
            output_files = [
                OutputFile(
                    name="Render Plan Arrangement",
                    s3_key=s3_key,
                    content_type=content_type,
                )
            ]
            
            # Mark as succeeded
            update_job_status(
                db,
                app_job_id,
                "succeeded",
                progress=100.0,
                output_files=output_files,
            )
            logger.info(f"[{app_job_id}] Render completed successfully")
    
    except Exception as e:
        logger.exception(
            "Worker failure with traceback: app_job_id=%s incoming_job_id=%s loop_id=%s arrangement_id=%s params=%s error=%s",
            app_job_id,
            job_id,
            loop_id,
            arrangement_id if 'arrangement_id' in locals() else None,
            params,
            e,
        )
        try:
            job = db.query(RenderJob).filter(RenderJob.id == app_job_id).first()
            if job:
                job.retry_count = (job.retry_count or 0) + 1
                update_job_status(
                    db,
                    app_job_id,
                    "failed",
                    error_message=f"{str(e)[:500]}",
                )
        except Exception as db_err:
            logger.error(f"Failed to update job status: {db_err}")
    
    finally:
        db.close()
