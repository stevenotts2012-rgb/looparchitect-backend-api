"""Stem validation + normalization rules for producer-grade stem packs."""

from __future__ import annotations

from dataclasses import dataclass

from pydub import AudioSegment
from app.services.stem_alignment import (
    START_OFFSET_MISALIGNMENT_MESSAGE,
    StemAlignmentError,
    align_stems,
    alignment_result_to_metadata,
)


class StemValidationError(ValueError):
    pass


@dataclass
class StemValidationResult:
    stems: list[tuple[str, AudioSegment]]
    sample_rate: int
    duration_ms: int
    lead_in_ms: int
    auto_aligned: bool
    alignment_confidence: float
    alignment_metadata: dict
    warnings: list[str]
    fallback_to_loop: bool


def validate_and_normalize_stems(
    stems: list[tuple[str, AudioSegment]],
    *,
    max_duration_delta_ms: int = 120,
    max_lead_delta_ms: int = 45,
) -> StemValidationResult:
    downgraded_legacy_misalignment = False
    try:
        alignment = align_stems(
            stems,
            severe_duration_delta_ms=max(15000, max_duration_delta_ms * 50),
            low_confidence_threshold=0.45,
        )
    except StemAlignmentError as exc:
        message = str(exc)
        normalized_message = message.lower()
        if "different start offset" in normalized_message or "stems are misaligned" in normalized_message:
            downgraded_legacy_misalignment = True
            alignment = align_stems(
                stems,
                severe_duration_delta_ms=10**9,
                low_confidence_threshold=0.45,
            )
        else:
            raise StemValidationError(message) from exc

    warnings = list(alignment.warnings)
    if downgraded_legacy_misalignment and not any(START_OFFSET_MISALIGNMENT_MESSAGE in warning for warning in warnings):
        warnings.insert(0, f"{START_OFFSET_MISALIGNMENT_MESSAGE} — auto-aligned during upload")

    alignment_metadata = alignment_result_to_metadata(alignment)
    alignment_metadata["warnings"] = list(warnings)

    return StemValidationResult(
        stems=alignment.stems,
        sample_rate=alignment.sample_rate,
        duration_ms=alignment.duration_ms,
        lead_in_ms=alignment.reference_offset_ms,
        auto_aligned=alignment.auto_aligned,
        alignment_confidence=alignment.confidence,
        alignment_metadata=alignment_metadata,
        warnings=warnings,
        fallback_to_loop=alignment.fallback_to_loop,
    )
