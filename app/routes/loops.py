import os
import uuid
import logging
import traceback
import boto3
from botocore.exceptions import ClientError
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

# AWS S3 Configuration
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Initialize S3 client if credentials are provided
s3_client = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_S3_BUCKET:
    try:
        s3_client = boto3.client(
            "s3",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
        logger.info(f"✅ S3 client initialized for bucket: {AWS_S3_BUCKET}")
    except Exception as e:
        logger.warning(f"⚠️  Failed to initialize S3 client: {e}")
        s3_client = None
else:
    logger.warning(
        "⚠️  AWS S3 credentials not configured. Set AWS_S3_BUCKET, "
        "AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY environment variables."
    )


async def upload_to_s3(file_content: bytes, s3_key: str) -> str:
    """Upload file to AWS S3 and return public URL.
    
    Args:
        file_content: File binary content
        s3_key: S3 object key (path in bucket)
        
    Returns:
        Public URL to the uploaded file
        
    Raises:
        HTTPException: If S3 upload fails
    """
    if not s3_client or not AWS_S3_BUCKET:
        raise HTTPException(
            status_code=500,
            detail="S3 not configured. Set AWS_S3_BUCKET, AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY."
        )
    
    try:
        # Upload file to S3
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET,
            Key=s3_key,
            Body=file_content,
            ContentType="audio/mpeg" if s3_key.endswith(".mp3") else "audio/wav",
        )
        
        # Generate public URL
        file_url = f"https://{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
        logger.info(f"✅ File uploaded to S3: {file_url}")
        return file_url
    except ClientError as e:
        logger.exception(f"S3 upload failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload to S3: {str(e)}"
        )


@router.post("/loops/upload", status_code=201)
async def upload_audio(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a WAV or MP3 audio file to S3."""
    # Validate file is provided
    if not file:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Validate MIME type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Only WAV and MP3 files are allowed. Received: {file.content_type}"
        )
    
    # Get the appropriate file extension based on MIME type
    file_extension = MIME_TO_EXTENSION.get(file.content_type, ".wav")
    
    # Generate unique filename with UUID while preserving extension
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    s3_key = f"uploads/{unique_filename}"
    
    try:
        # Read file content
        content = await file.read()
        
        # Upload to S3
        file_url = await upload_to_s3(content, s3_key)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
    
    # Create Loop database record
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
    """Upload a WAV or MP3 audio file to S3. Returns file URL only, no database record."""
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
    
    # Get the appropriate file extension based on MIME type
    file_extension = MIME_TO_EXTENSION.get(file.content_type, ".wav")
    
    # Generate unique filename with UUID while preserving extension
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    s3_key = f"uploads/{unique_filename}"
    
    try:
        # Read file content with size validation
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File too large. Maximum size is 50MB.")
        
        # Upload to S3
        file_url = await upload_to_s3(content, s3_key)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
    
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
    
    # Get the appropriate file extension based on MIME type
    file_extension = MIME_TO_EXTENSION.get(file.content_type, ".wav")
    
    # Generate unique filename with UUID
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    s3_key = f"uploads/{unique_filename}"
    
    try:
        # Read file content
        content = await file.read()
        
        # Upload to S3
        file_url = await upload_to_s3(content, s3_key)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to upload file")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
    
    # Run audio analysis on the uploaded file
    logger.info(f"Running audio analysis for uploaded file: {s3_key}")
    analysis_result = None
    try:
        # Note: AudioAnalyzer.analyze_audio() currently requires a local file path.
        # For S3-hosted files, you would need to either:
        # 1. Download the file temporarily from S3 before analysis
        # 2. Stream the audio from S3 directly
        # 3. Use a different audio analysis service that supports S3 URLs
        # For now, we skip analysis for S3 uploads
        logger.info("Audio analysis skipped for S3 uploads (requires local file)")
    except Exception as e:
        logger.warning(
            f"Audio analysis failed: {str(e)}. Proceeding with loop creation "
            "without analysis data."
        )
        # Continue without analysis - don't fail the entire upload

    # Create loop with file info and S3 URL
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
        else:
            logger.info(f"Loop created without audio analysis (S3 mode)")
        
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