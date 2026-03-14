"""
Health check endpoints.

Provides basic health check and detailed readiness check.
"""

import logging
import shutil
from fastapi import APIRouter, Depends, HTTPException
import boto3
from botocore.exceptions import ClientError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.job import RenderJob

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health/live")
async def health_live():
    """Liveness probe: process is running."""
    return {"ok": True}


@router.get("/health/ready")
async def health_ready(db: Session = Depends(get_db)):
    """Readiness probe: DB + Redis + optional S3 + FFmpeg checks."""
    db_ok = False
    redis_ok = False
    ffmpeg_ok = False
    redis_required = settings.is_production
    active_storage_backend = settings.get_storage_backend()
    s3_ok = active_storage_backend != "s3"

    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.exception("Readiness DB check failed")

    try:
        from app.queue import get_redis_conn
        redis_conn = get_redis_conn()
        redis_ok = bool(redis_conn.ping())
    except Exception:
        if redis_required:
            logger.exception("Readiness Redis check failed (required in production)")
        else:
            logger.warning("Readiness Redis check failed in development mode (non-blocking)")

    # Check FFmpeg availability
    try:
        ffmpeg_path = settings.ffmpeg_binary or shutil.which("ffmpeg")
        ffprobe_path = settings.ffprobe_binary or shutil.which("ffprobe")
        ffmpeg_ok = bool(ffmpeg_path and ffprobe_path)
        if ffmpeg_ok:
            logger.info("FFmpeg detected: ffmpeg=%s, ffprobe=%s", ffmpeg_path, ffprobe_path)
        elif settings.should_enforce_audio_binaries:
            logger.warning("FFmpeg/FFprobe missing and required (production policy enabled)")
        else:
            logger.warning("FFmpeg/FFprobe missing in development mode (audio decode may be limited)")
    except Exception:
        logger.exception("Readiness FFmpeg check failed")
        ffmpeg_ok = False

    if active_storage_backend == "s3":
        try:
            missing = []
            if not settings.aws_access_key_id:
                missing.append("AWS_ACCESS_KEY_ID")
            if not settings.aws_secret_access_key:
                missing.append("AWS_SECRET_ACCESS_KEY")
            if not settings.aws_region:
                missing.append("AWS_REGION")
            bucket_name = settings.get_s3_bucket()
            if not bucket_name:
                missing.append("AWS_S3_BUCKET or S3_BUCKET_NAME")

            if missing:
                s3_ok = False
            else:
                s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                    region_name=settings.aws_region,
                )
                s3_client.head_bucket(Bucket=bucket_name)
                s3_ok = True
        except ClientError:
            logger.exception("Readiness S3 check failed")
            s3_ok = False
        except Exception:
            logger.exception("Readiness S3 check failed")
            s3_ok = False

    payload = {
        "ok": bool(db_ok and (redis_ok or not redis_required) and s3_ok and ffmpeg_ok),
        "db_ok": db_ok,
        "redis_ok": redis_ok,
        "redis_required": redis_required,
        "s3_ok": s3_ok,
        "ffmpeg_ok": ffmpeg_ok,
        "storage_backend": active_storage_backend,
    }

    if not payload["ok"]:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@router.get("/health")
async def health_check_legacy():
    """Backward-compatible health endpoint."""
    return {"status": "ok", "message": "Service is healthy"}


@router.get("/ready")
async def readiness_check_legacy(db: Session = Depends(get_db)):
    """Backward-compatible readiness endpoint."""
    return await health_ready(db)


@router.get("/health/queue")
async def health_queue_debug(db: Session = Depends(get_db)):
    """Queue debug endpoint: queue depth and failed job counts."""
    def _count_jobs_by_status(status_value: str):
        try:
            value = db.execute(
                text("SELECT COUNT(*) FROM render_jobs WHERE status = :status"),
                {"status": status_value},
            ).scalar()
            return int(value or 0)
        except Exception as exc:
            logger.warning("Queue debug DB count failed for status=%s: %s", status_value, exc)
            return None

    failed_db_jobs = _count_jobs_by_status("failed")
    queued_db_jobs = _count_jobs_by_status("queued")
    processing_db_jobs = _count_jobs_by_status("processing")

    queue_name = "render"
    redis_ok = False
    queue_depth = None
    failed_queue_jobs = None
    queue_error = None

    try:
        from app.queue import DEFAULT_RENDER_QUEUE_NAME, get_redis_conn, get_queue

        queue_name = DEFAULT_RENDER_QUEUE_NAME
        redis_conn = get_redis_conn()
        redis_ok = bool(redis_conn.ping())

        queue = get_queue(redis_conn, name=queue_name)
        queue_depth = int(queue.count)
        failed_queue_jobs = int(len(queue.failed_job_registry))
    except Exception as exc:
        queue_error = str(exc)
        logger.warning("Queue debug check failed: %s", exc)

    return {
        "ok": bool(redis_ok),
        "queue_name": queue_name,
        "redis_ok": redis_ok,
        "queue_depth": queue_depth,
        "failed_queue_jobs": failed_queue_jobs,
        "failed_db_jobs": int(failed_db_jobs) if failed_db_jobs is not None else None,
        "queued_db_jobs": int(queued_db_jobs) if queued_db_jobs is not None else None,
        "processing_db_jobs": int(processing_db_jobs) if processing_db_jobs is not None else None,
        "error": queue_error,
    }
