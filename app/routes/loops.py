import os
import uuid
import logging
import traceback
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.models.schemas import LoopCreate, LoopResponse, LoopUpdate
from app.services.analyzer import AudioAnalyzer
from app.services.storage import storage
from app.services.loop_service import loop_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/loops/upload", status_code=201)
async def upload_audio(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a WAV or MP3 audio file to S3.
    
    Args:
        file: Audio file (WAV or MP3)
        db: Database session
        
    Returns:
        dict: Contains loop_id, play_url, and download_url
        
    Raises:
        HTTPException: If file type invalid or upload fails
    """
    # Validate file is provided
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Read file content
    content = await file.read()
    
    # Sanitize filename
    safe_filename = loop_service.sanitize_filename(file.filename or "audio.wav")
    
    # Validate file
    is_valid, error_msg = loop_service.validate_audio_file(
        filename=safe_filename,
        content_type=file.content_type or "audio/wav",
        file_size=len(content)
    )
    
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    try:
        # Upload file using service (returns file_key like "uploads/uuid.wav")
        file_key, _ = loop_service.upload_loop_file(
            file_content=content,
            filename=safe_filename,
            content_type=file.content_type or "audio/wav"
        )
    except Exception as e:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
    
    # Create Loop database record
    try:
        new_loop = Loop(
            name=safe_filename,
            filename=safe_filename,
            file_key=file_key  # Store S3 key
        )
        db.add(new_loop)
        db.commit()
        db.refresh(new_loop)
        logger.info(f"Loop uploaded: {new_loop.id} - {file_key}")
        
        # Return endpoints instead of direct file URLs
        return {
            "loop_id": new_loop.id,
            "play_url": f"/api/v1/loops/{new_loop.id}/play",
            "download_url": f"/api/v1/loops/{new_loop.id}/download"
        }
    except Exception as e:
        db.rollback()
        logger.exception("Failed to save loop record")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.post("/upload", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    """Upload a WAV or MP3 audio file to S3. Returns file key only, no database record.
    
    Args:
        file: Audio file (WAV or MP3)
        
    Returns:
        dict: Contains file_key (S3 key like "uploads/uuid.wav")
        
    Raises:
        HTTPException: If file type invalid, too large, or upload fails
    """
    # Validate file is provided
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Read file content
    content = await file.read()
    
    # Sanitize filename
    safe_filename = loop_service.sanitize_filename(file.filename or "audio.wav")
    
    # Validate file (max 50MB)
    is_valid, error_msg = loop_service.validate_audio_file(
        filename=safe_filename,
        content_type=file.content_type or "audio/wav",
        file_size=len(content),
        max_size_mb=50
    )
    
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    try:
        # Upload using service
        file_key, _ = loop_service.upload_loop_file(
            file_content=content,
            filename=safe_filename,
            content_type=file.content_type or "audio/wav"
        )
        logger.info(f"File uploaded (no DB record): {file_key}")
        return {"file_key": file_key}
    except Exception as e:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")


@router.post("/loops", response_model=LoopResponse, status_code=201)
def create_loop(loop_in: LoopCreate, db: Session = Depends(get_db)):
    """Create a new loop record.
    
    Args:
        loop_in: Loop creation data
        db: Database session
        
    Returns:
        Created loop record
        
    Raises:
        HTTPException: If creation fails
    """
    try:
        loop = loop_service.create_loop(db, loop_in)
        return loop
    except Exception as e:
        logger.exception("Failed to create loop")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/loops/with-file", response_model=LoopResponse, status_code=201)
async def create_loop_with_upload(
    loop_in: str = Form(
        ...,
        description=(
            'JSON string containing loop metadata, e.g. '
            '{"name":"My Loop","tempo":140,"key":"C","genre":"Trap"}'
        ),
    ),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Create a loop with file upload.
    
    Args:
        loop_in: JSON-encoded string containing loop metadata
        file: Audio file (WAV or MP3)
        db: Database session

    **loop_in** must be a JSON-encoded string containing the loop metadata, for example:
        {"name": "My Loop", "tempo": 140, "key": "C", "genre": "Trap"}

    This design is required because the endpoint uses multipart/form-data to accept
    both the file and the metadata in a single request.
    
    Returns:
        Created loop record with analysis data if successful
        
    Raises:
        HTTPException: If JSON invalid, file type invalid, or creation fails
    """
    # Parse the JSON string into a LoopCreate schema
    try:
        loop_data = LoopCreate.model_validate_json(loop_in)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid loop_in JSON: {exc.errors()}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"loop_in must be a valid JSON string: {exc}",
        )
    
    # Read file content
    content = await file.read()
    
    # Sanitize filename
    safe_filename = loop_service.sanitize_filename(file.filename or "audio.wav")
    
    # Validate file
    is_valid, error_msg = loop_service.validate_audio_file(
        filename=safe_filename,
        content_type=file.content_type or "audio/wav",
        file_size=len(content)
    )
    
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    try:
        # Upload using service (returns file_key like "uploads/uuid.wav")
        file_key, _ = loop_service.upload_loop_file(
            file_content=content,
            filename=safe_filename,
            content_type=file.content_type or "audio/wav"
        )
    except Exception as e:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
    
    # Audio analysis is skipped for S3 uploads - use /analyze-loop endpoint instead
    logger.info(f"File uploaded with key: {file_key}")
    logger.info("Note: For S3 storage, use POST /analyze-loop/{id} endpoint for audio analysis")

    # Create loop with file key
    try:
        loop_data_dict = loop_data.model_dump(exclude={"file_url"})
        
        loop = Loop(
            **loop_data_dict,
            file_key=file_key,
            filename=safe_filename
        )
        db.add(loop)
        db.commit()
        db.refresh(loop)
        logger.info(f"Loop created successfully with ID: {loop.id}")
        return loop
    except Exception as e:
        db.rollback()
        logger.exception("Failed to create loop with upload")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/loops", response_model=List[LoopResponse])
