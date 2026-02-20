import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.models.schemas import LoopCreate, LoopResponse, LoopUpdate

router = APIRouter()

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
async def upload_audio(file: UploadFile = File(...)):
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
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    
    # Return the file URL
    return {"file_url": f"/uploads/{unique_filename}"}


@router.post("/loops", response_model=LoopResponse, status_code=201)
def create_loop(loop_in: LoopCreate, db: Session = Depends(get_db)):
    loop = Loop(**loop_in.model_dump())
    db.add(loop)
    try:
        db.commit()
        db.refresh(loop)
    except Exception:
        db.rollback()
        raise
    return loop


@router.get("/loops", response_model=list[LoopResponse])
def list_loops(db: Session = Depends(get_db)):
    return db.query(Loop).all()


@router.get("/loops/{loop_id}", response_model=LoopResponse)
def get_loop(loop_id: int, db: Session = Depends(get_db)):
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")
    return loop


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
    except Exception:
        db.rollback()
        raise

    return loop


@router.delete("/loops/{loop_id}", status_code=200)
def delete_loop(loop_id: int, db: Session = Depends(get_db)):
    """Delete a loop by id."""
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    try:
        db.delete(loop)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"deleted": True, "id": loop_id}