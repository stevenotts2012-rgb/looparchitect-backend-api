"""
Router for audio arrangement generation.

Handles creation, status tracking, and downloads of generated audio arrangements.
"""

import logging
import os
import tempfile
import json
import asyncio
import io
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from pydub import AudioSegment

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
from app.services.audit_logging import log_feature_event
from app.services.job_service import create_render_job
from app.queue import DEFAULT_RENDER_QUEUE_NAME, is_redis_available
from app.services.style_service import style_service
from app.services.llm_style_parser import llm_style_parser
from app.services.rule_based_fallback import parse_with_rules
from app.services.producer_engine import ProducerEngine
from app.services.loop_metadata_analyzer import LoopMetadataAnalyzer
from app.services.style_direction_engine import StyleDirectionEngine
from app.services.render_plan import RenderPlanGenerator
from app.services.arrangement_validator import ArrangementValidator
from app.services.daw_export import DAWExporter
from app.services.storage import storage

logger = logging.getLogger(__name__)

router = APIRouter()


def _ensure_arrangements_schema(db: Session) -> None:
    """Best-effort schema reconciliation for deployments with stale arrangement columns."""
    try:
        import sqlalchemy as sa
        from sqlalchemy import text

        bind = db.get_bind()
        inspector = sa.inspect(bind)
        if "arrangements" not in inspector.get_table_names():
            return

        existing_columns = {col["name"] for col in inspector.get_columns("arrangements")}
        required_columns = {
            "style_profile_json": "TEXT",
            "ai_parsing_used": "BOOLEAN DEFAULT false",
            "producer_arrangement_json": "TEXT",
            "render_plan_json": "TEXT",
            "progress": "FLOAT DEFAULT 0.0",
            "progress_message": "VARCHAR(256)",
            "output_s3_key": "VARCHAR",
            "output_url": "VARCHAR",
            "stems_zip_url": "VARCHAR",
        }

        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                db.execute(text(f"ALTER TABLE arrangements ADD COLUMN {column_name} {column_type}"))
                logger.info("Added missing arrangements.%s column on-demand", column_name)

        db.flush()
    except Exception:
        logger.warning("Could not auto-reconcile arrangements schema on request path", exc_info=True)


def _extract_sections_for_export(arrangement: Arrangement) -> list[dict]:
    sections: list[dict] = []

    if arrangement.producer_arrangement_json:
        try:
            producer_payload = json.loads(arrangement.producer_arrangement_json)
            for section in producer_payload.get("sections", []):
                sections.append(
                    {
                        "name": section.get("name") or section.get("type") or "Section",
                        "bar_start": int(section.get("bar_start", section.get("start_bar", 0))),
                        "bars": int(section.get("bars", 1)),
                    }
                )
        except Exception:
            logger.warning("Failed to parse producer_arrangement_json for arrangement %s", arrangement.id, exc_info=True)

    if not sections and arrangement.render_plan_json:
        try:
            render_plan = json.loads(arrangement.render_plan_json)
            for section in render_plan.get("sections", []):
                sections.append(
                    {
                        "name": section.get("name", "Section"),
                        "bar_start": int(section.get("start_bar", section.get("bar_start", 0))),
                        "bars": int(section.get("bars", 1)),
                    }
                )
        except Exception:
            logger.warning("Failed to parse render_plan_json for arrangement %s", arrangement.id, exc_info=True)

    if not sections:
        sections = [{"name": "Full Arrangement", "bar_start": 0, "bars": 1}]

    return sections


def _load_output_audio_segment(arrangement: Arrangement) -> AudioSegment:
    if not arrangement.output_s3_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arrangement output key missing. Cannot generate DAW export.",
        )

    storage_backend = settings.get_storage_backend()

    if storage_backend == "local":
        local_filename = arrangement.output_s3_key.split("/")[-1]
        local_path = Path("uploads") / local_filename
        if not local_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rendered arrangement file not found in local storage.",
            )
        return AudioSegment.from_wav(str(local_path))

    if storage_backend != "s3":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid STORAGE_BACKEND: {storage_backend}",
        )

    bucket_name = settings.get_s3_bucket()
    if not bucket_name:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="S3 bucket is not configured.",
        )

    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        response = s3_client.get_object(Bucket=bucket_name, Key=arrangement.output_s3_key)
        file_bytes = response["Body"].read()
        if not file_bytes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Rendered arrangement file is empty in storage.",
            )
        return AudioSegment.from_wav(io.BytesIO(file_bytes))
    except ClientError as exc:
        logger.exception("Failed to fetch rendered arrangement from S3")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to load rendered arrangement from S3: {exc}",
        )