def list_loops(
    status: Optional[str] = Query(None, description="Filter by status: pending, processing, complete, failed"),
    genre: Optional[str] = Query(None, description="Filter by genre"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db)
):
    """List all loops with optional filters and pagination.
    
    Args:
        status: Optional status filter
        genre: Optional genre filter
        limit: Maximum results (1-1000)
        offset: Pagination offset
        db: Database session
        
    Returns:
        List of loop records
    """
    loops = loop_service.list_loops(
        db=db,
        status=status,
        genre=genre,
        limit=limit,
        offset=offset
    )
    return loops


@router.get("/loops/{loop_id}", response_model=LoopResponse)
def get_loop(loop_id: int, db: Session = Depends(get_db)):
    """Get a single loop by ID.
    
    Args:
        loop_id: Loop ID
        db: Database session
        
    Returns:
        Loop record with all fields including status, processed_file_url, analysis_json
        
    Raises:
        HTTPException: If loop not found
    """
    loop = loop_service.get_loop(db, loop_id)
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")
    return loop


@router.put("/loops/{loop_id}", response_model=LoopResponse, status_code=200)
def replace_loop(loop_id: int, loop_in: LoopCreate, db: Session = Depends(get_db)):
    """Fully replace a loop record (all optional fields not provided are set to null).
    
    Args:
        loop_id: Loop ID to replace
        loop_in: New loop data
        db: Database session
        
    Returns:
        Updated loop record
        
    Raises:
        HTTPException: If loop not found or update fails
    """
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    # model_dump(exclude_unset=False) includes defaults (None) so that omitted
    # optional fields are explicitly cleared – correct PUT (full-replace) semantics.
    for field, value in loop_in.model_dump(exclude_unset=False).items():
        setattr(loop, field, value)

    try:
        db.commit()
        db.refresh(loop)
        return loop
    except Exception as e:
        db.rollback()
        logger.exception("Failed to replace loop")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.patch("/loops/{loop_id}", response_model=LoopResponse, status_code=200)
def update_loop(loop_id: int, loop_in: LoopUpdate, db: Session = Depends(get_db)):
    """Update a loop with only the provided fields.
    
    Args:
        loop_id: Loop ID to update
        loop_in: Partial update data
        db: Database session
        
    Returns:
        Updated loop record
        
    Raises:
        HTTPException: If loop not found or update fails
    """
    try:
        loop = loop_service.update_loop(db, loop_id, loop_in)
        if loop is None:
            raise HTTPException(status_code=404, detail="Loop not found")
        return loop
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update loop")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.delete("/loops/{loop_id}", status_code=200)
def delete_loop(
    loop_id: int,
    delete_file: bool = Query(True, description="Also delete the audio file"),
    db: Session = Depends(get_db)
):
    """Delete a loop by id.
    
    Args:
        loop_id: Loop ID to delete
        delete_file: Whether to also delete the associated file
        db: Database session
        
    Returns:
        Confirmation with deleted flag and ID
        
    Raises:
        HTTPException: If loop not found or deletion fails
    """
    try:
        deleted = loop_service.delete_loop(db, loop_id, delete_file=delete_file)
        if not deleted:
            raise HTTPException(status_code=404, detail="Loop not found")
        return {"deleted": True, "id": loop_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to delete loop")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")