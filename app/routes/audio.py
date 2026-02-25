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
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.services.storage_service import storage_service
from app.services.task_service import task_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/loops/{loop_id}/download")
async def download_loop(
    loop_id: int,
    db: Session = Depends(get_db)
):
    """
    Download a loop audio file.

    Returns a signed URL for S3 or streams the file for local storage.

    Args:
        loop_id: ID of the loop to download

    Returns:
        Redirect to signed URL (S3) or FileResponse (local)

    Raises:
        404: If loop not found
        500: If file is not accessible
    """
    # Get loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    if not loop.file_url:
        raise HTTPException(
            status_code=404,
            detail=f"Loop {loop_id} has no associated file"
        )
    
    try:
        # Check if using S3 or local storage
        if storage_service.use_s3:
            # Generate signed URL for S3
            download_url = storage_service.generate_download_url(
                file_key=loop.file_url,
                expiration=3600  # 1 hour
            )
            return RedirectResponse(url=download_url)
        else:
            # Serve local file
            file_path = storage_service.get_file_path(loop.file_url)
            
            if not file_path or not file_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail="File not found on disk"
                )
            
            return FileResponse(
                path=str(file_path),
                media_type="audio/wav",
                filename=f"loop_{loop_id}.wav"
            )
    
    except HTTPException:
        raise
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

    Returns a streaming response for progressive audio playback.

    Args:
        loop_id: ID of the loop to stream

    Returns:
        StreamingResponse with audio data

    Raises:
        404: If loop not found
        500: If file is not accessible
    """
    # Get loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    if not loop.file_url:
        raise HTTPException(
            status_code=404,
            detail=f"Loop {loop_id} has no associated file"
        )
    
    try:
        # Get file stream from storage service
        file_stream = storage_service.get_file_stream(loop.file_url)
        
        # Determine media type from file extension
        media_type = "audio/mpeg" if loop.file_url.endswith(".mp3") else "audio/wav"
        
        # Return streaming response
        return StreamingResponse(
            content=file_stream,
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'inline; filename="loop_{loop_id}.wav"'
            }
        )
    
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Audio file not found"
        )
    except Exception as e:
        logger.error(f"Stream failed for loop {loop_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to stream audio file"
        )


@router.get("/loops/{loop_id}")
async def get_loop(
    loop_id: int,
    db: Session = Depends(get_db)
):
    """
    Get loop metadata and status.

    Args:
        loop_id: ID of the loop

    Returns:
        Loop record with all fields

    Raises:
        404: If loop not found
    """
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    return {
        "id": loop.id,
        "name": loop.name,
        "file_url": loop.file_url,
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
