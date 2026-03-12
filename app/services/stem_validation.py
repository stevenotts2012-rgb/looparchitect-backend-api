"""Stem validation + normalization rules for producer-grade stem packs."""

from __future__ import annotations

from dataclasses import dataclass

from pydub import AudioSegment
from pydub.silence import detect_nonsilent


class StemValidationError(ValueError):
    pass


@dataclass
class StemValidationResult:
    stems: list[tuple[str, AudioSegment]]
    sample_rate: int
    duration_ms: int
    lead_in_ms: int


def _leading_content_ms(audio: AudioSegment) -> int:
    ranges = detect_nonsilent(audio, min_silence_len=25, silence_thresh=audio.dBFS - 22 if audio.dBFS != float("-inf") else -55)
    if not ranges:
        return 0
    return int(ranges[0][0])


def validate_and_normalize_stems(
    stems: list[tuple[str, AudioSegment]],
    *,
    max_duration_delta_ms: int = 120,
    max_lead_delta_ms: int = 45,
) -> StemValidationResult:
    if len(stems) < 2:
        raise StemValidationError("At least two stem files are required")

    target_rate = int(stems[0][1].frame_rate)
    normalized: list[tuple[str, AudioSegment]] = []

    for name, audio in stems:
        clip = audio
        if int(clip.frame_rate) != target_rate:
            clip = clip.set_frame_rate(target_rate)
        if clip.channels != 2:
            clip = clip.set_channels(2)
        normalized.append((name, clip))

    lead_ins = [_leading_content_ms(audio) for _, audio in normalized]
    if max(lead_ins) - min(lead_ins) > max_lead_delta_ms:
        raise StemValidationError("Stems are misaligned (different start offsets)")

    common_lead = min(lead_ins)
    aligned = [(name, audio[common_lead:]) for name, audio in normalized]

    durations = [len(audio) for _, audio in aligned]
    min_duration = min(durations)
    max_duration = max(durations)
    if max_duration - min_duration > max_duration_delta_ms:
        raise StemValidationError("All stems must be aligned and the same length")

    trimmed = [(name, audio[:min_duration]) for name, audio in aligned]

    return StemValidationResult(
        stems=trimmed,
        sample_rate=target_rate,
        duration_ms=min_duration,
        lead_in_ms=common_lead,
    )
