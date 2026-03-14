
"""Async render job endpoints - Redis queue-based background processing."""

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.queue import is_redis_available
from app.routes.render import RenderConfig
from app.schemas.job import RenderJobRequest, RenderJobResponse, RenderJobStatusResponse, RenderJobHistoryResponse
from app.services.job_service import create_render_job, get_job_status, list_loop_jobs

router = APIRouter()


# ── Async Job Endpoints ───────────────────────────────────────────────────────────
# New async render pipeline using Redis queue

@router.post("/loops/{loop_id}/render-async", response_model=RenderJobResponse, status_code=202)
async def render_arrangement_async(
    loop_id: int,
    config: RenderConfig = Body(default=RenderConfig()),
    db: Session = Depends(get_db),
):
    """Enqueue a render job asynchronously.
    
    Returns immediately with job_id. Poll GET /api/v1/jobs/{job_id} for status.
    """
    # Check Redis availability first
    if not is_redis_available():
        raise HTTPException(
            status_code=503,
            detail="Background job queue is unavailable. Redis service may be offline."
        )
    
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    if not (loop.file_key or loop.file_url):
        raise HTTPException(status_code=400, detail="Loop has no associated audio file")
    
    params = {
        "genre": config.genre,
        "length_seconds": config.length_seconds,
        "energy": config.energy,
        "variations": config.variations,
        "variation_styles": config.variation_styles,
        "custom_style": config.custom_style,
    }
    
    try:
        job, was_deduplicated = create_render_job(db, loop_id, params)
        return RenderJobResponse(
            job_id=job.id,
            loop_id=loop_id,
            status=job.status,
            created_at=job.created_at,
            poll_url=f"/api/v1/jobs/{job.id}",
            deduplicated=was_deduplicated,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/jobs/{job_id}", response_model=RenderJobStatusResponse)
async def get_job_status_endpoint(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Get full status of a render job, including outputs and presigned URLs."""
    try:
        job_status = get_job_status(db, job_id)
        return job_status
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/loops/{loop_id}/jobs", response_model=RenderJobHistoryResponse)
async def get_loop_jobs(
    loop_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """List all render jobs for a loop (recent first)."""
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if not loop:
        raise HTTPException(status_code=404, detail="Loop not found")
    
    jobs = list_loop_jobs(db, loop_id, limit)
    return RenderJobHistoryResponse(loop_id=loop_id, jobs=jobs)
