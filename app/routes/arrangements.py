"""
Router for audio arrangement generation.

Handles creation, status tracking, and downloads of generated audio arrangements.
"""

import logging
import os
import tempfile
import json
import asyncio
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.config import settings
from app.db import get_db
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.schemas.arrangement import (
    AudioArrangementGenerateRequest,
    AudioArrangementGenerateResponse,
    ArrangementCreateRequest,
    ArrangementResponse,
)
from app.schemas.style_profile import StyleOverrides
from app.services.arrangement_jobs import run_arrangement_job
from app.services.audit_logging import log_feature_event
from app.services.style_service import style_service
from app.services.llm_style_parser import llm_style_parser
from app.services.rule_based_fallback import parse_with_rules

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
    "",
    response_model=list[ArrangementResponse],
    summary="List arrangements",
    description="List arrangements with optional loop_id filter.",
)
@router.get(
    "/",
    response_model=list[ArrangementResponse],
    include_in_schema=False,
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


def _map_style_params_to_overrides(style_params: dict | None) -> StyleOverrides | None:
    """
    PHASE 4: Map frontend style parameters to backend StyleOverrides.
    
    Frontend uses user-friendly names:
    - energy: Overall intensity/power (0=quiet, 1=loud)
    - darkness: Tonal darkness (0=bright, 1=dark)
    - bounce: Groove/drive (0=laid-back, 1=driving)
    - warmth: Melodic warmth (0=cold, 1=warm)
    - texture: String value 'smooth'/'balanced'/'gritty'
    
    Backend StyleOverrides uses audio engineering terms:
    - aggression: Maps from frontend 'energy'
    - darkness: Direct match
    - bounce: Direct match
    - melody_complexity: Maps from frontend 'warmth'
    - fx_density: Derived from 'texture' (smooth=0.3, balanced=0.5, gritty=0.8)
    """
    if not style_params:
        return None
    
    # Build StyleOverrides from frontend parameters
    overrides_dict = {}
    
    # Direct mappings
    if 'energy' in style_params:
        overrides_dict['aggression'] = float(style_params['energy'])
    
    if 'darkness' in style_params:
        overrides_dict['darkness'] = float(style_params['darkness'])
    
    if 'bounce' in style_params:
        overrides_dict['bounce'] = float(style_params['bounce'])
    
    if 'warmth' in style_params:
        overrides_dict['melody_complexity'] = float(style_params['warmth'])
    
    # Map texture string to fx_density numeric value
    if 'texture' in style_params:
        texture = style_params['texture']
        texture_to_fx = {
            'smooth': 0.3,    # Minimal effects, clean sound
            'balanced': 0.5,  # Moderate effects
            'gritty': 0.8,    # Heavy effects, distortion
        }
        overrides_dict['fx_density'] = texture_to_fx.get(texture, 0.5)
    
    # Return None if no valid mappings found
    if not overrides_dict:
        return None
    
    return StyleOverrides(**overrides_dict)


@router.post(
    "/generate",
    response_model=AudioArrangementGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate an audio arrangement",
    description="Submit a request to generate a full audio arrangement from a loop. "
    "The arrangement will be generated asynchronously. Use the returned arrangement_id "
    "to poll status or download the result.",
)
async def generate_arrangement(
    request: AudioArrangementGenerateRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    db: Session = Depends(get_db),
):
    """
    Generate an audio arrangement from an uploaded loop.

    - **loop_id**: ID of the source loop to arrange
    - **target_seconds**: Desired duration (10-3600 seconds)
    - **genre**: Optional genre hint
    - **intensity**: Optional intensity level (low/medium/high)
    - **include_stems**: Whether to generate separate stems
    - **style_text_input**: V2 - Natural language style description
    - **use_ai_parsing**: V2 - Enable LLM parsing of style_text_input

    Returns immediately with arrangement_id. Check status endpoint for progress.
    """
    # Validate that loop exists
    loop = db.query(Loop).filter(Loop.id == request.loop_id).first()
    if not loop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Loop with ID {request.loop_id} not found",
        )

    if settings.get_storage_backend() == "local":
        if not loop.file_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Loop {request.loop_id} has no source file key. "
                    "Please re-upload the loop before generating."
                ),
            )

        local_filename = loop.file_key.split("/")[-1]
        local_path = Path("uploads") / local_filename
        if not local_path.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Loop source file is missing in local storage ({local_filename}). "
                    "Please re-upload the loop and try again."
                ),
            )

    style_preset = None
    structure_json = None
    seed_used = None
    structure_preview = []
    style_profile_json = None
    ai_parsing_used = False
    correlation_id = getattr(http_request.state, "correlation_id", None) or http_request.headers.get("x-correlation-id")

    # V2: Handle LLM-based style parsing
    if request.use_ai_parsing and request.style_text_input:
        try:
            logger.info(f"Parsing style text: {request.style_text_input}")
            loop_metadata = {
                "bpm": float(loop.bpm or loop.tempo or 120.0),
                "key": loop.key or "C",
                "duration": request.target_seconds,
                "bars": int(loop.bars or 4),
            }
            
            # PHASE 4: Map frontend style_params to backend StyleOverrides
            style_overrides = _map_style_params_to_overrides(request.style_params)
            if style_overrides:
                logger.info(f"Applying style overrides from sliders: {style_overrides.model_dump(exclude_none=True)}")
            
            # Parse style intent using LLM with optional slider overrides
            style_profile = await llm_style_parser.parse_style_intent(
                user_input=request.style_text_input,
                loop_metadata=loop_metadata,
                overrides=style_overrides,
            )
            
            # Serialize StyleProfile to JSON
            style_profile_json = style_profile.model_dump_json()
            ai_parsing_used = True
            style_preset = style_profile.resolved_preset
            seed_used = style_profile.seed
            
            # Extract section structure for preview
            structure_preview = style_profile.sections
            structure_json = json.dumps({
                "seed": seed_used,
                "sections": structure_preview,
                "correlation_id": correlation_id,
            })
            
            logger.info(f"Style profile parsed: preset={style_preset}, confidence={style_profile.intent.confidence}")
        except Exception as llm_error:
            logger.warning(f"LLM style parsing failed: {llm_error}")
            # Fall through to preset-based or default handling

    # V1: Handle preset-based style configuration (fallback)
    elif settings.feature_style_engine and request.style_preset:
        try:
            bpm_for_plan = float(loop.bpm or loop.tempo or 120.0)
            loop_bars = int(loop.bars or 4)
            style_preview = style_service.preview_structure(
                style_preset=request.style_preset,
                target_seconds=request.target_seconds,
                bpm=bpm_for_plan,
                loop_bars=loop_bars,
                seed=request.seed,
            )
            style_preset = style_preview.get("style_preset")
            seed_used = style_preview.get("seed_used")
            structure_preview = style_preview.get("sections", [])
            # Wrap structure and seed for serialization
            structure_json = json.dumps({
                "seed": seed_used,
                "sections": structure_preview,
                "correlation_id": correlation_id,
            })
        except Exception as style_error:
            logger.warning("Style preview generation skipped: %s", style_error)

    # Create arrangement record
    arrangement = Arrangement(
        loop_id=request.loop_id,
        status="queued",
        target_seconds=request.target_seconds,
        genre=request.genre,
        intensity=request.intensity,
        include_stems=request.include_stems,
        arrangement_json=structure_json,
        style_profile_json=style_profile_json,
        ai_parsing_used=ai_parsing_used,
    )
    db.add(arrangement)
    db.commit()
    db.refresh(arrangement)

    log_feature_event(
        logger,
        event="arrangement_created",
        correlation_id=correlation_id,
        arrangement_id=arrangement.id,
        loop_id=arrangement.loop_id,
        sections_count=len(structure_preview or []),
        ai_parsing_used=ai_parsing_used,
    )

    # Schedule background job
    background_tasks.add_task(run_arrangement_job, arrangement.id)

    log_feature_event(
        logger,
        event="response_returned",
        correlation_id=correlation_id,
        route="/api/v1/arrangements/generate",
        arrangement_id=arrangement.id,
        status_code=202,
    )

    return AudioArrangementGenerateResponse(
        arrangement_id=arrangement.id,
        loop_id=arrangement.loop_id,
        status=arrangement.status,
        created_at=arrangement.created_at,
        render_job_ids=[],
        seed_used=seed_used,
        style_preset=style_preset,
        style_profile=json.loads(style_profile_json) if style_profile_json else None,
        structure_preview=structure_preview,
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
    response_class=FileResponse,
    summary="Download generated arrangement",
    description="Download the generated audio file. Returns FileResponse for Swagger UI requests and StreamingResponse for normal browser requests. Returns 409 if not yet complete.",
)
def download_arrangement(
    arrangement_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Download the generated audio arrangement.

    Returns 409 Conflict if the arrangement is still being processed.
    Returns 404 if the arrangement doesn't exist.
    Returns file download response if done.
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
            detail="Arrangement is complete but output file key is missing",
        )

    storage_backend = settings.get_storage_backend()
    output_key_filename = arrangement.output_s3_key.rsplit("/", maxsplit=1)[-1]
    download_filename = output_key_filename or f"arrangement_{arrangement_id}.wav"
    content_type = "audio/wav"

    headers = {
        "Content-Disposition": f'attachment; filename="{download_filename}"',
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Disposition",
    }

    referer = request.headers.get("referer", "")
    is_swagger_request = "/docs" in referer or "/redoc" in referer

    if storage_backend == "local":
        local_filename = arrangement.output_s3_key.split("/")[-1]
        local_path = Path("uploads") / local_filename
        if not local_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Arrangement file not found in local storage",
            )

        if is_swagger_request:
            return FileResponse(
                path=str(local_path),
                media_type=content_type,
                filename=download_filename,
                headers=headers,
            )

        def iter_local_stream():
            with open(local_path, "rb") as local_file:
                while True:
                    chunk = local_file.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            iter_local_stream(),
            media_type=content_type,
            headers=headers,
        )

    if storage_backend != "s3":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid STORAGE_BACKEND: {storage_backend}",
        )

    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_region = os.getenv("AWS_REGION")
    s3_bucket = os.getenv("AWS_S3_BUCKET")

    missing_vars = []
    if not aws_access_key_id:
        missing_vars.append("AWS_ACCESS_KEY_ID")
    if not aws_secret_access_key:
        missing_vars.append("AWS_SECRET_ACCESS_KEY")
    if not aws_region:
        missing_vars.append("AWS_REGION")
    if not s3_bucket:
        missing_vars.append("AWS_S3_BUCKET")

    if missing_vars:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"S3 is not configured. Missing environment variables: {', '.join(missing_vars)}",
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

    content_type = s3_object.get("ContentType") or content_type
    body = s3_object["Body"]

    if is_swagger_request:
        suffix = os.path.splitext(download_filename)[1] or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            for chunk in body.iter_chunks(chunk_size=1024 * 1024):
                if chunk:
                    temp_file.write(chunk)
            temp_path = temp_file.name
        body.close()
        return FileResponse(
            path=temp_path,
            media_type=content_type,
            filename=download_filename,
            headers=headers,
            background=BackgroundTask(lambda: os.remove(temp_path) if os.path.exists(temp_path) else None),
        )

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
