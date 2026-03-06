import logging
from typing import List, Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.loop import Loop
from app.models.schemas import LoopCreate, LoopResponse, LoopUpdate
from app.services.loop_service import loop_service
from app.services.loop_analyzer import loop_analyzer
from app.services.audit_logging import log_feature_event

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/loops/upload", status_code=201)
async def upload_audio(file: UploadFile = File(...), request: Request = None, db: Session = Depends(get_db)):
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
        file_key, file_url = loop_service.upload_loop_file(
            file_content=content,
            filename=safe_filename,
            content_type=file.content_type or "audio/wav"
        )
        if not isinstance(file_url, str) or not file_url:
            file_url = f"/uploads/{file_key.split('/')[-1]}"
    except Exception as e:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
    
    # Analyze audio from S3
    analysis_result = {
        'bpm': None,
        'key': None,
        'duration': None,
        'bars': None
    }
    
    try:
        logger.info(f"Starting audio analysis for file_key: {file_key}")
        analysis_result = await loop_analyzer.analyze_from_s3(file_key)
        logger.info(f"Analysis complete: BPM={analysis_result.get('bpm')}, Key={analysis_result.get('key')}, Bars={analysis_result.get('bars')}, Duration={analysis_result.get('duration')}")
    except Exception as e:
        logger.warning(f"Audio analysis failed (non-fatal): {e}")
        logger.info("Loop will be created with null analysis fields")
    
    # Create Loop database record with analysis results
    try:
        bpm_value = analysis_result.get('bpm')
        normalized_bpm = int(round(float(bpm_value))) if bpm_value is not None else None

        new_loop = Loop(
            name=safe_filename,
            filename=safe_filename,
            file_url=file_url,
            file_key=file_key,  # Store S3 key
            bpm=normalized_bpm,
            musical_key=analysis_result.get('key'),
            duration_seconds=analysis_result.get('duration'),
            bars=analysis_result.get('bars')
        )
        db.add(new_loop)
        db.commit()
        db.refresh(new_loop)
        logger.info(f"Loop uploaded: {new_loop.id} - {file_key}")
        correlation_id = getattr(request.state, "correlation_id", None) if request is not None else None
        log_feature_event(
            logger,
            event="loop_created",
            correlation_id=correlation_id,
            loop_id=new_loop.id,
            bpm=new_loop.bpm,
            bars=new_loop.bars,
            key=new_loop.musical_key,
        )
        
        # Return endpoints instead of direct file URLs
        return {
            "loop_id": new_loop.id,
            "file_url": file_url,
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
    
    # Validate file (configurable max upload size from settings)
    is_valid, error_msg = loop_service.validate_audio_file(
        filename=safe_filename,
        content_type=file.content_type or "audio/wav",
        file_size=len(content),
        max_size_mb=settings.max_upload_size_mb
    )
    
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    try:
        # Upload using service
        file_key, file_url = loop_service.upload_loop_file(
            file_content=content,
            filename=safe_filename,
            content_type=file.content_type or "audio/wav"
        )
        if not isinstance(file_url, str) or not file_url:
            file_url = f"/uploads/{file_key.split('/')[-1]}"
        logger.info(f"File uploaded (no DB record): {file_key}")
        return {"file_key": file_key, "file_url": file_url}
    except Exception as e:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")


@router.post("/loops", response_model=LoopResponse, status_code=201)
def create_loop(loop_in: LoopCreate, request: Request, db: Session = Depends(get_db)):
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
        correlation_id = getattr(request.state, "correlation_id", None)
        log_feature_event(
            logger,
            event="loop_created",
            correlation_id=correlation_id,
            loop_id=loop.id,
            bpm=loop.bpm,
            bars=loop.bars,
            key=loop.musical_key,
        )
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
    request: Request = None,
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
        file_key, file_url = loop_service.upload_loop_file(
            file_content=content,
            filename=safe_filename,
            content_type=file.content_type or "audio/wav"
        )
        if not isinstance(file_url, str) or not file_url:
            file_url = f"/uploads/{file_key.split('/')[-1]}"
    except Exception as e:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
    
    # Analyze audio from S3
    analysis_result = {
        'bpm': None,
        'key': None,
        'duration': None,
        'bars': None
    }
    
    try:
        logger.info(f"Starting audio analysis for file_key: {file_key}")
        analysis_result = await loop_analyzer.analyze_from_s3(file_key)
        logger.info(f"Analysis complete: BPM={analysis_result.get('bpm')}, Key={analysis_result.get('key')}, Bars={analysis_result.get('bars')}, Duration={analysis_result.get('duration')}")
    except Exception as e:
        logger.warning(f"Audio analysis failed (non-fatal): {e}")
        logger.info("Loop will be created with null analysis fields")

    # Create loop with file key and analysis results
    try:
        loop_data_dict = loop_data.model_dump(exclude={"file_url"})
        bpm_value = analysis_result.get('bpm')
        normalized_bpm = int(round(float(bpm_value))) if bpm_value is not None else None
        
        # Merge analysis results into loop data
        loop_data_dict.update({
            'file_url': file_url,
            'file_key': file_key,
            'filename': safe_filename,
        })

        if normalized_bpm is not None:
            loop_data_dict['bpm'] = normalized_bpm
        if analysis_result.get('key') is not None:
            loop_data_dict['musical_key'] = analysis_result.get('key')
        if analysis_result.get('duration') is not None:
            loop_data_dict['duration_seconds'] = analysis_result.get('duration')
        if analysis_result.get('bars') is not None:
            loop_data_dict['bars'] = analysis_result.get('bars')
        
        loop = Loop(**loop_data_dict)
        db.add(loop)
        db.commit()
        db.refresh(loop)
        logger.info(f"Loop created successfully with ID: {loop.id}")
        correlation_id = getattr(request.state, "correlation_id", None) if request is not None else None
        log_feature_event(
            logger,
            event="loop_created",
            correlation_id=correlation_id,
            loop_id=loop.id,
            bpm=loop.bpm,
            bars=loop.bars,
            key=loop.musical_key,
        )
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
def replace_loop(loop_id: int, loop_in: LoopUpdate, db: Session = Depends(get_db)):
    """Update a loop record via PUT.
    
    Args:
        loop_id: Loop ID to replace
        loop_in: Loop update data (partial fields accepted)
        db: Database session
        
    Returns:
        Updated loop record
        
    Raises:
        HTTPException: If loop not found or update fails
    """
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    update_data = loop_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
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


@router.get(
    "/loops/{loop_id}/download",
    response_class=FileResponse,
    summary="Download loop audio file",
    description="Download the original loop audio file. Returns 404 if the loop or file doesn't exist.",
)
def download_loop(
    loop_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Download the original loop audio file.

    Returns 404 if the loop doesn't exist or the file is missing.
    Returns file download response if available.
    """
    loop = db.query(Loop).filter(Loop.id == loop_id).first()

    if not loop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Loop with ID {loop_id} not found",
        )

    if not loop.file_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Loop record exists but file key is missing",
        )

    storage_backend = settings.get_storage_backend()
    download_filename = loop.filename or f"loop_{loop_id}.wav"
    content_type = "audio/wav"

    headers = {
        "Content-Disposition": f'attachment; filename="{download_filename}"',
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Disposition",
    }

    referer = request.headers.get("referer", "")
    is_swagger_request = "/docs" in referer or "/redoc" in referer

    if storage_backend == "local":
        local_filename = loop.file_key.split("/")[-1]
        local_path = Path("uploads") / local_filename
        if not local_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Loop file not found in local storage",
            )

        if is_swagger_request:
            return FileResponse(
                path=str(local_path),
                media_type=content_type,
                filename=download_filename,
                headers=headers,
            )

        def iter_local_stream():
            with open(local_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        return StreamingResponse(
            iter_local_stream(),
            media_type=content_type,
            headers=headers,
        )

    # S3 storage backend
    try:
        from app.services.storage import get_s3_client

        s3 = get_s3_client()
        response = s3.get_object(Bucket=settings.s3_bucket, Key=loop.file_key)

        if is_swagger_request:
            file_content = response["Body"].read()
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name

            try:
                return FileResponse(
                    path=tmp_path,
                    media_type=content_type,
                    filename=download_filename,
                    headers=headers,
                )
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        def stream_s3():
            for chunk in iter(lambda: response["Body"].read(65536), b""):
                yield chunk

        return StreamingResponse(
            stream_s3(),
            media_type=content_type,
            headers=headers,
        )

    except Exception as e:
        logger.exception(f"Failed to download loop {loop_id} from S3: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve loop file from storage",
        )


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