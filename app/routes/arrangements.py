"""
Router for audio arrangement generation.

Handles creation, status tracking, and downloads of generated audio arrangements.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.schemas.arrangement import (
    AudioArrangementGenerateRequest,
    AudioArrangementGenerateResponse,
    AudioArrangementResponse,
)
from app.services.arrangement_jobs import run_arrangement_job

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/generate",
    response_model=AudioArrangementGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate an audio arrangement",
    description="Submit a request to generate a full audio arrangement from a loop. "
    "The arrangement will be generated asynchronously. Use the returned arrangement_id "
    "to poll status or download the result.",
)
def generate_arrangement(
    request: AudioArrangementGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Generate an audio arrangement from an uploaded loop.

    - **loop_id**: ID of the source loop to arrange
    - **target_seconds**: Desired duration (10-3600 seconds)
    - **genre**: Optional genre hint
    - **intensity**: Optional intensity level (low/medium/high)
    - **include_stems**: Whether to generate separate stems

    Returns immediately with arrangement_id. Check status endpoint for progress.
    """
    # Validate that loop exists
    loop = db.query(Loop).filter(Loop.id == request.loop_id).first()
    if not loop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Loop with ID {request.loop_id} not found",
        )

    # Create arrangement record
    arrangement = Arrangement(
        loop_id=request.loop_id,
        status="queued",
        target_seconds=request.target_seconds,
        genre=request.genre,
        intensity=request.intensity,
        include_stems=request.include_stems,
    )
    db.add(arrangement)
    db.commit()
    db.refresh(arrangement)

    # Schedule background job
    background_tasks.add_task(run_arrangement_job, arrangement.id)

    return AudioArrangementGenerateResponse(
        arrangement_id=arrangement.id,
        loop_id=arrangement.loop_id,
        status=arrangement.status,
        created_at=arrangement.created_at,
    )


@router.get(
    "/{arrangement_id}",
    response_model=AudioArrangementResponse,
    summary="Get arrangement status",
    description="Get the current status and details of an arrangement generation job.",
)
def get_arrangement(
    arrangement_id: int,
    db: Session = Depends(get_db),
):
    """
    Get status and details of an arrangement.

    Returns the arrangement record including:
    - Current status (queued/processing/complete/failed)
    - Download URL (if complete)
    - Error message (if failed)
    """
    arrangement = (
        db.query(Arrangement)
        .filter(Arrangement.id == arrangement_id)
        .first()
    )

    if not arrangement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arrangement with ID {arrangement_id} not found",
        )

    return AudioArrangementResponse.from_orm(arrangement)


@router.get(
    "/{arrangement_id}/download",
    summary="Download generated arrangement",
    description="Download the generated audio file. Returns 409 if not yet complete.",
)
def download_arrangement(
    arrangement_id: int,
    db: Session = Depends(get_db),
):
    """
    Download the generated audio arrangement.

    Returns 409 Conflict if the arrangement is still being processed.
    Returns 404 if the arrangement doesn't exist.
    Returns 200 with audio/wav if complete.
    """
    arrangement = (
        db.query(Arrangement)
        .filter(Arrangement.id == arrangement_id)
        .first()
    )

    if not arrangement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arrangement with ID {arrangement_id} not found",
        )

    if arrangement.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Arrangement generation failed: {arrangement.error_message}",
        )

    if arrangement.status != "complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Arrangement is still {arrangement.status}. Try again later.",
        )

    # File should exist at output_file_url
    if not arrangement.output_file_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Arrangement is complete but output file is missing",
        )

    # Resolve file path from URL
    # output_file_url is like "/renders/arrangements/uuid.wav"
    file_path = Path(arrangement.output_file_url.lstrip("/"))

    # For local renders, construct full path assuming renders/ is relative to cwd
    full_path = Path.cwd() / file_path

    if not full_path.exists():
        logger.error(f"Output file not found: {full_path}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Output file not found on disk",
        )

    # Return file
    from fastapi.responses import FileResponse

    return FileResponse(
        path=full_path,
        media_type="audio/wav",
        filename=f"arrangement_{arrangement_id}.wav",
    )
