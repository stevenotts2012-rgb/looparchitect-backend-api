"""
Track Technical Quality Analysis — Upload Endpoint.

POST /api/v1/track/analyze-quality
    - Accepts an audio file upload (WAV, MP3, FLAC, OGG, M4A, AAC).
    - Returns technical quality metrics: sample rate, bit depth, clipping,
      mono compatibility, integrated loudness, true peak, phase issues,
      stereo field width, and a 4-band tonal profile.
    - Provides actionable mixing/mastering suggestions derived from the metrics.

Feature-gated by ``TRACK_QUALITY_ANALYSIS`` environment variable.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import settings
from app.schemas.track_quality import TrackQualityAnalysisResponse
from app.services.track_quality_analyzer import track_quality_analyzer

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants / validation limits
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
    "application/octet-stream",  # Generic fallback — validated by extension
}
_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_upload(file: UploadFile, file_bytes: bytes) -> None:
    """Raise HTTPException if the uploaded audio file is invalid."""
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    if len(file_bytes) > _MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File exceeds maximum allowed size of "
                f"{_MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
            ),
        )

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


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post(
    "/analyze-quality",
    response_model=TrackQualityAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyse the technical quality of an audio track",
    description=(
        "Upload an audio track to receive a detailed technical quality report.\n\n"
        "**Metrics returned:**\n"
        "- Sample rate and bit depth\n"
        "- Clipping detection\n"
        "- Mono compatibility (phase coherence test)\n"
        "- Integrated loudness (simplified BS.1770-3 LUFS approximation)\n"
        "- True peak level (dBFS)\n"
        "- Phase issue detection\n"
        "- Stereo field width (Narrow / Normal / Wide)\n"
        "- 4-band tonal profile with status per band\n"
        "- Actionable mixing/mastering suggestions\n\n"
        "**Feature gate:** requires `TRACK_QUALITY_ANALYSIS=true`."
    ),
)
async def analyze_track_quality(
    file: UploadFile = File(
        ...,
        description=(
            "Audio file to analyse (WAV, MP3, FLAC, OGG, M4A, AAC; max 100 MB)."
        ),
    ),
) -> TrackQualityAnalysisResponse:
    """Analyse an uploaded audio file and return technical quality metrics.

    Feature-gated: requires ``TRACK_QUALITY_ANALYSIS=true``.
    """
    if not settings.feature_track_quality_analysis:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Track quality analysis is not enabled. "
                "Set TRACK_QUALITY_ANALYSIS=true to enable this feature."
            ),
        )

    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {exc}",
        ) from exc

    _validate_upload(file, file_bytes)

    filename = file.filename or "track.wav"

    logger.info(
        "track_quality: analysis requested filename=%s size_bytes=%d",
        filename,
        len(file_bytes),
    )

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            track_quality_analyzer.analyze,
            file_bytes,
            filename,
        )
    except Exception as exc:
        logger.error(
            "track_quality: analysis failed for %s: %s", filename, exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Track quality analysis failed: {exc}",
        ) from exc

    logger.info(
        "track_quality: analysis complete filename=%s lufs=%.1f peak=%.1f "
        "stereo=%s suggestions=%d",
        filename,
        result.integrated_loudness,
        result.true_peak,
        result.stereo_field.value,
        len(result.suggestions),
    )

    return result
