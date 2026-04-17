import logging
import io
import json
from typing import List, Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from pydub import AudioSegment

from app.config import settings
from app.db import get_db
from app.models.loop import Loop
from app.models.schemas import LoopCreate, LoopResponse, LoopUpdate
from app.services.loop_service import loop_service
from app.services.loop_analyzer import loop_analyzer
from app.services.audit_logging import log_feature_event
from app.services.stem_separation import separate_and_store_stems
from app.services.stem_pack_service import (
    StemPackError,
    StemSourceFile,
    ingest_stem_files,
    ingest_stem_zip,
    persist_role_stems,
)
from app.services.stem_ingestion_router import (
    SOURCE_MODE_MULTI_STEM,
    SOURCE_MODE_SINGLE_FILE,
    SOURCE_MODE_ZIP_STEM,
    build_manifest_from_ai_separation,
    build_manifest_from_uploaded_stems,
)
from app.services.canonical_stem_manifest import SOURCE_UPLOADED_STEM, SOURCE_ZIP_STEM

router = APIRouter()
logger = logging.getLogger(__name__)


def _build_stem_analysis_json(
    existing_analysis: dict,
    *,
    source_content: bytes,
    source_filename: str,
    loop_id: int,
    source_key: str,
) -> str:
    payload = dict(existing_analysis or {})
    if not settings.feature_stem_separation:
        payload["stem_separation"] = {
            "enabled": False,
            "backend": settings.stem_separation_backend,
            "succeeded": False,
            "reason": "feature_disabled",
        }
        return json.dumps(payload)

    try:
        source_audio = AudioSegment.from_file(io.BytesIO(source_content), format=source_filename.split(".")[-1].lower())
    except Exception as e:
        logger.warning("Failed to decode source audio for stem separation: %s", e)
        payload["stem_separation"] = {
            "enabled": True,
            "backend": settings.stem_separation_backend,
            "succeeded": False,
            "error": f"decode_failed: {e}",
        }
        return json.dumps(payload)

    # Phase 3/8: use advanced two-stage separation when flag is enabled
    if settings.feature_advanced_stem_separation_v2:
        try:
            from app.services.advanced_stem_separation import run_advanced_separation
            adv_result = run_advanced_separation(
                source_audio,
                loop_id=loop_id,
                source_key=source_key,
                # Use the preferred backend (e.g. demucs_htdemucs_6s); the pipeline
                # falls back automatically through the priority chain to builtin.
                backend=(settings.preferred_stem_backend or "builtin").strip().lower(),
            )
            if adv_result.succeeded:
                manifest = adv_result.to_manifest(loop_id)
                payload["stem_separation"] = {
                    "enabled": True,
                    "backend": adv_result.backend,
                    "succeeded": True,
                    "upload_mode": SOURCE_MODE_SINGLE_FILE,
                    "stems_generated": manifest.broad_roles,
                    "stem_s3_keys": manifest.stem_keys(),
                    "canonical_manifest": manifest.to_dict(),
                }
                return json.dumps(payload)
            # Advanced separation failed — fall through to legacy path
            logger.warning(
                "Advanced stem separation failed for loop_id=%s, falling back to legacy: %s",
                loop_id,
                adv_result.error,
            )
        except Exception as adv_exc:  # pragma: no cover — unexpected errors are non-fatal
            logger.warning(
                "Unexpected error in advanced stem separation for loop_id=%s: %s",
                loop_id,
                adv_exc,
                exc_info=True,
            )

    # Legacy path: broad 4-stem separation
    stem_result = separate_and_store_stems(
        source_audio=source_audio,
        loop_id=loop_id,
        source_key=source_key,
    )
    separation_dict = stem_result.to_dict()

    # Phase 5: always build a canonical manifest from the AI-separated stems,
    # even on the legacy path, so downstream consumers have a uniform object.
    if stem_result.succeeded and stem_result.stem_s3_keys:
        try:
            manifest = build_manifest_from_ai_separation(
                stem_result.stem_s3_keys,
                loop_id=loop_id,
            )
            separation_dict["canonical_manifest"] = manifest.to_dict()
            separation_dict["upload_mode"] = SOURCE_MODE_SINGLE_FILE
        except Exception as manifest_exc:
            logger.debug(
                "Canonical manifest generation failed for loop_id=%s: %s",
                loop_id,
                manifest_exc,
            )

    payload["stem_separation"] = separation_dict
    return json.dumps(payload)


def _build_uploaded_stem_analysis_json(existing_analysis: dict, *, stem_metadata: dict) -> str:
    payload = dict(existing_analysis or {})
    payload["stem_separation"] = stem_metadata
    return json.dumps(payload)


