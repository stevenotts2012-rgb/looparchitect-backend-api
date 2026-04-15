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
import threading
from dataclasses import asdict as dataclass_asdict
from pathlib import Path
from datetime import datetime, timedelta

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
from app.models.job import RenderJob
from app.models.loop import Loop
from app.schemas.arrangement import (
    AudioArrangementGenerateRequest,
    AudioArrangementGenerateResponse,
    ArrangementPreviewCandidate,
    ArrangementCreateRequest,
    ArrangementResponse,
    ArrangementPlan,
    ArrangementPlanRequest,
    ArrangementPlanResponse,
)
from app.schemas.style_profile import StyleOverrides
from app.services.audit_logging import log_feature_event
from app.services.job_service import create_render_job
from app.queue import DEFAULT_RENDER_QUEUE_NAME, get_queue, is_redis_available
from app.services.style_service import style_service
from app.services.llm_style_parser import llm_style_parser
from app.services.rule_based_fallback import parse_with_rules
from app.services.producer_engine import ProducerEngine
from app.services.loop_metadata_analyzer import LoopMetadataAnalyzer
from app.services.style_direction_engine import StyleDirectionEngine
from app.services.render_plan import RenderPlanGenerator
from app.services.arrangement_validator import ArrangementValidator
from app.services.daw_export import DAWExporter
from app.services.storage import storage, S3StorageError
from app.services.arrangement_planner import (
    arrangement_planner_service,
    validate_arrangement_plan,
    plan_to_producer_arrangement,
)
from app.services.producer_plan_builder import ProducerPlanBuilderV2
from app.services.producer_rules_engine import ProducerRulesEngine
from app.services.render_qa import RenderQAService
from app.schemas.arrangement import (
    ProducerPlanV2,
    ProducerSectionSummaryItem,
    ProducerDecisionLogEntry,
    QualityScoreSchema,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _sync_arrangement_status_from_job(db: Session, arrangement: Arrangement) -> Arrangement:
    """Best-effort sync of arrangement status from its linked render job record."""
    now_utc = datetime.utcnow()
    processing_timeout_seconds = max(60, int(settings.render_job_timeout_seconds or 900))

    try:
        linked_job = (
            db.query(RenderJob)
            .filter(RenderJob.params_json.like(f'%"arrangement_id": {arrangement.id}%'))
            .order_by(RenderJob.created_at.desc())
            .first()
        )
    except Exception:
        logger.warning(
            "Failed to query linked render job for arrangement %s",
            arrangement.id,
            exc_info=True,
        )
        return arrangement

    if not linked_job:
        return arrangement

    if linked_job.status == "processing" and arrangement.status == "queued":
        arrangement.status = "processing"
        arrangement.progress = max(float(arrangement.progress or 0.0), 10.0)
        arrangement.progress_message = linked_job.progress_message or "Running arrangement job"
        db.commit()
        db.refresh(arrangement)
        return arrangement

    is_stale_queued = (
        linked_job.status == "queued"
        and linked_job.created_at is not None
        and linked_job.created_at <= now_utc - timedelta(seconds=15)
    )

    processing_started_at = linked_job.started_at or linked_job.created_at
    is_stale_processing = (
        linked_job.status == "processing"
        and processing_started_at is not None
        and processing_started_at <= now_utc - timedelta(seconds=processing_timeout_seconds)
    )

    if arrangement.status in {"queued", "processing"} and is_stale_processing:
        elapsed_seconds = int((now_utc - processing_started_at).total_seconds())
        timeout_message = (
            f"Render job timed out after {elapsed_seconds}s (limit {processing_timeout_seconds}s)"
        )
        logger.error(
            "Detected stale processing arrangement; forcing timeout failure: arrangement_id=%s job_id=%s elapsed_seconds=%s timeout_seconds=%s",
            arrangement.id,
            linked_job.id,
            elapsed_seconds,
            processing_timeout_seconds,
        )

        linked_job.status = "failed"
        linked_job.finished_at = now_utc
        linked_job.error_message = timeout_message
        linked_job.progress_message = "Render job timed out"

        arrangement.status = "failed"
        arrangement.error_message = timeout_message
        arrangement.progress_message = "Render job timed out"
        db.commit()
        db.refresh(arrangement)
        return arrangement

    if arrangement.status == "queued" and is_stale_queued:
        logger.warning(
            "Detected stale queued arrangement; starting fallback worker: arrangement_id=%s job_id=%s age_seconds=%s",
            arrangement.id,
            linked_job.id,
            int((now_utc - linked_job.created_at).total_seconds()) if linked_job.created_at else None,
        )

        try:
            queue = get_queue(name=DEFAULT_RENDER_QUEUE_NAME)
            rq_job = queue.fetch_job(linked_job.id)
            if rq_job:
                try:
                    rq_job.cancel()
                except Exception:
                    pass
                rq_job.delete()
        except Exception:
            logger.warning("Could not cancel queued RQ job for fallback launch: job_id=%s", linked_job.id, exc_info=True)

        linked_job.status = "processing"
        linked_job.started_at = now_utc
        linked_job.progress = max(float(linked_job.progress or 0.0), 10.0)
        linked_job.progress_message = "Fallback worker started"
        arrangement.status = "processing"
        arrangement.progress = max(float(arrangement.progress or 0.0), 10.0)
        arrangement.progress_message = "Fallback worker started"
        db.commit()
        db.refresh(arrangement)

        fallback_job_id = str(linked_job.id)
        fallback_loop_id = int(linked_job.loop_id)
        fallback_params_json = linked_job.params_json

        def _run_fallback() -> None:
            try:
                from app.workers.render_worker import render_loop_worker

                params = json.loads(fallback_params_json) if fallback_params_json else {}
                render_loop_worker(fallback_job_id, fallback_loop_id, params)
            except Exception:
                logger.exception(
                    "Fallback worker execution failed: arrangement_id=%s job_id=%s",
                    arrangement.id,
                    fallback_job_id,
                )

        threading.Thread(
            target=_run_fallback,
            name=f"arrangement-fallback-{arrangement.id}",
            daemon=True,
        ).start()
        return arrangement

    if linked_job.status == "failed" and arrangement.status in {"queued", "processing"}:
        arrangement.status = "failed"
        arrangement.error_message = linked_job.error_message or "Render job failed"
        arrangement.progress_message = "Worker failed"
        db.commit()
        db.refresh(arrangement)

    return arrangement


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
            "is_saved": "BOOLEAN DEFAULT false",
            "saved_at": "TIMESTAMP",
        }

        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                db.execute(text(f"ALTER TABLE arrangements ADD COLUMN {column_name} {column_type}"))
                logger.info("Added missing arrangements.%s column on-demand", column_name)

        db.flush()
    except Exception:
        logger.warning("Could not auto-reconcile arrangements schema on request path", exc_info=True)


