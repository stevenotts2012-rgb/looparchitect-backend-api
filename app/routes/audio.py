"""
Audio processing routes.

Handles:
- Loop download
- Beat generation
- Loop extension
- Background task status
"""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.services.storage import storage
from app.services.task_service import task_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/loops/{loop_id}/play")
async def play_loop(
    loop_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a presigned URL to play/stream a loop audio file.

    Returns JSON with a presigned S3 URL (expires in 1 hour) or local URL.

    Args:
        loop_id: ID of the loop to play

    Returns:
        JSON with {"url": "<presigned_url>"}

    Raises:
        404: If loop not found or file not available
    """
    # Get loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    if not loop.file_key:
        raise HTTPException(
            status_code=404,
            detail=f"Loop {loop_id} has no associated file"
        )
    
    try:
        # Generate presigned URL (expires in 1 hour)
        play_url = storage.create_presigned_get_url(
            key=loop.file_key,
            expires_seconds=3600
        )
        
        logger.info(f"Generated play URL for loop {loop_id}")
        return {"url": play_url}
    except Exception as e:
        logger.error(f"Failed to generate play URL for loop {loop_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate play URL"
        )


@router.get("/loops/{loop_id}/download")
async def download_loop(
    loop_id: int,
    db: Session = Depends(get_db)
):
    """
    Download a loop audio file.

    Returns a redirect to presigned S3 URL with Content-Disposition header
    to force download with the loop's name.

    Args:
        loop_id: ID of the loop to download

    Returns:
        Redirect to presigned URL (with download filename)

    Raises:
        404: If loop not found
        500: If file is not accessible
    """
    # Get loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    if not loop.file_key:
        raise HTTPException(
            status_code=404,
            detail=f"Loop {loop_id} has no associated file"
        )
    
    try:
        # Determine file extension from file_key
        file_ext = loop.file_key.split(".")[-1] if "." in loop.file_key else "wav"
        
        # Generate download filename from loop name
        download_filename = f"{loop.name or f'loop_{loop_id}'}.{file_ext}"
        
        # Generate presigned URL with Content-Disposition for download
        download_url = storage.create_presigned_get_url(
            key=loop.file_key,
            expires_seconds=3600,  # 1 hour
            download_filename=download_filename
        )
        
        logger.info(f"Generated download URL for loop {loop_id}: {download_filename}")
        return RedirectResponse(url=download_url)
    except Exception as e:
        logger.error(f"Download failed for loop {loop_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate download URL"
        )


@router.get("/loops/{loop_id}/stream")
async def stream_loop(
    loop_id: int,
    db: Session = Depends(get_db)
):
    """
    Stream a loop audio file.

    For S3 storage, redirects to presigned URL.
    For local storage, returns streaming response.

    Args:
        loop_id: ID of the loop to stream

    Returns:
        Redirect or StreamingResponse with audio data

    Raises:
        404: If loop not found
        500: If file is not accessible
    """
    # Get loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    if not loop.file_key:
        raise HTTPException(
            status_code=404,
            detail=f"Loop {loop_id} has no associated file"
        )
    
    try:
        # For S3, redirect to presigned URL (more efficient)
        if storage.use_s3:
            play_url = storage.create_presigned_get_url(
                key=loop.file_key,
                expires_seconds=3600
            )
            return RedirectResponse(url=play_url)
        else:
            # For local files, stream directly
            # This is a simplified implementation - storage module doesn't expose get_file_stream
            # For local mode, just redirect to the uploads path
            local_url = f"/uploads/{loop.file_key.split('/')[-1]}"
            return RedirectResponse(url=local_url)
    
    except Exception as e:
        logger.error(f"Stream failed for loop {loop_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to stream audio file"
        )


@router.get("/loops/{loop_id}/info")
async def get_loop_audio_info(
    loop_id: int,
    db: Session = Depends(get_db)
):
    """
    Get loop metadata and audio status.
    
    This endpoint is part of the audio router and provides
    loop information in the context of audio operations.

    Args:
        loop_id: ID of the loop

    Returns:
        Loop record with all fields including audio status

    Raises:
        404: If loop not found
    """
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    return {
        "id": loop.id,
        "name": loop.name,
        "file_key": loop.file_key,
        "play_url": f"/api/v1/loops/{loop.id}/play" if loop.file_key else None,
        "download_url": f"/api/v1/loops/{loop.id}/download" if loop.file_key else None,
        "status": loop.status,
        "bpm": loop.bpm,
        "musical_key": loop.musical_key,
        "genre": loop.genre,
        "duration_seconds": loop.duration_seconds,
        "processed_file_url": loop.processed_file_url,
        "analysis_json": loop.analysis_json,
        "created_at": loop.created_at
    }


@router.post("/generate-beat/{loop_id}")
async def generate_beat(
    loop_id: int,
    background_tasks: BackgroundTasks,
    target_length: int = Query(..., ge=10, le=600, description="Target length in seconds"),
    db: Session = Depends(get_db)
):
    """
    Generate a full beat from a loop.

    This endpoint queues a background task and returns immediately.
    Use GET /api/v1/loops/{loop_id} to check status.

    Args:
        loop_id: ID of the source loop
        target_length: Desired beat length in seconds (10-600)
        background_tasks: FastAPI background tasks
        db: Database session

    Returns:
        JSON with task status and loop ID

    Raises:
        404: If loop not found
    """
    # Get loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    # Generate unique filename for output
    output_filename = f"beat_{loop_id}_{uuid.uuid4().hex[:8]}.wav"
    
    # Update status to pending
    loop.status = "pending"
    db.commit()
    
    # Queue background task
    background_tasks.add_task(
        task_service.generate_beat_task,
        loop_id=loop_id,
        target_length_seconds=target_length,
        output_filename=output_filename
    )
    
    logger.info(f"Beat generation queued for loop {loop_id}")
    
    return {
        "loop_id": loop_id,
        "status": "pending",
        "message": f"Beat generation queued for {target_length} seconds",
        "check_status_at": f"/api/v1/loops/{loop_id}"
    }


@router.post("/extend-loop/{loop_id}")
async def extend_loop(
    loop_id: int,
    background_tasks: BackgroundTasks,
    bars: int = Query(..., ge=1, le=128, description="Number of bars to extend to"),
    db: Session = Depends(get_db)
):
    """
    Extend a loop to a specific number of bars.

    This endpoint queues a background task and returns immediately.
    Use GET /api/v1/loops/{loop_id} to check status.

    Args:
        loop_id: ID of the source loop
        bars: Number of bars to extend to (1-128)
        background_tasks: FastAPI background tasks
        db: Database session

    Returns:
        JSON with task status and loop ID

    Raises:
        404: If loop not found
    """
    # Get loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    # Generate unique filename for output
    output_filename = f"extended_{loop_id}_{bars}bars_{uuid.uuid4().hex[:8]}.wav"
    
    # Update status to pending
    loop.status = "pending"
    db.commit()
    
    # Queue background task
    background_tasks.add_task(
        task_service.extend_loop_task,
        loop_id=loop_id,
        bars=bars,
        output_filename=output_filename
    )
    
    logger.info(f"Loop extension queued for loop {loop_id}, bars={bars}")
    
    return {
        "loop_id": loop_id,
        "status": "pending",
        "message": f"Loop extension queued for {bars} bars",
        "check_status_at": f"/api/v1/loops/{loop_id}"
    }


@router.post("/analyze-loop/{loop_id}")
async def analyze_loop(
    loop_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Analyze a loop to detect BPM, key, and duration.

    This endpoint queues a background task and returns immediately.
    Use GET /api/v1/loops/{loop_id} to check status.

    Args:
        loop_id: ID of the loop to analyze
        background_tasks: FastAPI background tasks
        db: Database session

    Returns:
        JSON with task status and loop ID

    Raises:
        404: If loop not found
    """
    # Get loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    # Update status to pending
    loop.status = "pending"
    db.commit()
    
    # Queue background task
    background_tasks.add_task(
        task_service.analyze_loop_task,
        loop_id=loop_id
    )
    
    logger.info(f"Analysis queued for loop {loop_id}")
    
    return {
        "loop_id": loop_id,
        "status": "pending",
        "message": "Loop analysis queued",
        "check_status_at": f"/api/v1/loops/{loop_id}"
    }
