"""
Router for audio arrangement generation.

Handles creation, status tracking, and downloads of generated audio arrangements.
"""

import logging
import os

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.schemas.arrangement import (
    AudioArrangementGenerateRequest,
    AudioArrangementGenerateResponse,
    ArrangementCreateRequest,
    ArrangementResponse,
)
from app.services.arrangement_jobs import run_arrangement_job

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/",
    response_model=ArrangementResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an arrangement job",
    description="Create an arrangement job and process it asynchronously.",
)
def create_arrangement(
    request: ArrangementCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Create an arrangement job and enqueue background processing."""
    loop = db.query(Loop).filter(Loop.id == request.loop_id).first()
    if not loop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Loop with ID {request.loop_id} not found",
        )

    arrangement = Arrangement(
        loop_id=request.loop_id,
        status="queued",
        target_seconds=request.target_duration_seconds,
    )
    db.add(arrangement)
    db.commit()
    db.refresh(arrangement)

    background_tasks.add_task(run_arrangement_job, arrangement.id)
    return ArrangementResponse.from_orm(arrangement)


@router.get(
    "/",
    response_model=list[ArrangementResponse],
    summary="List arrangements",
    description="List arrangements with optional loop_id filter.",
)
def list_arrangements(
    loop_id: int | None = None,
    db: Session = Depends(get_db),
):
    """List arrangements with optional filtering by loop_id."""
    query = db.query(Arrangement)
    if loop_id is not None:
        query = query.filter(Arrangement.loop_id == loop_id)
    arrangements = query.order_by(Arrangement.created_at.desc()).all()
    return [ArrangementResponse.from_orm(item) for item in arrangements]


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
    response_model=ArrangementResponse,
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
    - Current status (queued/processing/done/failed)
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

    return ArrangementResponse.from_orm(arrangement)


@router.get(
    "/{arrangement_id}/download",
    summary="Download generated arrangement",
    description="Download the generated audio file by streaming from S3. Returns 409 if not yet complete.",
)
def download_arrangement(
    arrangement_id: int,
    db: Session = Depends(get_db),
):
    """
    Download the generated audio arrangement.

    Returns 409 Conflict if the arrangement is still being processed.
    Returns 404 if the arrangement doesn't exist.
    Streams audio bytes from S3 if done.
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

    if arrangement.status != "done":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Arrangement is still {arrangement.status}. Try again later.",
        )

    if not arrangement.output_s3_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Arrangement is complete but S3 object key is missing",
        )

    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_region = os.getenv("AWS_REGION")
    s3_bucket = os.getenv("S3_BUCKET")

    if not all([aws_access_key_id, aws_secret_access_key, aws_region, s3_bucket]):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="S3 is not configured. Missing one or more required environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET",
        )

    s3_client = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=aws_region,
    )

    try:
        s3_object = s3_client.get_object(Bucket=s3_bucket, Key=arrangement.output_s3_key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        if error_code in {"NoSuchKey", "404"}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Arrangement file not found in storage",
            ) from exc
        logger.exception("S3 get_object failed for arrangement_id=%s key=%s", arrangement_id, arrangement.output_s3_key)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch arrangement file from storage",
        ) from exc

    content_type = s3_object.get("ContentType") or "audio/wav"
    content_length = s3_object.get("ContentLength")
    output_key_filename = arrangement.output_s3_key.rsplit("/", maxsplit=1)[-1]
    download_filename = output_key_filename or f"arrangement_{arrangement_id}.wav"

    headers = {
        "Content-Disposition": f'attachment; filename="{download_filename}"',
    }
    if content_length is not None:
        headers["Content-Length"] = str(content_length)

    body = s3_object["Body"]

    def iter_s3_stream():
        try:
            for chunk in body.iter_chunks(chunk_size=1024 * 1024):
                if chunk:
                    yield chunk
        finally:
            body.close()

    return StreamingResponse(
        iter_s3_stream(),
        media_type=content_type,
        headers=headers,
    )
