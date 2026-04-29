
"""Async render job endpoints - Redis queue-based background processing."""

import json
import logging
from typing import Dict

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.queue import is_redis_available
from app.routes.render import RenderConfig
from app.schemas.job import RenderJobRequest, RenderJobResponse, RenderJobStatusResponse, RenderJobHistoryResponse
from app.services.job_service import create_render_job, get_job_status, list_loop_jobs

router = APIRouter()
logger = logging.getLogger(__name__)


def _build_minimal_render_plan(loop: Loop, params: Dict) -> dict:
    """Build a minimal valid render plan from a loop when no existing plan is available.

    Prefers the loop's own bpm/bars values; falls back to safe defaults so the
    worker always receives a well-formed plan.
    """
    bpm = float(loop.bpm or loop.tempo or 120.0)
    loop_length_bars = int(loop.bars or 8)

    # Discover available stem roles; fall back to a sensible generic set.
    available_roles: list = []
    try:
        stem_roles = loop.stem_roles  # dict of {role: file_key}
        if stem_roles:
            available_roles = list(stem_roles.keys())
    except Exception:
        pass
    if not available_roles:
        available_roles = ["full_mix"]

    return {
        "loop_id": loop.id,
        "bpm": bpm,
        "sections": [
            {
                "name": "full_loop",
                "type": "VERSE",
                "start_bar": 0,
                "length_bars": loop_length_bars,
                "active_stem_roles": available_roles,
                "instruments": available_roles,
            }
        ],
    }


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
    logger.info("render_async_request_received: loop_id=%s", loop_id)

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

    # ── Build render_plan_json ────────────────────────────────────────────────
    # Prefer an existing arrangement's render_plan_json; otherwise build a
    # minimal valid plan so the worker always receives one.
    render_plan_json: str | None = None

    logger.info("render_plan_json_build_started: loop_id=%s", loop_id)

    try:
        from app.models.arrangement import Arrangement

        existing_arrangement = (
            db.query(Arrangement)
            .filter(
                Arrangement.loop_id == loop_id,
                Arrangement.render_plan_json.isnot(None),
            )
            .order_by(Arrangement.created_at.desc())
            .first()
        )
        if existing_arrangement and existing_arrangement.render_plan_json:
            render_plan_json = existing_arrangement.render_plan_json
            logger.info(
                "render_plan_json_build_success: loop_id=%s source=existing_arrangement arrangement_id=%s",
                loop_id,
                existing_arrangement.id,
            )
        else:
            minimal_plan = _build_minimal_render_plan(loop, {
                "genre": config.genre,
                "length_seconds": config.length_seconds,
            })
            render_plan_json = json.dumps(minimal_plan)
            logger.info(
                "render_plan_json_build_success: loop_id=%s source=minimal_fallback",
                loop_id,
            )
    except Exception as plan_err:
        logger.error(
            "render_plan_json_missing_failed: loop_id=%s error=%s",
            loop_id,
            plan_err,
            exc_info=True,
        )
        render_plan_json = None

    if not render_plan_json:
        logger.error(
            "render_plan_json_missing_failed: loop_id=%s reason=could_not_build_plan",
            loop_id,
        )
        raise HTTPException(
            status_code=400,
            detail="Could not build render_plan_json for this loop. Ensure the loop has valid metadata.",
        )

    params = {
        "genre": config.genre,
        "length_seconds": config.length_seconds,
        "energy": config.energy,
        "variations": config.variations,
        "variation_styles": config.variation_styles,
        "custom_style": config.custom_style,
        "render_plan_json": render_plan_json,
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