def _build_arrangement_response(arrangement: Arrangement) -> "ArrangementResponse":
    """Build a normalized ArrangementResponse with a fresh presigned audio URL.

    For arrangements in ``done`` status with a stable ``output_s3_key``, a
    new short-lived access URL is derived from the permanent storage key on
    every call.  This prevents the frontend from receiving an expired S3
    presigned URL that would cause the audio player to show 0:00.

    For arrangements in any other status (queued, processing, failed) the
    audio URL fields are always ``None`` — there is no playable audio yet.

    Both ``output_url`` and ``output_file_url`` are set to the same value so
    that all frontend field names continue to work regardless of which alias
    the frontend reads.

    Phase 4 note: ``output_s3_key`` is the permanent, stable cache key.
    ``output_url``/``output_file_url`` are ephemeral access URLs regenerated
    on every read — never persisted as the canonical client-facing source of
    truth.
    """
    response = ArrangementResponse.from_orm(arrangement)

    # Populate duration_seconds from the arrangement's target_seconds column so the
    # frontend player can show expected length without a separate API call.
    if arrangement.target_seconds is not None:
        response = response.model_copy(update={"duration_seconds": arrangement.target_seconds})

    if arrangement.status == "done" and arrangement.output_s3_key:
        try:
            fresh_url = storage.create_presigned_get_url(
                arrangement.output_s3_key,
                expires_seconds=3600,
                download_filename=f"arrangement_{arrangement.id}.wav",
            )
            response = response.model_copy(
                update={"output_url": fresh_url, "output_file_url": fresh_url}
            )
            logger.debug(
                "_build_arrangement_response: arrangement_id=%s status=done fresh_url_generated=true",
                arrangement.id,
            )
        except (S3StorageError, OSError):
            logger.warning(
                "_build_arrangement_response: presigned URL regeneration failed: "
                "arrangement_id=%s output_s3_key=%s — falling back to stored url",
                arrangement.id,
                arrangement.output_s3_key,
                exc_info=True,
            )
            # Fall back: ensure both aliases point to the same stored URL even
            # if it may be expired, so the frontend has something to try.
            if response.output_url:
                response = response.model_copy(
                    update={"output_file_url": response.output_url}
                )
    elif arrangement.status != "done":
        # Explicitly clear audio URL fields for non-done arrangements so the
        # frontend never tries to play a partial or missing file.
        response = response.model_copy(
            update={"output_url": None, "output_file_url": None}
        )

    return response


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

    # Attach layering plan and arrangement_json to response
    response = ArrangementResponse.from_orm(arrangement)
    if hasattr(arrangement, 'layering_plan') and arrangement.layering_plan:
        response.layering_plan = [l.__dict__ for l in arrangement.layering_plan]
    # Optionally include arrangement_json
    try:
        import json
        response.arrangement_json = json.dumps(arrangement.to_dict())
    except Exception:
        response.arrangement_json = None
    return response


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
    include_unsaved: bool = False,
    db: Session = Depends(get_db),
):
    """List arrangements with optional filtering by loop_id."""
    _ensure_arrangements_schema(db)
    query = db.query(Arrangement)
    if loop_id is not None:
        query = query.filter(Arrangement.loop_id == loop_id)
    if not include_unsaved:
        query = query.filter(Arrangement.is_saved.is_(True), Arrangement.saved_at.isnot(None))
    arrangements = query.order_by(Arrangement.created_at.desc()).all()
    
    # Sync status for recent queued/processing arrangements to show fallback worker updates
    # This ensures the list reflects recent job status changes from the fallback mechanism
    synced_arrangements = []
    for arrangement in arrangements:
        if arrangement.status in {"queued", "processing"}:
            # Only sync recent items (within last 60 seconds) to avoid unnecessary queries
            age_seconds = (datetime.utcnow() - arrangement.created_at).total_seconds() if arrangement.created_at else 0
            if age_seconds < 60:
                synced = _sync_arrangement_status_from_job(db, arrangement)
                synced_arrangements.append(synced)
            else:
                synced_arrangements.append(arrangement)
        else:
            synced_arrangements.append(arrangement)
    
    return [_build_arrangement_response(item) for item in synced_arrangements]


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

    # Validate loop exists and file key
    loop = db.query(Loop).filter(Loop.id == request.loop_id).first()
    if not loop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Loop with ID {request.loop_id} not found",
        )
    if settings.get_storage_backend() == "local" and not loop.file_key:
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
    # Holds params needed to regenerate ProducerArrangement per candidate with a distinct
    # structure template.  Populated by the LLM-style and metadata-analysis paths below;
    # used inside the variation loop to produce structurally different arrangements.
    producer_gen_context: dict | None = None
    correlation_id = getattr(http_request.state, "correlation_id", None) or http_request.headers.get("x-correlation-id")

    effective_style_text = (request.style_text_input or "").strip()
    if request.producer_moves:
        moves_text = ", ".join(move for move in request.producer_moves if move)
        if moves_text:
            effective_style_text = f"{effective_style_text}; producer moves: {moves_text}" if effective_style_text else f"producer moves: {moves_text}"

    # Highest priority: explicit user-edited arrangement plan
    if request.arrangement_plan:
        try:
            planner_plan = ArrangementPlan.model_validate(request.arrangement_plan)

            detected_roles: list[str] = []
            loop_stem_meta = loop.stem_metadata or {}
            if isinstance(loop_stem_meta, dict):
                detected_roles = [str(role) for role in (loop_stem_meta.get("roles_detected") or []) if role]

            validation = validate_arrangement_plan(planner_plan, detected_roles)
            if not validation.valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "message": "Invalid arrangement_plan",
                        "errors": validation.errors,
                        "warnings": validation.warnings,
                    },
                )

            producer_arrangement_json = json.dumps(
                {
                    "version": "2.1",
                    "producer_arrangement": plan_to_producer_arrangement(planner_plan),
                    "from_user_plan": True,
                    "correlation_id": correlation_id,
                },
                default=str,
            )

            structure_preview = [
                {
                    "name": str(section.type).replace("_", " ").title(),
                    "bars": int(section.bars),
                    "energy": round(float(section.energy) / 5.0, 3),
                }
                for section in planner_plan.sections
            ]

            style_profile_json = json.dumps(
                {
                    "source": "user_arrangement_plan",
                    "planner_notes": planner_plan.planner_notes.model_dump(),
                }
            )
            ai_parsing_used = True
            style_preset = "user_plan"

            logger.info(
                "Using user-supplied arrangement plan: sections=%s total_bars=%s",
                len(planner_plan.sections),
                planner_plan.total_bars,
            )
        except HTTPException:
            raise
        except Exception as plan_error:
            logger.warning("Failed to parse user arrangement_plan: %s", plan_error, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid arrangement_plan payload: {plan_error}",
            )

    # V2: Handle LLM-based style parsing
    if not request.arrangement_plan and request.use_ai_parsing and effective_style_text:
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
                    logger.info(f"ProducerEngine enabled - capturing params for per-candidate generation: genre={genre_for_producer}")

                    # Defer ProducerEngine.generate() to the variation loop so each
                    # candidate receives a structurally distinct arrangement template.
                    producer_gen_context = {
                        "genre": genre_for_producer,
                        "style_profile": style_profile,
                        "extra_json_keys": {},
                    }
                except Exception as producer_error:
                    logger.warning(f"ProducerEngine param capture failed: {producer_error}", exc_info=True)
                    # Continue with fallback - producer_arrangement_json stays None
            else:
                logger.warning(f"ProducerEngine NOT enabled - feature flag is {settings.feature_producer_engine}")
        except Exception as llm_error:
            logger.warning(f"LLM style parsing failed: {llm_error}")
            # Fall through to preset-based or default handling

    # V1: Handle preset-based style configuration (fallback)
    elif not request.arrangement_plan and settings.feature_style_engine and request.style_preset:
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
    if settings.feature_producer_engine and not request.arrangement_plan and not ai_parsing_used and not request.genre:
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

                    # Defer ProducerEngine.generate() to the variation loop so each
                    # candidate receives a structurally distinct arrangement template.
                    producer_gen_context = {
                        "genre": detected_genre,
                        "style_profile": auto_style_profile,
                        "extra_json_keys": {
                            "metadata_analysis": metadata_analysis,
                            "auto_detected": True,
                        },
                    }

                    # Also store style profile for tracking
                    style_profile_json = auto_style_profile.model_dump_json()
                    ai_parsing_used = False  # Mark as metadata-based, not AI-based

                    logger.info(
                        "ProducerEngine params captured for per-candidate generation from metadata: genre=%s",
                        detected_genre,
                    )
                except Exception as producer_error:
                    logger.warning(f"ProducerEngine generation from metadata failed: {producer_error}", exc_info=True)
            else:
                logger.warning(f"Metadata analysis confidence too low ({confidence:.2f}), skipping auto-generation")
                
        except Exception as metadata_error:
            logger.warning(f"Metadata analysis failed: {metadata_error}", exc_info=True)
            # Continue without metadata-based generation

    # -------------------------------------------------------------------------
    # PRODUCER ENGINE V2 — deterministic section planning with decision log
    # Controlled by PRODUCER_ENGINE_V2 feature flag.
    # Runs on top of / instead of the legacy producer_arrangement_json path.
    # -------------------------------------------------------------------------
    producer_plan_v2: "ProducerPlanV2 | None" = None
    quality_score_v2: "QualityScoreSchema | None" = None
    section_summary_v2: list = []
    decision_log_v2: list = []
    producer_notes_v2: list[str] = []

    if settings.feature_producer_engine_v2:
        try:
            # Extract available roles from loop stem metadata
            v2_available_roles: list[str] = []
            loop_stem_meta = loop.stem_metadata or {}
            if isinstance(loop_stem_meta, dict):
                v2_available_roles = [
                    str(r) for r in (loop_stem_meta.get("roles_detected") or []) if r
                ]

            # Determine genre from request / prior parsing
            v2_genre = request.genre or "generic"
            if style_profile_json:
                try:
                    _sp_dict = json.loads(style_profile_json)
                    v2_genre = (
                        _sp_dict.get("resolved_preset")
                        or _sp_dict.get("genre")
                        or v2_genre
                    )
                except Exception:
                    pass

            plan_tempo_bpm = float(loop.bpm or loop.tempo or 120.0)
            calculated_target_bars = max(8, int(round(effective_target_seconds / ((60.0 / plan_tempo_bpm) * 4))))

            v2_source_type = "stem_pack" if v2_available_roles else "loop"

            builder = ProducerPlanBuilderV2(
                available_roles=v2_available_roles,
                genre=v2_genre,
                tempo=plan_tempo_bpm,
                target_bars=calculated_target_bars,
                source_type=v2_source_type,
                structure_template="standard",
            )
            raw_plan = builder.build()

            # Apply rules engine
            rules_result = ProducerRulesEngine.apply(raw_plan)
            refined_plan = rules_result.plan

            # Quality scoring
            qa_result = RenderQAService.score_plan(refined_plan)

            # Build API-friendly objects
            section_summary_v2 = [
                ProducerSectionSummaryItem(
                    index=s.index,
                    section_type=s.section_type.value,
                    label=s.label,
                    start_bar=s.start_bar,
                    length_bars=s.length_bars,
                    target_energy=s.target_energy.value,
                    density=s.density.value,
                    active_roles=s.active_roles,
                    muted_roles=s.muted_roles,
                    variation_strategy=s.variation_strategy.value,
                    transition_in=s.transition_in.value,
                    transition_out=s.transition_out.value,
                    notes=s.notes,
                    rationale=s.rationale,
                )
                for s in refined_plan.sections
            ]

            decision_log_v2 = [
                ProducerDecisionLogEntry(
                    section_index=e.section_index,
                    section_label=e.section_label,
                    decision=e.decision,
                    reason=e.reason,
                    flag=e.flag,
                )
                for e in refined_plan.decision_log
            ]

            producer_notes_v2 = [e.decision for e in refined_plan.decision_log]

            quality_score_v2 = QualityScoreSchema(
                structure_score=qa_result.score.structure_score,
                transition_score=qa_result.score.transition_score,
                audio_quality_score=qa_result.score.audio_quality_score,
                overall_score=qa_result.score.overall_score,
                flags=qa_result.score.flags,
                warnings=qa_result.score.warnings,
            )

            producer_plan_v2 = ProducerPlanV2(
                builder_version=refined_plan.builder_version,
                genre=refined_plan.genre,
                style_tags=refined_plan.style_tags,
                tempo=refined_plan.tempo,
                total_bars=refined_plan.total_bars,
                source_type=refined_plan.source_type,
                available_roles=refined_plan.available_roles,
                rules_applied=refined_plan.rules_applied,
                sections=section_summary_v2,
                decision_log=decision_log_v2,
            )

            # Enrich producer_arrangement_json with V2 data
            v2_payload = refined_plan.to_dict()
            if producer_arrangement_json:
                try:
                    existing_payload = json.loads(producer_arrangement_json)
                    existing_payload["producer_plan_v2"] = v2_payload
                    existing_payload["quality_score"] = quality_score_v2.model_dump()
                    producer_arrangement_json = json.dumps(existing_payload, default=str)
                except Exception:
                    pass
            else:
                producer_arrangement_json = json.dumps(
                    {
                        "version": "2.1",
                        "producer_plan_v2": v2_payload,
                        "quality_score": quality_score_v2.model_dump(),
                        "correlation_id": correlation_id,
                    },
                    default=str,
                )

            log_feature_event(
                logger,
                event="producer_engine_v2_plan_built",
                correlation_id=correlation_id,
                sections_count=len(section_summary_v2),
                total_bars=refined_plan.total_bars,
                rules_applied=refined_plan.rules_applied,
                quality_overall=qa_result.score.overall_score,
                violations_count=len(rules_result.violations),
                flag_producer_engine_v2=True,
            )

            logger.info(
                "ProducerEngineV2: %d sections, %d bars, quality=%.1f, %d rules applied",
                len(refined_plan.sections),
                refined_plan.total_bars,
                qa_result.score.overall_score,
                len(refined_plan.rules_applied),
            )

        except Exception as v2_error:
            logger.warning(
                "ProducerEngineV2 plan building failed — continuing without V2 plan: %s",
                v2_error,
                exc_info=True,
            )
            # Graceful fallback: legacy engine remains intact

    # -------------------------------------------------------------------------
    # REFERENCE-GUIDED ARRANGEMENT — Phase 4
    # Controlled by REFERENCE_GUIDED_ARRANGEMENT feature flag.
    # Loads a previously analyzed reference structure and adapts the producer
    # plan to follow its structural blueprint.
    # Musical content is NEVER copied from the reference.
    # -------------------------------------------------------------------------
    reference_guided = False
    reference_summary: str | None = None
    reference_structure_summary: dict | None = None
    reference_adaptation_mode: str | None = None
    reference_adaptation_strength_used: str | None = None
    reference_analysis_confidence: float | None = None

    if settings.feature_reference_guided_arrangement and request.reference_analysis_id:
        try:
            from app.routes.reference import _load_analysis
            from app.schemas.reference_arrangement import (
                ReferenceAdaptationStrength,
                ReferenceGuidanceMode,
                ReferenceStructure,
            )
            from app.services.reference_plan_adapter import reference_plan_adapter

            stored = _load_analysis(request.reference_analysis_id)
            if stored is None:
                logger.warning(
                    "Reference analysis ID not found: %s — skipping reference guidance",
                    request.reference_analysis_id,
                )
                log_feature_event(
                    logger,
                    event="reference_analysis_not_found",
                    correlation_id=correlation_id,
                    analysis_id=request.reference_analysis_id,
                )
            else:
                ref_structure = ReferenceStructure(**stored["structure"])

                # Resolve guidance mode and adaptation strength
                raw_mode = (
                    request.reference_guidance_mode
                    or stored.get("guidance_mode", "structure_and_energy")
                )
                raw_strength = (
                    request.reference_adaptation_strength
                    or stored.get("adaptation_strength", "medium")
                )
                try:
                    guidance_mode = ReferenceGuidanceMode(raw_mode)
                except ValueError:
                    guidance_mode = ReferenceGuidanceMode.STRUCTURE_AND_ENERGY

                try:
                    adaptation_strength = ReferenceAdaptationStrength(raw_strength)
                except ValueError:
                    adaptation_strength = ReferenceAdaptationStrength.MEDIUM

                # Extract available roles
                ref_available_roles: list[str] = []
                loop_stem_meta_ref = loop.stem_metadata or {}
                if isinstance(loop_stem_meta_ref, dict):
                    ref_available_roles = [
                        str(r) for r in (loop_stem_meta_ref.get("roles_detected") or []) if r
                    ]

                ref_tempo = float(loop.bpm or loop.tempo or 120.0)
                ref_target_bars = max(
                    8, int(round(effective_target_seconds / ((60.0 / ref_tempo) * 4)))
                ) if effective_target_seconds else None

                guidance = reference_plan_adapter.adapt(
                    structure=ref_structure,
                    guidance_mode=guidance_mode,
                    adaptation_strength=adaptation_strength,
                    available_roles=ref_available_roles,
                    user_tempo_bpm=ref_tempo,
                    user_target_bars=ref_target_bars,
                )

                reference_guided = True
                reference_summary = ref_structure.summary
                reference_structure_summary = {
                    "total_duration_sec": ref_structure.total_duration_sec,
                    "section_count": len(ref_structure.sections),
                    "tempo_estimate": ref_structure.tempo_estimate,
                    "analysis_quality": ref_structure.analysis_quality,
                    "energy_arc": guidance.energy_arc_summary,
                    "legal_note": guidance.legal_note,
                }
                reference_adaptation_mode = guidance.adaptation_mode
                reference_adaptation_strength_used = guidance.adaptation_strength
                reference_analysis_confidence = guidance.reference_confidence

                # Inject reference guidance into producer_arrangement_json
                ref_payload = {
                    "reference_analysis_id": request.reference_analysis_id,
                    "guidance_mode": guidance_mode.value,
                    "adaptation_strength": adaptation_strength.value,
                    "reference_confidence": guidance.reference_confidence,
                    "section_guidance": [g.model_dump() for g in guidance.section_guidance],
                    "suggested_total_bars": guidance.suggested_total_bars,
                    "energy_arc_summary": guidance.energy_arc_summary,
                    "adapter_decision_log": guidance.decision_log,
                    "legal_note": guidance.legal_note,
                }
                if producer_arrangement_json:
                    try:
                        existing_payload = json.loads(producer_arrangement_json)
                        existing_payload["reference_guidance"] = ref_payload
                        producer_arrangement_json = json.dumps(existing_payload, default=str)
                    except Exception:
                        pass
                else:
                    producer_arrangement_json = json.dumps(
                        {
                            "version": "2.1",
                            "reference_guidance": ref_payload,
                            "correlation_id": correlation_id,
                        },
                        default=str,
                    )

                # Extend producer_notes with reference adapter log
                if guidance.decision_log:
                    producer_notes_v2 = list(producer_notes_v2) + guidance.decision_log

                log_feature_event(
                    logger,
                    event="reference_guidance_applied",
                    correlation_id=correlation_id,
                    analysis_id=request.reference_analysis_id,
                    guidance_mode=guidance_mode.value,
                    adaptation_strength=adaptation_strength.value,
                    section_count=len(guidance.section_guidance),
                    reference_confidence=guidance.reference_confidence,
                    flag_reference_guided_arrangement=True,
                )

                logger.info(
                    "Reference guidance applied: analysis_id=%s sections=%d confidence=%.2f",
                    request.reference_analysis_id,
                    len(guidance.section_guidance),
                    guidance.reference_confidence,
                )

        except (HTTPException, ImportError):
            raise
        except Exception as ref_error:
            # Graceful fallback: continue with standard generation
            logger.warning(
                "Reference guidance failed — falling back to standard generation: %s",
                ref_error,
                exc_info=True,
            )
            log_feature_event(
                logger,
                event="reference_guidance_fallback",
                correlation_id=correlation_id,
                analysis_id=request.reference_analysis_id,
                error=str(ref_error),
            )

    # Create arrangement record(s)
    _ensure_arrangements_schema(db)
    logger.info(
        "DEBUG-SAVE: Creating arrangement previews with auto_save=%s ai_parsing_used=%s has_producer_json=%s json_len=%s",
        request.auto_save,
        ai_parsing_used,
        producer_arrangement_json is not None,
        len(producer_arrangement_json) if producer_arrangement_json else 0,
    )

    # Structure templates used to produce genuinely distinct arrangements when
    # multiple candidates are requested.  Cycling through these ensures each
    # candidate has a different section layout rather than being a seed-only
    # variation of the same structure.
    _CANDIDATE_TEMPLATES = ["standard", "progressive", "minimal", "looped"]

    candidate_count = max(1, int(request.variation_count or 1))
    candidates: list[ArrangementPreviewCandidate] = []
    render_job_ids: list[str] = []
    first_arrangement: Arrangement | None = None

    base_seed = None
    if isinstance(seed_used, int):
        base_seed = seed_used
    elif isinstance(request.seed, int):
        base_seed = int(request.seed)

    for variation_index in range(candidate_count):
        candidate_seed = (base_seed + variation_index) if base_seed is not None else None
        candidate_structure_json = structure_json
        if structure_preview and candidate_seed is not None:
            candidate_structure_json = json.dumps(
                {
                    "seed": candidate_seed,
                    "sections": structure_preview,
                    "correlation_id": correlation_id,
                    "variation_index": variation_index,
                }
            )

        # Generate a per-candidate ProducerArrangement using a distinct structure
        # template so each option presented to the user is structurally different
        # (not just a seed variation of the same section layout).
        candidate_producer_json = producer_arrangement_json
        if producer_gen_context is not None and producer_arrangement_json is None:
            candidate_template = _CANDIDATE_TEMPLATES[variation_index % len(_CANDIDATE_TEMPLATES)]
            try:
                candidate_arrangement = ProducerEngine.generate(
                    target_seconds=effective_target_seconds,
                    tempo=float(loop.bpm or loop.tempo or 120.0),
                    genre=producer_gen_context["genre"],
                    style_profile=producer_gen_context.get("style_profile"),
                    structure_template=candidate_template,
                )
                candidate_producer_json = json.dumps(
                    {
                        "version": "2.0",
                        "producer_arrangement": dataclass_asdict(candidate_arrangement),
                        "structure_template": candidate_template,
                        "correlation_id": correlation_id,
                        **producer_gen_context.get("extra_json_keys", {}),
                    },
                    default=str,
                )
                logger.info(
                    "Generated candidate %d with template=%s sections=%d",
                    variation_index,
                    candidate_template,
                    len(candidate_arrangement.sections),
                )
            except Exception as candidate_gen_err:
                logger.warning(
                    "Per-candidate ProducerEngine generation failed (index=%d template=%s): %s",
                    variation_index,
                    candidate_template,
                    candidate_gen_err,
                    exc_info=True,
                )
                # candidate_producer_json stays None — renderer will fall back to style_sections

        arrangement = Arrangement(
            loop_id=request.loop_id,
            status="queued",
            target_seconds=effective_target_seconds,
            genre=request.genre,
            intensity=request.intensity,
            include_stems=request.include_stems,
            arrangement_json=candidate_structure_json,
            style_profile_json=style_profile_json,
            ai_parsing_used=ai_parsing_used,
            producer_arrangement_json=candidate_producer_json,
            is_saved=request.auto_save,
            saved_at=datetime.utcnow() if request.auto_save else None,
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

        if first_arrangement is None:
            first_arrangement = arrangement

        logger.info(
            "Arrangement created: arrangement_id=%s loop_id=%s status=%s variation_index=%s",
            arrangement.id,
            arrangement.loop_id,
            arrangement.status,
            variation_index,
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
            "variations": 1,
            "variation_styles": [],
            "custom_style": effective_style_text or request.style_preset,
            "arrangement_id": arrangement.id,
            "correlation_id": correlation_id,
            "variation_index": variation_index,
            "arrangement_preset": request.arrangement_preset or "trap",
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

        render_job_ids.append(job.id)
        candidates.append(
            ArrangementPreviewCandidate(
                arrangement_id=arrangement.id,
                status=arrangement.status,
                created_at=arrangement.created_at,
                render_job_id=job.id,
                seed_used=candidate_seed,
            )
        )

    log_feature_event(
        logger,
        event="response_returned",
        correlation_id=correlation_id,
        route="/api/v1/arrangements/generate",
        arrangement_id=arrangement.id,
        status_code=202,
    )

    primary_job_id = render_job_ids[0] if render_job_ids else None
    return AudioArrangementGenerateResponse(
        arrangement_id=first_arrangement.id if first_arrangement else None,
        loop_id=request.loop_id,
        status=first_arrangement.status if first_arrangement else None,
        created_at=first_arrangement.created_at if first_arrangement else None,
        job_id=primary_job_id,
        poll_url=f"/api/v1/jobs/{primary_job_id}" if primary_job_id else None,
        render_job_ids=render_job_ids,
        seed_used=seed_used,
        style_preset=style_preset,
        arrangement_preset=request.arrangement_preset,
        style_profile=json.loads(style_profile_json) if style_profile_json else None,
        structure_preview=structure_preview,
        candidates=candidates,
        # Duration fields: surface target_seconds and bpm so the frontend preview
        # player can show the expected duration without an extra API call.
        target_seconds=effective_target_seconds,
        bpm=float(loop.bpm or loop.tempo or 120.0),
        # Phase 5: backward-compatible producer intelligence fields
        producer_plan=producer_plan_v2,
        producer_notes=producer_notes_v2,
        quality_score=quality_score_v2,
        section_summary=section_summary_v2,
        decision_log=decision_log_v2,
        # Reference-Guided Arrangement Mode fields (Phase 4)
        reference_guided=reference_guided,
        reference_summary=reference_summary,
        reference_structure_summary=reference_structure_summary,
        adaptation_mode=reference_adaptation_mode,
        adaptation_strength=reference_adaptation_strength_used,
        reference_analysis_confidence=reference_analysis_confidence,
    )


@router.post(
    "/{arrangement_id}/save",
    response_model=ArrangementResponse,
    summary="Save arrangement preview",
    description="Marks a generated preview arrangement as saved so it appears in history.",
)
def save_arrangement_preview(
    arrangement_id: int,
    db: Session = Depends(get_db),
):
    _ensure_arrangements_schema(db)

    arrangement = db.query(Arrangement).filter(Arrangement.id == arrangement_id).first()
    if not arrangement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Arrangement with ID {arrangement_id} not found",
        )

    arrangement.is_saved = True
    arrangement.saved_at = arrangement.saved_at or datetime.utcnow()
    db.commit()
    db.refresh(arrangement)
    return ArrangementResponse.from_orm(arrangement)


@router.post(
    "/plan",
    response_model=ArrangementPlanResponse,
    summary="Generate AI arrangement plan",
    description="Generate a strict JSON arrangement plan from loop metadata and detected stem roles.",
)
async def generate_arrangement_plan(request: ArrangementPlanRequest):
    """Generate an arrangement plan with LLM + deterministic validation/fallback."""
    plan, validation, planner_meta = await arrangement_planner_service.generate_plan(
        planner_input=request.input,
        user_request=request.user_request,
        planner_config=request.planner_config,
    )

    return ArrangementPlanResponse(
        plan=plan,
        validation=validation,
        planner_meta=planner_meta,
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

    arrangement = _sync_arrangement_status_from_job(db, arrangement)

    response = _build_arrangement_response(arrangement)
    logger.info(
        "GET arrangement: arrangement_id=%s status=%s output_s3_key=%s audio_url_set=%s",
        arrangement_id,
        arrangement.status,
        arrangement.output_s3_key,
        response.output_url is not None,
    )
    return response


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
        "Access-Control-Expose-Headers": "Content-Disposition, Content-Length, Accept-Ranges",
        "Accept-Ranges": "bytes",
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

        file_size = local_path.stat().st_size
        local_headers = {**headers, "Content-Length": str(file_size)}

        if is_swagger_request:
            return FileResponse(
                path=str(local_path),
                media_type=content_type,
                filename=download_filename,
                headers=local_headers,
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
            headers=local_headers,
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
    # Forward Content-Length from S3 so the browser audio player can show duration.
    s3_content_length = s3_object.get("ContentLength")
    s3_headers = dict(headers)
    if s3_content_length is not None:
        s3_headers["Content-Length"] = str(s3_content_length)

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
            headers=s3_headers,
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
        headers=s3_headers,
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

    # Include rendered timeline/debug payload if available
    if arrangement.arrangement_json:
        try:
            timeline = json.loads(arrangement.arrangement_json)
            metadata["timeline"] = timeline
            if isinstance(timeline, dict) and "producer_debug_report" in timeline:
                metadata["producer_debug_report"] = timeline.get("producer_debug_report")
        except json.JSONDecodeError:
            logger.warning(f"Failed to decode arrangement_json for arrangement {arrangement_id}")
    
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
        logger.info("DAW export: generating ZIP for arrangement %s (key=%s)", arrangement.id, export_key)
        try:
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

            logger.info(
                "DAW export: ZIP generated for arrangement %s (size=%d bytes), uploading to key=%s",
                arrangement.id,
                len(zip_bytes),
                export_key,
            )
            storage.upload_file(
                file_bytes=zip_bytes,
                content_type="application/zip",
                key=export_key,
            )
        except Exception:
            logger.exception("DAW export: failed to generate/upload ZIP for arrangement %s", arrangement.id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate DAW export ZIP.",
            )
        arrangement.stems_zip_url = f"/api/v1/arrangements/{arrangement.id}/daw-export/download"
        db.commit()
        db.refresh(arrangement)
    else:
        logger.info("DAW export: cached ZIP found for arrangement %s (key=%s)", arrangement.id, export_key)
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
    logger.info("DAW export: returning download_url=%s for arrangement %s", download_url, arrangement.id)

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
        logger.warning("DAW export download: ZIP not found for arrangement %s (key=%s)", arrangement_id, export_key)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DAW export ZIP has not been generated yet. Call GET /daw-export first.",
        )

    logger.info("DAW export download: serving %s for arrangement %s", export_key, arrangement_id)

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