"""
Health check endpoints.

Provides basic health check and detailed readiness check.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
import boto3
from botocore.exceptions import ClientError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health/live")
async def health_live():
    """Liveness probe: process is running."""
    return {"ok": True}


@router.get("/health/ready")
async def health_ready(db: Session = Depends(get_db)):
    """Readiness probe: DB + Redis + optional S3 checks."""
    db_ok = False
    redis_ok = False
    s3_ok = settings.storage_backend.lower() != "s3"

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
        logger.exception("Readiness Redis check failed")

    if settings.storage_backend.lower() == "s3":
        try:
            missing = []
            if not settings.aws_access_key_id:
                missing.append("AWS_ACCESS_KEY_ID")
            if not settings.aws_secret_access_key:
                missing.append("AWS_SECRET_ACCESS_KEY")
            if not settings.aws_region:
                missing.append("AWS_REGION")
            if not settings.aws_s3_bucket:
                missing.append("AWS_S3_BUCKET")

            if missing:
                s3_ok = False
            else:
                s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                    region_name=settings.aws_region,
                )
                s3_client.head_bucket(Bucket=settings.aws_s3_bucket)
                s3_ok = True
        except ClientError:
            logger.exception("Readiness S3 check failed")
            s3_ok = False
        except Exception:
            logger.exception("Readiness S3 check failed")
            s3_ok = False

    payload = {
        "ok": bool(db_ok and redis_ok and s3_ok),
        "db_ok": db_ok,
        "redis_ok": redis_ok,
        "s3_ok": s3_ok,
        "storage_backend": settings.storage_backend.lower(),
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
