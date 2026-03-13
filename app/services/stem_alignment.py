"""Stem auto-alignment service.

Accepts imperfect stem timing and attempts safe timeline alignment using
leading-silence/onset detection, trim/pad operations, and duration normalization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydub import AudioSegment
from pydub.silence import detect_nonsilent


class StemAlignmentError(ValueError):
    """Raised when stems are too damaged/incompatible to align safely."""


START_OFFSET_MISALIGNMENT_MESSAGE = "Stems are misaligned (different start offset)"


@dataclass
class StemAlignmentResult:
    stems: list[tuple[str, AudioSegment]]
    sample_rate: int
    duration_ms: int
    reference_offset_ms: int
    original_offsets_ms: dict[str, int]
    adjustments_ms: dict[str, dict[str, int]]
    auto_aligned: bool
    confidence: float
    warnings: list[str]
    low_confidence: bool
    fallback_to_loop: bool


@dataclass
class _StemAnalysis:
    name: str
    audio: AudioSegment
    offset_ms: int
    has_detected_onset: bool


def _detect_offset_ms(audio: AudioSegment) -> tuple[int, bool]:
    if len(audio) <= 0:
        return 0, False

    if audio.dBFS == float("-inf"):
        return 0, False

    silence_thresh = max(-60, int(audio.dBFS) - 22)
    ranges = detect_nonsilent(audio, min_silence_len=20, silence_thresh=silence_thresh)
    if not ranges:
        return 0, False

    return int(ranges[0][0]), True


def _score_confidence(
    analyses: list[_StemAnalysis],
    offset_spread_ms: int,
    duration_spread_ms: int,
) -> float:
    score = 1.0

    missing_onset_count = sum(0 if item.has_detected_onset else 1 for item in analyses)
    score -= min(0.40, missing_onset_count * 0.10)
    score -= min(0.35, offset_spread_ms / 2500.0)
    score -= min(0.25, duration_spread_ms / 7000.0)

    return max(0.0, min(1.0, round(score, 3)))


def align_stems(
    stems: list[tuple[str, AudioSegment]],
    *,
    severe_duration_delta_ms: int = 15000,
    low_confidence_threshold: float = 0.45,
) -> StemAlignmentResult:
    """Auto-align stems by detecting offsets and applying trim/pad operations.

    Hard failures are only raised for truly unusable inputs.
    """
    if len(stems) < 2:
        raise StemAlignmentError("At least two stem files are required")

    target_rate = int(stems[0][1].frame_rate)
    analyses: list[_StemAnalysis] = []

    for name, audio in stems:
        if len(audio) <= 0:
            raise StemAlignmentError(f"Unreadable or empty audio stem: {name}")

        normalized = audio
        if int(normalized.frame_rate) != target_rate:
            normalized = normalized.set_frame_rate(target_rate)
        if normalized.channels != 2:
            normalized = normalized.set_channels(2)

        offset, onset_detected = _detect_offset_ms(normalized)
        analyses.append(
            _StemAnalysis(
                name=name,
                audio=normalized,
                offset_ms=offset,
                has_detected_onset=onset_detected,
            )
        )

    durations = [len(item.audio) for item in analyses]
    min_duration = min(durations)
    max_duration = max(durations)
    duration_spread = max_duration - min_duration

    if min_duration < 300:
        raise StemAlignmentError("One or more stems are too short or severely corrupted")

    severe_duration_mismatch = duration_spread > severe_duration_delta_ms

    if all(item.audio.dBFS == float("-inf") for item in analyses):
        raise StemAlignmentError("All stems appear silent/corrupted")

    offsets = [item.offset_ms for item in analyses]
    offset_spread = max(offsets) - min(offsets)
    reference_offset = int(sorted(offsets)[len(offsets) // 2])

    adjusted: list[tuple[str, AudioSegment]] = []
    adjustments_ms: dict[str, dict[str, int]] = {}
    warnings: list[str] = []

    for item in analyses:
        trim_ms = max(0, item.offset_ms - reference_offset)
        pad_ms = max(0, reference_offset - item.offset_ms)

        shifted = item.audio
        if trim_ms > 0:
            shifted = shifted[trim_ms:]
        if pad_ms > 0:
            shifted = AudioSegment.silent(duration=pad_ms).set_frame_rate(target_rate).set_channels(2) + shifted

        adjusted.append((item.name, shifted))
        adjustments_ms[item.name] = {
            "trim_ms": int(trim_ms),
            "pad_ms": int(pad_ms),
        }

    adjusted_durations = [len(audio) for _, audio in adjusted]
    normalized_duration = max(adjusted_durations)

    normalized_stems: list[tuple[str, AudioSegment]] = []
    for name, audio in adjusted:
        if len(audio) < normalized_duration:
            diff = normalized_duration - len(audio)
            audio = audio + AudioSegment.silent(duration=diff).set_frame_rate(target_rate).set_channels(2)
        elif len(audio) > normalized_duration:
            audio = audio[:normalized_duration]
        normalized_stems.append((name, audio))

    if offset_spread > 0:
        warnings.append(
            f"{START_OFFSET_MISALIGNMENT_MESSAGE} — auto-aligned during upload"
        )
        warnings.append(
            f"Detected start-offset spread of {offset_spread}ms and auto-aligned stems"
        )

    if duration_spread > 120:
        warnings.append(
            f"Detected duration spread of {duration_spread}ms and normalized end lengths"
        )

    if severe_duration_mismatch:
        warnings.append(
            "Severe stem duration mismatch detected; upload accepted with stereo fallback recommendation"
        )

    for item in analyses:
        if not item.has_detected_onset:
            warnings.append(f"Low-confidence onset detection for stem '{item.name}'")

    confidence = _score_confidence(analyses, offset_spread, duration_spread)
    low_confidence = confidence < low_confidence_threshold or severe_duration_mismatch

    if low_confidence:
        warnings.append(
            "Alignment confidence is low; upload accepted with stereo fallback recommendation"
        )

    return StemAlignmentResult(
        stems=normalized_stems,
        sample_rate=target_rate,
        duration_ms=normalized_duration,
        reference_offset_ms=reference_offset,
        original_offsets_ms={item.name: int(item.offset_ms) for item in analyses},
        adjustments_ms=adjustments_ms,
        auto_aligned=offset_spread > 0 or duration_spread > 0,
        confidence=confidence,
        warnings=warnings,
        low_confidence=low_confidence,
        fallback_to_loop=low_confidence,
    )


def alignment_result_to_metadata(result: StemAlignmentResult) -> dict[str, Any]:
    return {
        "auto_aligned": result.auto_aligned,
        "confidence": result.confidence,
        "low_confidence": result.low_confidence,
        "fallback_to_loop": result.fallback_to_loop,
        "reference_offset_ms": result.reference_offset_ms,
        "original_offsets_ms": result.original_offsets_ms,
        "adjustments_ms": result.adjustments_ms,
        "warnings": result.warnings,
    }
