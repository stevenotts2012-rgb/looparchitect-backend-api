"""Service for managing render jobs: creation, deduplication, status updates."""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.job import RenderJob
from app.models.loop import Loop
from app.queue import DEFAULT_RENDER_QUEUE_NAME, get_queue
from app.schemas.job import OutputFile, RenderJobStatusResponse

logger = logging.getLogger(__name__)


def _compute_dedupe_hash(loop_id: int, params: Dict) -> str:
    """Hash (loop_id, render params) for deduplication."""
    key = json.dumps({"loop_id": loop_id, "params": params}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()


def _find_existing_job(
    db: Session, loop_id: int, dedupe_hash: str, window_minutes: int = 5
) -> Optional[RenderJob]:
    """Find a recent identical job to avoid duplication."""
    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
    job = (
        db.query(RenderJob)
        .filter(
            RenderJob.loop_id == loop_id,
            RenderJob.dedupe_hash == dedupe_hash,
            RenderJob.created_at >= cutoff,
            RenderJob.status.in_(["queued", "processing", "succeeded"]),
        )
        .order_by(RenderJob.created_at.desc())
        .first()
    )
    return job


def create_render_job(
    db: Session,
    loop_id: int,
    params: Dict,
    dedupe_window_minutes: int = 5,
) -> tuple[RenderJob, bool]:
    """
    Create a new render job, or return existing if deduplicated.
    
    Args:
        db: Database session
        loop_id: Loop to render
        params: RenderConfig as dict
        dedupe_window_minutes: Window to check for deduplication
    
    Returns:
        (job, was_deduplicated)
    """
    # Validate loop exists and has audio
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if not loop:
        raise ValueError(f"Loop {loop_id} not found")
    if not (loop.file_key or loop.file_url):
        raise ValueError(f"Loop {loop_id} has no audio file")
    
    # Compute deduplication hash
    dedupe_hash = _compute_dedupe_hash(loop_id, params)
    
    # Check for existing job in window
    existing_job = _find_existing_job(db, loop_id, dedupe_hash, dedupe_window_minutes)
    if existing_job:
        logger.info(f"Deduplicated job request: loop_id={loop_id}, reusing job_id={existing_job.id}")
        return existing_job, True
    
    # Create new job
    import uuid
    job_id = str(uuid.uuid4())
    
    job = RenderJob(
        id=job_id,
        loop_id=loop_id,
        job_type="render_arrangement",
        params_json=json.dumps(params),
        dedupe_hash=dedupe_hash,
        status="queued",
        queued_at=datetime.utcnow(),
    )
    
    db.add(job)
    db.commit()
    db.refresh(job)
    
    logger.info(f"Created render job: job_id={job_id}, loop_id={loop_id}")
    
    # Enqueue to Redis
    queue = get_queue(name=DEFAULT_RENDER_QUEUE_NAME)
    from app.workers.render_worker import render_loop_worker

    queue.enqueue(render_loop_worker, job_id, loop_id, params)
    logger.info(
        "Enqueued render job: job_id=%s queue_name=%s function_name=%s",
        job_id,
        queue.name,
        render_loop_worker.__name__,
    )
    
    return job, False


def update_job_status(
    db: Session,
    job_id: str,
    status: str,
    progress: float = None,
    progress_message: str = None,
    error_message: str = None,
    output_files: List[OutputFile] = None,
) -> RenderJob:
    """Update job status inline (called by worker)."""
    job = db.query(RenderJob).filter(RenderJob.id == job_id).first()
    if not job:
        raise ValueError(f"Job {job_id} not found")
    
    job.status = status
    
    if progress is not None:
        job.progress = progress
    if progress_message is not None:
        job.progress_message = progress_message
    if error_message is not None:
        job.error_message = error_message
    
    if status == "processing" and not job.started_at:
        job.started_at = datetime.utcnow()
    elif status in ["succeeded", "failed"]:
        job.finished_at = datetime.utcnow()
        if output_files:
            output_list = [f.model_dump() for f in output_files]
            job.output_files_json = json.dumps(output_list)
    
    db.commit()
    db.refresh(job)
    return job


def get_job_status(db: Session, job_id: str) -> RenderJobStatusResponse:
    """Fetch full job status with presigned URLs for outputs."""
    job = db.query(RenderJob).filter(RenderJob.id == job_id).first()
    if not job:
        raise ValueError(f"Job {job_id} not found")
    
    # Parse outputs and regenerate presigned URLs if succeeded
    output_files = None
    if job.output_files_json:
        try:
            outputs = json.loads(job.output_files_json)
            # Regenerate presigned URLs (they expire, so do this on-demand)
            from app.services.storage import storage
            
            output_files = []
            for output in outputs:
                s3_key = output.get("s3_key")
                if s3_key:
                    signed_url = storage.create_presigned_get_url(
                        key=s3_key,
                        expires_seconds=3600,  # 1 hour
                        download_filename=output.get("name"),
                    )
                    output_files.append(
                        OutputFile(
                            name=output.get("name"),
                            s3_key=s3_key,
                            content_type=output.get("content_type", "audio/wav"),
                            signed_url=signed_url,
                        )
                    )
        except Exception as e:
            logger.error(f"Failed to parse outputs for job {job_id}: {e}")
    
    return RenderJobStatusResponse(
        job_id=job.id,
        loop_id=job.loop_id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress or 0.0,
        progress_message=job.progress_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        output_files=output_files,
        error_message=job.error_message,
        retry_count=job.retry_count,
    )


def list_loop_jobs(db: Session, loop_id: int, limit: int = 20) -> List[RenderJobStatusResponse]:
    """List jobs for a loop (recent first)."""
    jobs = (
        db.query(RenderJob)
        .filter(RenderJob.loop_id == loop_id)
        .order_by(RenderJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return [get_job_status(db, job.id) for job in jobs]