def _collect_existing_midi_artifacts(arrangement_id: int) -> dict[str, bytes]:
    """Collect real MIDI artifacts if they already exist. No placeholder MIDI is generated."""
    midi_artifacts: dict[str, bytes] = {}
    local_uploads = Path("uploads")
    if not local_uploads.exists():
        return midi_artifacts

    possible_names = [
        f"arrangement_{arrangement_id}_drums.mid",
        f"arrangement_{arrangement_id}_bass.mid",
        f"arrangement_{arrangement_id}_melody.mid",
        f"arrangement_{arrangement_id}.mid",
    ]
    for filename in possible_names:
        candidate = local_uploads / filename
        if candidate.exists() and candidate.stat().st_size > 0:
            midi_artifacts[filename] = candidate.read_bytes()

    return midi_artifacts


def _generate_producer_arrangement(
    loop_id: int,
    tempo: float,
    target_seconds: float,
    style_text_input: str | None = None,
    genre: str | None = None,
):
    """
    Helper: Generate a ProducerArrangement for a given loop.
    
    This bridges style direction input to the producer engine.
    """
    # Determine genre from style input or explicit parameter
    determined_genre = genre or "generic"
    style_profile = None
    
    if style_text_input:
        # Parse natural language style direction
        from app.services.producer_models import StyleProfile
        style_profile = StyleDirectionEngine.parse(style_text_input)
        determined_genre = style_profile.genre
        logger.info(f"Style direction parsed: {determined_genre} @ {style_profile.bpm_range[0]}-{style_profile.bpm_range[1]} BPM")
    
    # Generate producer arrangement
    arrangement = ProducerEngine.generate(
        target_seconds=target_seconds,
        tempo=tempo,
        genre=determined_genre,
        style_profile=style_profile,
        structure_template="standard",
    )
    
    # Validate arrangement
    ArrangementValidator.validate_and_raise(arrangement)
    
    return arrangement


