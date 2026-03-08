"""Final mastering/polish stage for rendered arrangements."""

from __future__ import annotations

from dataclasses import dataclass

from pydub import AudioSegment

from app.config import settings


@dataclass
class MasteringResult:
    audio: AudioSegment
    profile: str
    peak_dbfs_before: float
    peak_dbfs_after: float
    applied: bool


def _safe_peak(audio: AudioSegment) -> float:
    peak = float(audio.max_dBFS)
    if peak == float("-inf"):
        return -120.0
    return peak


def _profile_for_genre(genre: str | None) -> str:
    explicit = (settings.mastering_profile_default or "").strip().lower()
    if explicit and explicit not in {"auto", "none"}:
        return explicit

    g = str(genre or "").strip().lower()
    if g in {"rnb", "r&b", "neo-soul", "neosoul"}:
        return "rnb_smooth"
    if g in {"trap", "hip-hop", "hiphop"}:
        return "low_end_focus"
    return "transparent"


def apply_mastering(audio: AudioSegment, *, genre: str | None) -> MasteringResult:
    """Apply lightweight final mastering chain with genre-aware profile."""
    if not settings.feature_mastering_stage:
        peak = _safe_peak(audio)
        return MasteringResult(
            audio=audio,
            profile="disabled",
            peak_dbfs_before=peak,
            peak_dbfs_after=peak,
            applied=False,
        )

    profile = _profile_for_genre(genre)
    before_peak = _safe_peak(audio)
    mastered = audio

    if profile == "rnb_smooth":
        body = mastered.low_pass_filter(12000) + 1
        air = mastered.high_pass_filter(6500) - 5
        mastered = body.overlay(air)
        mastered = mastered.low_pass_filter(15000)
    elif profile == "low_end_focus":
        sub = mastered.low_pass_filter(180) + 2
        presence = mastered.high_pass_filter(2500) - 2
        mastered = mastered.overlay(sub).overlay(presence)
    else:
        gentle_body = mastered.low_pass_filter(14000) + 0.5
        mastered = mastered.overlay(gentle_body, gain_during_overlay=-1)

    post_peak = _safe_peak(mastered)
    target_ceiling_dbfs = -1.0
    if post_peak > target_ceiling_dbfs:
        mastered = mastered - (post_peak - target_ceiling_dbfs)

    after_peak = _safe_peak(mastered)
    return MasteringResult(
        audio=mastered,
        profile=profile,
        peak_dbfs_before=before_peak,
        peak_dbfs_after=after_peak,
        applied=True,
    )