def _validate_detected_bar_range(analysis_result: dict) -> None:
    bars = analysis_result.get("bars")
    if bars is None:
        return
    try:
        bars_value = int(round(float(bars)))
    except Exception:
        return
    if bars_value < 4 or bars_value > 16:
        raise HTTPException(
            status_code=400,
            detail=f"Stem loop must be 4-16 bars. Detected: {bars_value} bars.",
        )


def _extract_detected_roles(stem_metadata: dict | None) -> list[str]:
    if not isinstance(stem_metadata, dict):
        return []
    roles = stem_metadata.get("roles_detected") or stem_metadata.get("stems_generated") or []
    return [str(role) for role in roles]


@router.post("/loops/upload", status_code=201)
async def upload_audio(file: UploadFile = File(...), request: Request = None, db: Session = Depends(get_db)):
    """Upload a WAV or MP3 audio file to S3.

    Routing assumptions (production):
    - File is written to S3 via ``loop_service.upload_loop_file`` which uses
      the configured storage backend (``S3`` in production, ``local`` in dev).
    - The returned ``file_key`` (e.g. ``uploads/<uuid>.wav``) is the stable
      permanent object key stored in the DB.  It never changes after upload.
    - ``file_url`` is an ephemeral access URL (presigned or local path) only
      used for the immediate response; the DB row stores only the ``file_key``.
    - Audio analysis (BPM, key, bars) is performed asynchronously after the
      file is stored; failures are non-fatal and the Loop row is still created.
    - Stem separation is kicked off in ``_build_stem_analysis_json`` when the
      ``FEATURE_STEM_SEPARATION`` flag is enabled; again non-fatal.

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
        correlation_id = getattr(request.state, "correlation_id", None) if request is not None else None
        log_feature_event(
            logger,
            event="upload_failure",
            correlation_id=correlation_id,
            reason="validation_failed",
            detail=error_msg,
            filename=safe_filename,
        )
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
        correlation_id = getattr(request.state, "correlation_id", None) if request is not None else None
        log_feature_event(
            logger,
            event="upload_failure",
            correlation_id=correlation_id,
            reason="storage_error",
            error=str(e),
            filename=safe_filename,
        )
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

        new_loop.analysis_json = _build_stem_analysis_json(
            analysis_result,
            source_content=content,
            source_filename=safe_filename,
            loop_id=new_loop.id,
            source_key=file_key,
        )
        db.commit()
        db.refresh(new_loop)

        logger.info(f"Loop uploaded: {new_loop.id} - {file_key}")
        correlation_id = getattr(request.state, "correlation_id", None) if request is not None else None
        # Single structured event covering both upload and loop creation for log aggregators.
        log_feature_event(
            logger,
            event="upload_success",
            correlation_id=correlation_id,
            loop_id=new_loop.id,
            file_key=file_key,
            bpm=new_loop.bpm,
            bars=new_loop.bars,
            key=new_loop.musical_key,
            duration_seconds=new_loop.duration_seconds,
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
        log_feature_event(
            logger,
            event="upload_failure",
            correlation_id=getattr(request.state, "correlation_id", None) if request is not None else None,
            reason="db_error",
            error=str(e),
            filename=safe_filename,
        )
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
    file: UploadFile | None = File(None),
    stem_files: List[UploadFile] | None = File(None),
    stem_zip: UploadFile | None = File(None),
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
    
    single_file_mode = file is not None
    multi_stem_mode = bool(stem_files)
    stem_zip_mode = stem_zip is not None

    if sum(bool(flag) for flag in (single_file_mode, multi_stem_mode, stem_zip_mode)) != 1:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one upload mode: file, stem_files, or stem_zip.",
        )

    analysis_result = {
        'bpm': None,
        'key': None,
        'duration': None,
        'bars': None
    }
    uploaded_stem_metadata: dict | None = None

    if single_file_mode:
        assert file is not None
        content = await file.read()
        safe_filename = loop_service.sanitize_filename(file.filename or "audio.wav")

        is_valid, error_msg = loop_service.validate_audio_file(
            filename=safe_filename,
            content_type=file.content_type or "audio/wav",
            file_size=len(content)
        )
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)

        try:
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
    else:
        try:
            if stem_zip_mode:
                assert stem_zip is not None
                zip_bytes = await stem_zip.read()
                ingest_result = ingest_stem_zip(zip_bytes)
                safe_filename = loop_service.sanitize_filename(stem_zip.filename or "stem_pack.zip")
            else:
                source_files: list[StemSourceFile] = []
                for stem_file in stem_files or []:
                    stem_content = await stem_file.read()
                    sanitized = loop_service.sanitize_filename(stem_file.filename or "stem.wav")
                    source_files.append(StemSourceFile(filename=sanitized, content=stem_content))
                ingest_result = ingest_stem_files(source_files)
                safe_filename = "stem_pack_mixdown.wav"

            mix_buffer = io.BytesIO()
            ingest_result.mixed_preview.export(mix_buffer, format="wav")
            content = mix_buffer.getvalue()
            file_key, file_url = loop_service.upload_loop_file(
                file_content=content,
                filename=safe_filename,
                content_type="audio/wav",
            )
            if not isinstance(file_url, str) or not file_url:
                file_url = f"/uploads/{file_key.split('/')[-1]}"

        except StemPackError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.exception("Failed to ingest stem pack")
            raise HTTPException(status_code=500, detail=f"Failed to process stem pack: {str(e)}")
    
    try:
        logger.info(f"Starting audio analysis for file_key: {file_key}")
        analysis_result = await loop_analyzer.analyze_from_s3(file_key)
        logger.info(f"Analysis complete: BPM={analysis_result.get('bpm')}, Key={analysis_result.get('key')}, Bars={analysis_result.get('bars')}, Duration={analysis_result.get('duration')}")
        if not single_file_mode:
            _validate_detected_bar_range(analysis_result)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
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

        if single_file_mode:
            loop.analysis_json = _build_stem_analysis_json(
                analysis_result,
                source_content=content,
                source_filename=safe_filename,
                loop_id=loop.id,
                source_key=file_key,
            )
        else:
            stem_keys = persist_role_stems(loop.id, ingest_result.role_stems)
            uploaded_stem_metadata = ingest_result.to_metadata(
                loop_id=loop.id,
                stem_s3_keys=stem_keys,
                bars=analysis_result.get("bars"),
            )
            can_use_stem_path = bool(
                uploaded_stem_metadata.get("enabled")
                and uploaded_stem_metadata.get("succeeded")
                and not uploaded_stem_metadata.get("fallback_to_loop", False)
            )
            loop.is_stem_pack = "true" if can_use_stem_path else "false"
            loop.stem_roles_json = json.dumps(stem_keys)
            loop.stem_files_json = json.dumps(
                {
                    role: {
                        "file_key": key,
                        "s3_key": key,
                        "duration_ms": ingest_result.duration_ms,
                        "source_files": ingest_result.role_sources.get(role, []),
                    }
                    for role, key in stem_keys.items()
                }
            )
            loop.stem_validation_json = json.dumps(
                {
                    "is_valid": can_use_stem_path,
                    "auto_aligned": bool((uploaded_stem_metadata.get("alignment") or {}).get("auto_aligned", False)),
                    "confidence": (uploaded_stem_metadata.get("alignment") or {}).get("confidence"),
                    "fallback_to_loop": bool(uploaded_stem_metadata.get("fallback_to_loop", False)),
                    "warnings": list(uploaded_stem_metadata.get("warnings") or []),
                }
            )
            loop.analysis_json = _build_uploaded_stem_analysis_json(
                analysis_result,
                stem_metadata=uploaded_stem_metadata,
            )

            # Phase 5: build and persist the canonical manifest for multi-stem / ZIP modes
            try:
                _src_type = SOURCE_ZIP_STEM if stem_zip_mode else SOURCE_UPLOADED_STEM
                _src_mode = SOURCE_MODE_ZIP_STEM if stem_zip_mode else SOURCE_MODE_MULTI_STEM
                canonical_manifest = build_manifest_from_uploaded_stems(
                    ingest_result,
                    loop_id=loop.id,
                    stem_s3_keys=stem_keys,
                    source_type=_src_type,
                    source_mode=_src_mode,
                )
                # Store the manifest as part of the analysis_json payload
                existing_payload = json.loads(loop.analysis_json or "{}")
                stem_sep = existing_payload.setdefault("stem_separation", {})
                stem_sep["canonical_manifest"] = canonical_manifest.to_dict()
                stem_sep["upload_mode"] = _src_mode
                loop.analysis_json = json.dumps(existing_payload)
            except Exception as manifest_exc:
                logger.debug(
                    "Canonical manifest generation failed for loop_id=%s: %s",
                    loop.id,
                    manifest_exc,
                )
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
            stem_roles=_extract_detected_roles(uploaded_stem_metadata or loop.stem_metadata),
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