@router.post(
    "/",
    response_model=ArrangementResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an arrangement job",
    description="Create an arrangement job and process it asynchronously.",
)
def create_arrangement(
    request: ArrangementCreateRequest,
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

    if not is_redis_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background job queue is unavailable. Redis service may be offline.",
        )

    db.add(arrangement)
    db.commit()
    db.refresh(arrangement)

    enqueue_params = {
        "length_seconds": int(request.target_duration_seconds or 180),
        "arrangement_id": arrangement.id,
    }

    try:
        create_render_job(db, arrangement.loop_id, enqueue_params)
    except ValueError as enqueue_error:
        arrangement.status = "failed"
        arrangement.progress = 0.0
        arrangement.progress_message = "Queue enqueue validation failed"
        arrangement.error_message = f"Enqueue validation failed: {enqueue_error}"
        db.commit()
        db.refresh(arrangement)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue arrangement job: {enqueue_error}",
        )
    except RuntimeError as enqueue_error:
        arrangement.status = "failed"
        arrangement.progress = 0.0
        arrangement.progress_message = "Queue unavailable"
        arrangement.error_message = f"Queue enqueue failed: {enqueue_error}"
        db.commit()
        db.refresh(arrangement)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Background queue unavailable: {enqueue_error}",
        )

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

    if not is_redis_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background job queue is unavailable. Redis service may be offline.",
        )

    bpm_for_duration = float(loop.bpm or loop.tempo or 120.0)
    effective_target_seconds = request.target_seconds
    if request.bars is not None:
        effective_target_seconds = max(10, int(round((request.bars * 4 * 60.0) / bpm_for_duration)))
        logger.info(
            "Using bars override for arrangement generation: bars=%s bpm=%.2f target_seconds=%s",
            request.bars,
            bpm_for_duration,
            effective_target_seconds,
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
    producer_arrangement_json = None
    correlation_id = getattr(http_request.state, "correlation_id", None) or http_request.headers.get("x-correlation-id")

    effective_style_text = (request.style_text_input or "").strip()
    if request.producer_moves:
        moves_text = ", ".join(move for move in request.producer_moves if move)
        if moves_text:
            effective_style_text = f"{effective_style_text}; producer moves: {moves_text}" if effective_style_text else f"producer moves: {moves_text}"

    # V2: Handle LLM-based style parsing
    if request.use_ai_parsing and effective_style_text:
        try:
            logger.info(f"Parsing style text: {effective_style_text}")
            loop_metadata = {
                "bpm": float(loop.bpm or loop.tempo or 120.0),
                "key": loop.key or "C",
                "duration": effective_target_seconds,
                "bars": int(loop.bars or 4),
            }
            
            # PHASE 4: Map frontend style_params to backend StyleOverrides
            style_overrides = _map_style_params_to_overrides(request.style_params)
            if style_overrides:
                logger.info(f"Applying style overrides from sliders: {style_overrides.model_dump(exclude_none=True)}")
            
            # Parse style intent using LLM with optional slider overrides
            style_profile = await llm_style_parser.parse_style_intent(
                user_input=effective_style_text,
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
            
            # PRODUCER ENGINE INTEGRATION: Generate professional arrangement if feature enabled
            logger.info(f"DEBUG: settings.feature_producer_engine = {settings.feature_producer_engine}")
            if settings.feature_producer_engine:
                try:
                    # Extract genre from resolved preset (archetype)
                    genre_for_producer = style_profile.resolved_preset or style_profile.intent.archetype.split('_')[0] or "generic"
                    logger.info(f"ProducerEngine enabled - generating arrangement for genre: {genre_for_producer}")
                    
                    # Call ProducerEngine with style profile
                    producer_arrangement = ProducerEngine.generate(
                        target_seconds=effective_target_seconds,
                        tempo=float(loop.bpm or loop.tempo or 120.0),
                        genre=genre_for_producer,
                        style_profile=style_profile,
                        structure_template="standard",
                    )
                    
                    # Import asdict for dataclass serialization
                    from dataclasses import asdict
                    
                    # Serialize the producer arrangement for storage
                    producer_arrangement_json = json.dumps({
                        "version": "2.0",
                        "producer_arrangement": asdict(producer_arrangement),
                        "correlation_id": correlation_id,
                    }, default=str)
                    
                    logger.info(f"ProducerEngine arrangement generated with {len(producer_arrangement.sections)} sections")
                    logger.info(f"producer_arrangement_json set to: {len(producer_arrangement_json) if producer_arrangement_json else 0} bytes")
                except Exception as producer_error:
                    logger.warning(f"ProducerEngine generation failed: {producer_error}", exc_info=True)
                    # Continue with fallback - producer_arrangement_json stays None
            else:
                logger.warning(f"ProducerEngine NOT enabled - feature flag is {settings.feature_producer_engine}")
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
                target_seconds=effective_target_seconds,
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

    # METADATA ANALYZER INTEGRATION: Auto-detect genre/mood if not already determined
    # This runs when ProducerEngine is enabled but no genre/style was parsed from AI or preset
    if settings.feature_producer_engine and not ai_parsing_used and not request.genre:
        try:
            logger.info("Auto-detecting genre/mood from loop metadata for ProducerEngine")
            
            # Extract tags from loop if available
            tags = []
            if hasattr(loop, 'tags') and loop.tags:
                if isinstance(loop.tags, str):
                    tags = [t.strip() for t in loop.tags.split(',')]
                elif isinstance(loop.tags, list):
                    tags = loop.tags
            
            # Analyze loop metadata
            metadata_analysis = LoopMetadataAnalyzer.analyze(
                bpm=loop.bpm or loop.tempo,
                tags=tags,
                filename=loop.filename,
                mood_keywords=[],
                genre_hint=request.genre,
                bars=loop.bars,
                musical_key=loop.musical_key,
            )
            
            detected_genre = metadata_analysis["detected_genre"]
            detected_mood = metadata_analysis["detected_mood"]
            energy_level = metadata_analysis["energy_level"]
            confidence = metadata_analysis["confidence"]
            
            logger.info(
                f"Metadata analysis complete: genre={detected_genre}, mood={detected_mood}, "
                f"energy={energy_level:.2f}, confidence={confidence:.2f}"
            )
            
            # Generate ProducerArrangement using detected genre/mood
            if confidence >= 0.4:  # Minimum confidence threshold
                try:
                    logger.info(f"Generating ProducerArrangement with detected genre: {detected_genre}")
                    
                    # Build style profile from metadata analysis
                    from app.schemas.style_profile import StyleProfile, StyleIntent, StyleParameters
                    
                    auto_style_profile = StyleProfile(
                        intent=StyleIntent(
                            raw=f"Auto-detected {detected_genre} with {detected_mood} mood",
                            archetype=detected_genre,
                            energy=energy_level,
                            mood=detected_mood,
                            confidence=confidence,
                        ),
                        parameters=StyleParameters(
                            aggression=energy_level,
                            darkness=0.7 if detected_mood == "dark" else 0.3,
                            bounce=energy_level,
                            melody_complexity=0.6 if "melodic" in detected_genre else 0.4,
                            fx_density=0.5,
                        ),
                        resolved_preset=detected_genre,
                        sections=[],  # Will be generated by ProducerEngine
                        seed=None,
                    )
                    
                    # Generate producer arrangement
                    producer_arrangement = ProducerEngine.generate(
                        target_seconds=effective_target_seconds,
                        tempo=float(loop.bpm or loop.tempo or 120.0),
                        genre=detected_genre,
                        style_profile=auto_style_profile,
                        structure_template=metadata_analysis["recommended_template"],
                    )
                    
                    # Serialize producer arrangement
                    from dataclasses import asdict
                    producer_arrangement_json = json.dumps({
                        "version": "2.0",
                        "producer_arrangement": asdict(producer_arrangement),
                        "metadata_analysis": metadata_analysis,
                        "auto_detected": True,
                        "correlation_id": correlation_id,
                    }, default=str)
                    
                    # Also store style profile for tracking
                    style_profile_json = auto_style_profile.model_dump_json()
                    ai_parsing_used = False  # Mark as metadata-based, not AI-based
                    
                    logger.info(
                        f"ProducerArrangement auto-generated from metadata with {len(producer_arrangement.sections)} sections"
                    )
                except Exception as producer_error:
                    logger.warning(f"ProducerEngine generation from metadata failed: {producer_error}", exc_info=True)
            else:
                logger.warning(f"Metadata analysis confidence too low ({confidence:.2f}), skipping auto-generation")
                
        except Exception as metadata_error:
            logger.warning(f"Metadata analysis failed: {metadata_error}", exc_info=True)
            # Continue without metadata-based generation

    # Create arrangement record
    _ensure_arrangements_schema(db)
    logger.info(f"DEBUG-SAVE: Creating arrangement with: ai_parsing_used={ai_parsing_used}, has_producer_json={producer_arrangement_json is not None}, json_len={len(producer_arrangement_json) if producer_arrangement_json else 0}")
    arrangement = Arrangement(
        loop_id=request.loop_id,
        status="queued",
        target_seconds=effective_target_seconds,
        genre=request.genre,
        intensity=request.intensity,
        include_stems=request.include_stems,
        arrangement_json=structure_json,
        style_profile_json=style_profile_json,
        ai_parsing_used=ai_parsing_used,
        producer_arrangement_json=producer_arrangement_json,
    )
    db.add(arrangement)
    try:
        db.commit()
    except Exception as commit_error:
        db.rollback()
        logger.exception("Failed to create arrangement row")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create arrangement record: {str(commit_error)}",
        )
    db.refresh(arrangement)

    logger.info(
        "Arrangement created: arrangement_id=%s loop_id=%s status=%s",
        arrangement.id,
        arrangement.loop_id,
        arrangement.status,
    )

    log_feature_event(
        logger,
        event="arrangement_created",
        correlation_id=correlation_id,
        arrangement_id=arrangement.id,
        loop_id=arrangement.loop_id,
        sections_count=len(structure_preview or []),
        ai_parsing_used=ai_parsing_used,
    )

    enqueue_params = {
        "genre": request.genre,
        "length_seconds": effective_target_seconds,
        "energy": request.intensity,
        "variations": int(request.variation_count or 1),
        "variation_styles": [],
        "custom_style": effective_style_text or request.style_preset,
        "arrangement_id": arrangement.id,
        "correlation_id": correlation_id,
    }
    try:
        job, _ = create_render_job(db, arrangement.loop_id, enqueue_params)
    except ValueError as enqueue_error:
        try:
            arrangement.status = "failed"
            arrangement.progress = 0.0
            arrangement.progress_message = "Queue enqueue validation failed"
            arrangement.error_message = f"Enqueue validation failed: {enqueue_error}"
            db.commit()
            db.refresh(arrangement)
        except Exception:
            db.rollback()
            logger.exception("Failed to mark arrangement as failed after enqueue validation error")
        logger.exception("Failed to enqueue arrangement job for arrangement_id=%s", arrangement.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue arrangement job: {enqueue_error}",
        )
    except RuntimeError as enqueue_error:
        try:
            arrangement.status = "failed"
            arrangement.progress = 0.0
            arrangement.progress_message = "Queue unavailable"
            arrangement.error_message = f"Queue enqueue failed: {enqueue_error}"
            db.commit()
            db.refresh(arrangement)
        except Exception:
            db.rollback()
            logger.exception("Failed to mark arrangement as failed after queue outage")
        logger.exception("Queue unavailable while enqueuing arrangement_id=%s", arrangement.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Background queue unavailable: {enqueue_error}",
        )

    logger.info(
        "Arrangement job enqueued: arrangement_id=%s job_id=%s queue_name=%s",
        arrangement.id,
        job.id,
        DEFAULT_RENDER_QUEUE_NAME,
    )

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
        render_job_ids=[job.id],
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

@router.get(
    "/{arrangement_id}/metadata",
    summary="Get arrangement metadata (producer structure)",
    description="Get detailed arrangement metadata including producer arrangement and render plan.",
)
def get_arrangement_metadata(
    arrangement_id: int,
    db: Session = Depends(get_db),
):
    """
    Get detailed arrangement metadata.
    
    Returns:
    - producer_arrangement: ProducerArrangement structure (if available)
    - render_plan: Render plan with events (if available)
    - validation_summary: Validation results
    - daw_export_info: DAW export package information
    """
    arrangement = db.query(Arrangement).filter(Arrangement.id == arrangement_id).first()
    if not arrangement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arrangement {arrangement_id} not found",
        )
    
    metadata = {
        "arrangement_id": arrangement.id,
        "loop_id": arrangement.loop_id,
        "status": arrangement.status,
        "target_seconds": arrangement.target_seconds,
        "created_at": arrangement.created_at.isoformat() if arrangement.created_at else None,
        "updated_at": arrangement.updated_at.isoformat() if arrangement.updated_at else None,
    }
    
    # Include producer arrangement if available
    if arrangement.producer_arrangement_json:
        try:
            metadata["producer_arrangement"] = json.loads(arrangement.producer_arrangement_json)
        except json.JSONDecodeError:
            logger.warning(f"Failed to decode producer_arrangement_json for arrangement {arrangement_id}")
    
    # Include render plan if available
    if arrangement.render_plan_json:
        try:
            metadata["render_plan"] = json.loads(arrangement.render_plan_json)
        except json.JSONDecodeError:
            logger.warning(f"Failed to decode render_plan_json for arrangement {arrangement_id}")
    
    return metadata


