import os
import uuid
import logging
import traceback
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.models.schemas import LoopCreate, LoopResponse, LoopUpdate
from app.services.analyzer import AudioAnalyzer

router = APIRouter()

# Configure logging
logger = logging.getLogger(__name__)

# Allowed MIME types for WAV and MP3 files
ALLOWED_MIME_TYPES = {
    "audio/wav", 
    "audio/x-wav", 
    "audio/wave", 
    "audio/vnd.wave",
    "audio/mpeg",
    "audio/mp3"
}

# MIME type to extension mapping
MIME_TO_EXTENSION = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/vnd.wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3"
}

UPLOAD_DIR = "uploads"


@router.post("/loops/upload", status_code=201)
async def upload_audio(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a WAV or MP3 audio file."""
    # Validate file is provided
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Validate MIME type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Only WAV and MP3 files are allowed. Received: {file.content_type}"
        )
    
    # Create uploads directory if it doesn't exist
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Get the appropriate file extension based on MIME type
    file_extension = MIME_TO_EXTENSION.get(file.content_type, ".wav")
    
    # Generate unique filename with UUID while preserving extension
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    try:
        # Save the file
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
    except Exception as e:
        logger.exception("Failed to save file")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    
    # Create Loop database record
    file_url = f"/uploads/{unique_filename}"
    try:
        new_loop = Loop(name=unique_filename, file_url=file_url)
        db.add(new_loop)
        db.commit()
        db.refresh(new_loop)
        return {"loop_id": new_loop.id, "file_url": new_loop.file_url}
    except Exception as e:
        db.rollback()
        logger.exception("Failed to save loop record")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.post("/upload", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    """Upload a WAV or MP3 audio file. Returns file URL only, no database record."""
    # Max file size: 50MB
    MAX_FILE_SIZE = 50 * 1024 * 1024
    
    # Validate file is provided
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Validate MIME type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Only WAV and MP3 files are allowed. Received: {file.content_type}"
        )
    
    # Create uploads directory if it doesn't exist
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Get the appropriate file extension based on MIME type
    file_extension = MIME_TO_EXTENSION.get(file.content_type, ".wav")
    
    # Generate unique filename with UUID while preserving extension
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    try:
        # Save the file with size validation
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File too large. Maximum size is 50MB.")
        
        with open(file_path, "wb") as buffer:
            buffer.write(content)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to save file")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    
    file_url = f"/uploads/{unique_filename}"
    return {"file_url": file_url}


@router.post("/loops", response_model=LoopResponse, status_code=201)
def create_loop(loop_in: LoopCreate, db: Session = Depends(get_db)):
    """Create a new loop record."""
    try:
        loop = Loop(**loop_in.model_dump())
        db.add(loop)
        db.commit()
        db.refresh(loop)
        return loop
    except Exception as e:
        db.rollback()
        traceback.print_exc()
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

    **loop_in** must be a JSON-encoded string containing the loop metadata, for example:

        {"name": "My Loop", "tempo": 140, "key": "C", "genre": "Trap"}

    This design is required because the endpoint uses multipart/form-data to accept
    both the file and the metadata in a single request.
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
    # Validate MIME type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Only WAV and MP3 files are allowed. Received: {file.content_type}"
        )
    
    # Create uploads directory if it doesn't exist
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Get the appropriate file extension based on MIME type
    file_extension = MIME_TO_EXTENSION.get(file.content_type, ".wav")
    
    # Generate unique filename with UUID
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    try:
        # Save the file
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
    except Exception as e:
        logger.exception("Failed to save file")
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    
    # Run audio analysis
    logger.info(f"Running audio analysis for uploaded file: {file_path}")
    analysis_result = None
    try:
        analysis_result = AudioAnalyzer.analyze_audio(file_path)
        logger.info(
            f"Analysis complete - BPM: {analysis_result['bpm']}, "
            f"Key: {analysis_result['musical_key']}, "
            f"Duration: {analysis_result['duration_seconds']:.2f}s"
        )
    except Exception as e:
        logger.warning(
            f"Audio analysis failed: {str(e)}. Proceeding with loop creation "
            "without analysis data."
        )
        # Continue without analysis - don't fail the entire upload

    # Create loop with file info and analysis data
    file_url = f"/uploads/{unique_filename}"
    try:
        loop_data_dict = loop_data.model_dump(exclude={"file_url"})
        
        # Add analysis results to loop if available
        if analysis_result:
            loop_data_dict["bpm"] = analysis_result["bpm"]
            loop_data_dict["musical_key"] = analysis_result["musical_key"]
            loop_data_dict["duration_seconds"] = analysis_result["duration_seconds"]
            logger.info(
                f"Loop enhanced with analysis: BPM={analysis_result['bpm']}, "
                f"Key={analysis_result['musical_key']}"
            )
        
        loop = Loop(
            **loop_data_dict,
            file_url=file_url
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


@router.get("/loops", response_model=list[LoopResponse])
def list_loops(db: Session = Depends(get_db)):
    return db.query(Loop).all()


@router.get("/loops/{loop_id}", response_model=LoopResponse)
def get_loop(loop_id: int, db: Session = Depends(get_db)):
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")
    return loop


@router.put("/loops/{loop_id}", response_model=LoopResponse, status_code=200)
def replace_loop(loop_id: int, loop_in: LoopCreate, db: Session = Depends(get_db)):
    """Fully replace a loop record (all optional fields not provided are set to null)."""
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
    """Update a loop with only the provided fields."""
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
        logger.exception("Failed to update loop")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.delete("/loops/{loop_id}", status_code=200)
def delete_loop(loop_id: int, db: Session = Depends(get_db)):
    """Delete a loop by id."""
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    try:
        db.delete(loop)
        db.commit()
        return {"deleted": True, "id": loop_id}
    except Exception as e:
        db.rollback()
        logger.exception("Failed to delete loop")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")