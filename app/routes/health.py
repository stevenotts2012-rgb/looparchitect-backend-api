"""
Health check endpoints.

Provides basic health check and detailed readiness check.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.schemas import HealthResponse
from app.services.storage_service import storage_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Basic health check.

    Returns 200 OK if service is running.

    Returns:
        Status message
    """
    return HealthResponse(status="ok", message="Service is healthy")


@router.get("/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """
    Detailed readiness check.

    Checks:
    - Database connectivity
    - Storage accessibility

    Returns:
        Detailed system status

    Raises:
        503: If system is not ready
    """
    health_status = {
        "status": "ready",
        "checks": {}
    }
    
    all_healthy = True
    
    # Check database
    try:
        db.execute(text("SELECT 1"))
        health_status["checks"]["database"] = {
            "status": "healthy",
            "message": "Database connection OK"
        }
        logger.debug("Database check: OK")
    except Exception as e:
        all_healthy = False
        health_status["checks"]["database"] = {
            "status": "unhealthy",
            "message": f"Database error: {str(e)}"
        }
        logger.error(f"Database check failed: {e}")
    
    # Check storage
    try:
        if storage_service.use_s3:
            # For S3, check if we can list objects (minimal check)
            try:
                storage_service.s3_client.list_objects_v2(
                    Bucket=storage_service.bucket_name,
                    MaxKeys=1
                )
                health_status["checks"]["storage"] = {
                    "status": "healthy",
                    "type": "s3",
                    "bucket": storage_service.bucket_name,
                    "message": "S3 storage accessible"
                }
                logger.debug("S3 storage check: OK")
            except Exception as e:
                all_healthy = False
                health_status["checks"]["storage"] = {
                    "status": "unhealthy",
                    "type": "s3",
                    "message": f"S3 error: {str(e)}"
                }
                logger.error(f"S3 check failed: {e}")
        else:
            # For local storage, check if directory is writable
            if storage_service.upload_dir.exists() and storage_service.upload_dir.is_dir():
                health_status["checks"]["storage"] = {
                    "status": "healthy",
                    "type": "local",
                    "path": str(storage_service.upload_dir),
                    "message": "Local storage accessible"
                }
                logger.debug("Local storage check: OK")
            else:
                all_healthy = False
                health_status["checks"]["storage"] = {
                    "status": "unhealthy",
                    "type": "local",
                    "message": "Upload directory not accessible"
                }
                logger.error("Local storage check failed")
    except Exception as e:
        all_healthy = False
        health_status["checks"]["storage"] = {
            "status": "unhealthy",
            "message": f"Storage check error: {str(e)}"
        }
        logger.error(f"Storage check failed: {e}")
    
    # Set overall status
    if not all_healthy:
        health_status["status"] = "degraded"
        raise HTTPException(
            status_code=503,
            detail=health_status
        )
    
    return health_status