@router.get(
    "/{arrangement_id}/daw-export",
    summary="Get DAW export package info",
    description="Get information about the DAW export package (stems, MIDI, metadata).",
)
def get_daw_export_info(
    arrangement_id: int,
    db: Session = Depends(get_db),
):
    """
    Get DAW export package information.
    
    Returns details about:
    - Supported DAWs (FL Studio, Ableton, Logic, etc.)
    - Stems included (kick, snare, bass, melody, etc.)
    - MIDI files (drums, bass, melody)
    - Metadata files (markers, tempo map, README)
    """
    arrangement = db.query(Arrangement).filter(Arrangement.id == arrangement_id).first()
    if not arrangement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arrangement {arrangement_id} not found",
        )
    
    _ensure_arrangements_schema(db)

    if arrangement.status != "done":
        return {
            "arrangement_id": arrangement.id,
            "ready_for_export": False,
            "status": arrangement.status,
            "message": "Arrangement must be done before DAW export can be generated.",
        }

    export_key = f"exports/{arrangement.id}.zip"
    if not storage.file_exists(export_key):
        full_mix_audio = _load_output_audio_segment(arrangement)
        loop = db.query(Loop).filter(Loop.id == arrangement.loop_id).first()
        tempo = float(loop.bpm) if loop and loop.bpm else 120.0
        musical_key = loop.musical_key if loop and loop.musical_key else "C"
        sections = _extract_sections_for_export(arrangement)
        midi_artifacts = _collect_existing_midi_artifacts(arrangement.id)

        zip_bytes, contents = DAWExporter.build_export_zip(
            arrangement_id=arrangement.id,
            full_mix=full_mix_audio,
            bpm=tempo,
            musical_key=musical_key,
            sections=sections,
            midi_files=midi_artifacts,
        )

        storage.upload_file(
            file_bytes=zip_bytes,
            content_type="application/zip",
            key=export_key,
        )
        arrangement.stems_zip_url = f"/api/v1/arrangements/{arrangement.id}/daw-export/download"
        db.commit()
        db.refresh(arrangement)
    else:
        sections = _extract_sections_for_export(arrangement)
        contents = {
            "stems": [
                "stems/kick.wav",
                "stems/bass.wav",
                "stems/snare.wav",
                "stems/hats.wav",
                "stems/melody.wav",
                "stems/pads.wav",
            ],
            "midi": [],
            "metadata": ["markers.csv", "tempo_map.json", "README.txt"],
        }

    if not arrangement.stems_zip_url:
        arrangement.stems_zip_url = f"/api/v1/arrangements/{arrangement.id}/daw-export/download"
        db.commit()
        db.refresh(arrangement)

    download_url = arrangement.stems_zip_url or f"/api/v1/arrangements/{arrangement.id}/daw-export/download"

    return {
        "arrangement_id": arrangement.id,
        "ready_for_export": True,
        "supported_daws": DAWExporter.SUPPORTED_DAWS,
        "download_url": download_url,
        "export_s3_key": export_key,
        "contents": contents,
        "sections": sections,
        "midi_note": "MIDI files are included only when real MIDI artifacts are present.",
    }


