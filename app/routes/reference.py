"""
Reference-Guided Arrangement Mode — Upload & Analysis Endpoint (Phase 4).

POST /api/v1/reference/analyze
    - Accepts a reference audio file upload.
    - Extracts structural/energy guidance only (no musical content).
    - Returns an analysis_id that can be passed to arrangement generation.

Legal / product guardrails enforced here:
- Reference audio is used for structure and energy guidance ONLY.
- Musical content (melody, harmony, drum patterns) is never extracted or stored.
- Clear disclaimers are included in all responses.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, UploadFile, File, status

from app.config import settings
from app.schemas.reference_arrangement import (
    ReferenceAdaptationStrength,
    ReferenceAnalysisResponse,
    ReferenceGuidanceMode,
)
from app.services.audit_logging import log_feature_event
from app.services.reference_analyzer import reference_analyzer
from app.services.storage import storage, S3StorageError

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants / validation limits (V1)
# ---------------------------------------------------------------------------

_ALLOWED_EXTENSIONS = {"wav", "mp3", "flac", "ogg", "m4a", "aac"}
_ALLOWED_CONTENT_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/flac",
    "audio/x-flac",
    "audio/ogg",
    "audio/mp4",
    "audio/m4a",
    "audio/aac",
    "application/octet-stream",  # Generic fallback (validate by extension)
}
_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
_MAX_DURATION_SECONDS = 900.0             # 15 minutes (V1 limit)

_LEGAL_DISCLAIMER = (
    "Reference audio is used for structural and energy guidance only. "
    "Musical content (melody, harmony, drum patterns) is not copied or reproduced. "
    "Your arrangement will be generated entirely from your own source material."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_file(file: UploadFile, file_bytes: bytes) -> None:
    """Raise HTTPException if the uploaded file is invalid."""
    # Check size
    if len(file_bytes) > _MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Reference file exceeds maximum size of "
                f"{_MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
            ),
        )
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reference file is empty.",
        )

    # Check extension
    filename = (file.filename or "").lower()
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type '.{ext}'. "
                f"Accepted formats: {', '.join(sorted(_ALLOWED_EXTENSIONS))}."
            ),
        )


def _store_analysis(analysis_id: str, payload: dict) -> str:
    """Persist the analysis JSON to storage and return its storage key."""
    key = f"reference_analyses/{analysis_id}.json"
    json_bytes = json.dumps(payload, default=str).encode("utf-8")
    try:
        storage.upload_file(json_bytes, "application/json", key)
    except S3StorageError as exc:
        logger.warning("Could not persist reference analysis to storage: %s", exc)
        # Best-effort local fallback
        try:
            local_dir = Path("uploads/reference_analyses")
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / f"{analysis_id}.json").write_bytes(json_bytes)
            logger.info("Reference analysis saved locally: %s", analysis_id)
        except Exception as local_exc:
            logger.warning("Local fallback save also failed: %s", local_exc)
    return key


def _load_analysis(analysis_id: str) -> Optional[dict]:
    """Load a previously stored analysis by its ID.

    The analysis_id is validated as a UUID to prevent path traversal attacks.
    """
    # Sanitize: only allow valid UUID-format IDs to prevent path traversal
    try:
        import uuid as _uuid_mod
        # Validate and normalize as UUID string — raises ValueError on invalid input
        safe_id = str(_uuid_mod.UUID(analysis_id))
    except (ValueError, AttributeError):
        logger.warning("Invalid analysis_id format (not a UUID): %s", analysis_id)
        return None

    key = f"reference_analyses/{safe_id}.json"

    # Try storage service first
    try:
        backend = settings.get_storage_backend()
        if backend == "s3":
            import boto3  # type: ignore
            s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
            )
            obj = s3.get_object(Bucket=settings.get_s3_bucket(), Key=key)
            return json.loads(obj["Body"].read())
        else:
            # Local storage: construct safe path and verify it stays within expected directory
            base_dir = Path("uploads/reference_analyses").resolve()
            local_path = (base_dir / f"{safe_id}.json").resolve()
            # Guard against path traversal: ensure resolved path stays inside base_dir
            if not str(local_path).startswith(str(base_dir)):
                logger.warning(
                    "Path traversal attempt blocked for analysis_id=%s", safe_id
                )
                return None
            if local_path.exists():
                return json.loads(local_path.read_bytes())
    except Exception as exc:
        logger.warning("Could not load reference analysis %s: %s", safe_id, exc)

    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/analyze",
    response_model=ReferenceAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze a reference audio file for structural guidance",
    description=(
        "Upload a reference audio track (full song or instrumental). "
        "The system extracts high-level structural guidance ONLY: "
        "section boundaries, energy curve, density progression, and tempo estimate. "
        "\n\n"
        "**Legal / Product Guarantee:** "
        "Musical content (melody, harmony, chord progressions, drum patterns) is "
        "never extracted, stored, or reproduced. "
        "The reference is used exclusively as a structural blueprint for your own material."
        "\n\n"
        "Returns an `analysis_id` to pass into `POST /api/v1/arrangements/generate`."
    ),
)
async def analyze_reference(
    file: UploadFile = File(
        ...,
        description="Reference audio file (WAV, MP3, FLAC, OGG, M4A, AAC; max 100 MB, max 15 min)",
    ),
    guidance_mode: ReferenceGuidanceMode = Form(
        default=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
        description="Which aspects of the reference to use as guidance",
    ),
    adaptation_strength: ReferenceAdaptationStrength = Form(
        default=ReferenceAdaptationStrength.MEDIUM,
        description="How closely to follow the reference structure (loose | medium | close)",
    ),
) -> ReferenceAnalysisResponse:
    """Upload and analyze a reference audio file.

    Feature-gated: requires ``REFERENCE_SECTION_ANALYSIS=true``.
    """
    if not settings.feature_reference_section_analysis:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Reference section analysis is not enabled. "
                "Set REFERENCE_SECTION_ANALYSIS=true to enable this feature."
            ),
        )

    # Read file bytes
    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {exc}",
        ) from exc

    _validate_file(file, file_bytes)

    filename = file.filename or "reference.wav"
    analysis_id = str(uuid.uuid4())

    log_feature_event(
        logger,
        event="reference_analysis_started",
        analysis_id=analysis_id,
        filename=filename,
        file_size_bytes=len(file_bytes),
        guidance_mode=guidance_mode.value,
        adaptation_strength=adaptation_strength.value,
        flag_reference_section_analysis=True,
    )

    # Run analysis (always succeeds — returns fallback on failure)
    try:
        structure = reference_analyzer.analyze(file_bytes, filename=filename)
    except Exception as exc:
        logger.error(
            "Unexpected error in reference_analyzer.analyze: %s", exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reference analysis failed unexpectedly: {exc}",
        )

    # Validate duration limit
    if structure.total_duration_sec > _MAX_DURATION_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Reference audio exceeds maximum duration of "
                f"{int(_MAX_DURATION_SECONDS // 60)} minutes for V1. "
                "Please use a shorter reference track."
            ),
        )

    created_at = datetime.utcnow()

    # Persist analysis for later retrieval during arrangement generation
    payload = {
        "analysis_id": analysis_id,
        "structure": structure.model_dump(),
        "guidance_mode": guidance_mode.value,
        "adaptation_strength": adaptation_strength.value,
        "created_at": created_at.isoformat(),
    }
    _store_analysis(analysis_id, payload)

    log_feature_event(
        logger,
        event="reference_analysis_complete",
        analysis_id=analysis_id,
        duration_sec=structure.total_duration_sec,
        section_count=len(structure.sections),
        confidence=structure.analysis_confidence,
        quality=structure.analysis_quality,
        tempo_estimate=structure.tempo_estimate,
        warnings_count=len(structure.analysis_warnings),
    )

    logger.info(
        "Reference analysis complete: id=%s sections=%d confidence=%.2f quality=%s",
        analysis_id,
        len(structure.sections),
        structure.analysis_confidence,
        structure.analysis_quality,
    )

    return ReferenceAnalysisResponse(
        analysis_id=analysis_id,
        structure=structure,
        guidance_mode=guidance_mode,
        adaptation_strength=adaptation_strength,
        created_at=created_at,
        legal_disclaimer=_LEGAL_DISCLAIMER,
    )
