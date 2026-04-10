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
        # Warm the top end and add gentle body; avoid stacking copies of the signal.
        mastered = mastered.low_pass_filter(13000) + 0.5
    elif profile == "low_end_focus":
        # Trap: remove truly subsonic rumble, gentle high-end roll for warmth.
        # Do NOT overlay copies of the signal — that causes sub mud and potential clipping.
        mastered = mastered.high_pass_filter(30)
        mastered = mastered.low_pass_filter(16000)
    else:
        # Transparent: gentle high-end roll only; no signal duplication.
        mastered = mastered.low_pass_filter(16000)

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