@router.get(
    "/{arrangement_id}/daw-export/download",
    summary="Download DAW export ZIP",
    description="Download the generated DAW export ZIP artifact for an arrangement.",
)
def download_daw_export(
    arrangement_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    arrangement = db.query(Arrangement).filter(Arrangement.id == arrangement_id).first()
    if not arrangement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arrangement {arrangement_id} not found",
        )

    export_key = f"exports/{arrangement.id}.zip"
    if not storage.file_exists(export_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DAW export ZIP has not been generated yet.",
        )

    storage_backend = settings.get_storage_backend()
    download_filename = f"arrangement_{arrangement_id}_daw_export.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{download_filename}"',
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Disposition",
    }

    referer = request.headers.get("referer", "")
    is_swagger_request = "/docs" in referer or "/redoc" in referer

    if storage_backend == "local":
        local_filename = export_key.split("/")[-1]
        local_path = Path("uploads") / local_filename
        if not local_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="DAW export file not found in local storage",
            )

        if is_swagger_request:
            return FileResponse(
                path=str(local_path),
                media_type="application/zip",
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
            media_type="application/zip",
            headers=headers,
        )

    if storage_backend != "s3":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid STORAGE_BACKEND: {storage_backend}",
        )

    if not settings.get_s3_bucket():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="S3 bucket is not configured",
        )

    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )

        s3_object = s3_client.get_object(Bucket=settings.get_s3_bucket(), Key=export_key)
        body = s3_object["Body"]

        if is_swagger_request:
            suffix = os.path.splitext(download_filename)[1] or ".zip"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(body.read())
                temp_path = temp_file.name
            return FileResponse(
                path=temp_path,
                media_type="application/zip",
                filename=download_filename,
                headers=headers,
                background=BackgroundTask(lambda path=temp_path: Path(path).unlink(missing_ok=True)),
            )

        return StreamingResponse(
            body.iter_chunks(chunk_size=1024 * 1024),
            media_type="application/zip",
            headers=headers,
        )
    except ClientError as exc:
        logger.exception("Failed to download DAW export %s from S3", arrangement_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Failed to download DAW export from S3: {exc}",
        )