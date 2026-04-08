"""Advanced single-file stem separation with second-stage sub-role classification.

Phase 3 — Two-stage separation pipeline
-----------------------------------------
Stage 1: Broad stem separation (existing Demucs / builtin)
Stage 2: Spectral/temporal analysis to derive richer sub-roles from each stem

Sub-role derivation targets
---------------------------
drums stem   → try to distinguish: kick / snare / hi_hat / percussion / cymbals
bass stem    → try to distinguish: bass vs 808
other stem   → try to distinguish: piano / keys / guitar / pads / strings / arp / melody

Degradation policy (Phase 3 spec)
----------------------------------
- Best case:   detailed sub-roles (kick, snare, hi_hat, 808, piano, …)
- Fallback:    grouped producer roles (drums, bass, melody, …)
- Worst case:  retain the broad 4-stem output unchanged

The system never hallucinates precision.  When isolation confidence is below
SUBROLE_MIN_CONFIDENCE the broad grouped role is used instead.

Feature flag
------------
This module is only invoked when settings.feature_advanced_stem_separation_v2 is True.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Any

from pydub import AudioSegment

from app.services.canonical_stem_manifest import (
    CANONICAL_TO_BROAD,
    CanonicalStemEntry,
    CanonicalStemManifest,
    SOURCE_AI_SEPARATED,
)
from app.services.stem_ingestion_router import SOURCE_MODE_SINGLE_FILE
from app.services.stem_separation import (
    StemSeparationResult,
    _builtin_stems,
    _export_segment_to_wav_bytes,
)
from app.services.storage import storage

logger = logging.getLogger(__name__)

# Minimum confidence required to promote a sub-role (below this → keep broad role)
SUBROLE_MIN_CONFIDENCE: float = 0.60


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SubRoleCandidate:
    """A candidate sub-role identified during second-stage analysis."""

    role: str
    broad_role: str
    confidence: float
    reason: str
    fallback: bool = False


@dataclass
class AdvancedSeparationResult:
    """Output of the advanced separation pipeline."""

    succeeded: bool
    backend: str
    stem_entries: list[CanonicalStemEntry] = field(default_factory=list)
    error: str | None = None

    def to_manifest(self, loop_id: int) -> CanonicalStemManifest:
        manifest = CanonicalStemManifest(
            source_mode=SOURCE_MODE_SINGLE_FILE, loop_id=loop_id
        )
        manifest.stems = list(self.stem_entries)
        return manifest


# ---------------------------------------------------------------------------
# Second-stage sub-role classifiers
# ---------------------------------------------------------------------------


def _classify_drums_subrole(audio: AudioSegment) -> SubRoleCandidate:
    """Attempt to classify a drums stem into a sub-role.

    Uses spectral band energy ratios and transient proxy to distinguish:
    kick (heavy sub-low, high transient) vs hi_hat (bright, sparse low) vs
    snare (mid-body transient) vs percussion (broad mid/hi).
    Falls back to "drums" when confidence is insufficient.
    """
    try:
        total_rms = max(1, audio.rms)

        sub = audio.low_pass_filter(100)
        low = audio.high_pass_filter(100).low_pass_filter(300)
        mid = audio.high_pass_filter(300).low_pass_filter(3000)
        hi = audio.high_pass_filter(3000)

        sub_r = max(1, sub.rms) / total_rms
        low_r = max(1, low.rms) / total_rms
        mid_r = max(1, mid.rms) / total_rms
        hi_r = max(1, hi.rms) / total_rms

        # Transient density proxy
        try:
            peak_ratio = max(1, audio.max) / total_rms
        except Exception:
            peak_ratio = 1.0

        low_energy = sub_r + low_r

        # Kick: dominant sub, strong transient
        if low_energy > 0.72 and peak_ratio > 5.0 and hi_r < 0.40:
            return SubRoleCandidate("kick", "drums", 0.72, "subrole:kick:sub_dominant+transient")

        # Hi-hat: bright, sparse low
        if hi_r > 0.70 and low_energy < 0.35:
            return SubRoleCandidate("hi_hat", "drums", 0.70, "subrole:hi_hat:bright_sparse_low")

        # Snare: mid-body energy with moderate transient
        if mid_r > 0.55 and peak_ratio > 3.5 and low_energy < 0.55:
            return SubRoleCandidate("snare", "drums", 0.65, "subrole:snare:mid_body_transient")

        # Percussion: broad spectrum, moderate transients
        if mid_r > 0.45 and hi_r > 0.30 and peak_ratio > 2.5:
            return SubRoleCandidate("percussion", "percussion", 0.62, "subrole:percussion:broad_mid_hi")

    except Exception as exc:  # pragma: no cover — audio analysis failures are non-fatal
        logger.debug("Drums sub-role analysis failed: %s", exc)

    return SubRoleCandidate("drums", "drums", 0.50, "subrole:drums:fallback", fallback=True)


def _classify_bass_subrole(audio: AudioSegment) -> SubRoleCandidate:
    """Attempt to distinguish bass vs 808 sub-role.

    808: very heavy sub (below 80 Hz), sustained, minimal high-frequency content.
    Bass: moderate sub+low energy with some mid presence.
    """
    try:
        total_rms = max(1, audio.rms)

        sub = audio.low_pass_filter(80)
        hi = audio.high_pass_filter(3000)

        sub_r = max(1, sub.rms) / total_rms
        hi_r = max(1, hi.rms) / total_rms

        # 808: extremely sub-heavy, barely any high-frequency content
        if sub_r > 0.85 and hi_r < 0.20:
            return SubRoleCandidate("808", "bass", 0.70, "subrole:808:sub_dominant")

    except Exception as exc:  # pragma: no cover
        logger.debug("Bass sub-role analysis failed: %s", exc)

    return SubRoleCandidate("bass", "bass", 0.72, "subrole:bass:fallback", fallback=False)


def _classify_other_subrole(audio: AudioSegment) -> SubRoleCandidate:
    """Attempt to classify the Demucs 'other' stem into a melodic sub-role.

    Targets: piano / guitar / pads / arp / melody
    Falls back to "melody" when confidence is low.
    """
    try:
        total_rms = max(1, audio.rms)

        sub = audio.low_pass_filter(80)
        low = audio.high_pass_filter(80).low_pass_filter(300)
        mid = audio.high_pass_filter(300).low_pass_filter(3000)
        hi = audio.high_pass_filter(3000)

        sub_r = max(1, sub.rms) / total_rms
        low_r = max(1, low.rms) / total_rms
        mid_r = max(1, mid.rms) / total_rms
        hi_r = max(1, hi.rms) / total_rms

        try:
            peak_ratio = max(1, audio.max) / total_rms
        except Exception:
            peak_ratio = 1.0

        low_energy = sub_r + low_r

        # Pads: sustained mid, sparse hi, very few transients
        if mid_r > 0.78 and hi_r < 0.45 and low_energy < 0.40 and peak_ratio < 3.0:
            return SubRoleCandidate("pads", "pads", 0.65, "subrole:pads:sustained_mid")

        # Guitar: bright mid attack, some hi presence, moderate transients
        if mid_r > 0.60 and hi_r > 0.45 and peak_ratio > 3.5 and low_energy < 0.35:
            return SubRoleCandidate("guitar", "melody", 0.63, "subrole:guitar:bright_mid_attack")

        # Arp: bright, repetitive (high peak ratio), sparse low
        if hi_r > 0.65 and peak_ratio > 5.0 and low_energy < 0.30:
            return SubRoleCandidate("arp", "melody", 0.62, "subrole:arp:bright_repetitive")

        # Piano: balanced mid+hi, moderate transients
        if mid_r > 0.55 and hi_r > 0.40 and peak_ratio > 3.0 and low_energy < 0.40:
            return SubRoleCandidate("piano", "melody", 0.61, "subrole:piano:balanced_tonal")

    except Exception as exc:  # pragma: no cover
        logger.debug("Other sub-role analysis failed: %s", exc)

    return SubRoleCandidate("melody", "melody", 0.55, "subrole:melody:fallback", fallback=True)


# ---------------------------------------------------------------------------
# Stage-2 dispatcher
# ---------------------------------------------------------------------------


def _second_stage_classify(
    stem_name: str, audio: AudioSegment
) -> SubRoleCandidate:
    """Route a broad Demucs stem to the appropriate sub-role classifier."""
    norm = stem_name.lower().strip()
    if norm == "drums":
        return _classify_drums_subrole(audio)
    if norm == "bass":
        return _classify_bass_subrole(audio)
    if norm in ("other", "melody"):
        return _classify_other_subrole(audio)
    # vocals → keep as "vocal" with high confidence
    if norm in ("vocals", "vocal"):
        return SubRoleCandidate("vocal", "vocals", 0.85, "subrole:vocal:direct_mapping")
    # Unknown — safe fallback
    return SubRoleCandidate(norm, CANONICAL_TO_BROAD.get(norm, norm), 0.60, "subrole:unknown:passthrough")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_advanced_separation(
    source_audio: AudioSegment,
    *,
    loop_id: int,
    source_key: str | None = None,
    backend: str = "builtin",
) -> AdvancedSeparationResult:
    """Run the two-stage advanced stem separation pipeline.

    Stage 1: Broad stem separation (builtin or future Demucs)
    Stage 2: Spectral analysis to derive richer sub-roles per stem

    Parameters
    ----------
    source_audio:
        The full audio to separate.
    loop_id:
        The owning loop ID (used for storage key naming).
    source_key:
        Original source storage key (for logging).
    backend:
        Separation backend identifier ("builtin" or future backends).

    Returns
    -------
    AdvancedSeparationResult with per-stem CanonicalStemEntry objects.
    """
    try:
        # ── Stage 1: broad separation ──────────────────────────────────────
        if backend in {"builtin", "mock"}:
            broad_stems = _builtin_stems(source_audio)
        else:
            raise ValueError(f"Unsupported advanced separation backend: {backend}")

        stem_entries: list[CanonicalStemEntry] = []

        for broad_name, stem_audio in broad_stems.items():
            # Persist stem to storage
            stem_key = f"stems/loop_{loop_id}_{broad_name}.wav"
            stem_bytes = _export_segment_to_wav_bytes(stem_audio)
            storage.upload_file(
                file_bytes=stem_bytes,
                content_type="audio/wav",
                key=stem_key,
            )

            # ── Stage 2: sub-role classification ──────────────────────────
            candidate = _second_stage_classify(broad_name, stem_audio)

            # Apply minimum-confidence guard: fall back to broad role if not confident
            if candidate.confidence < SUBROLE_MIN_CONFIDENCE:
                canonical_role = broad_name
                broad_role = CANONICAL_TO_BROAD.get(broad_name, broad_name)
                fallback = True
                confidence = candidate.confidence
                reason = f"{candidate.reason}→fallback_to_broad"
            else:
                canonical_role = candidate.role
                broad_role = candidate.broad_role
                fallback = candidate.fallback
                confidence = candidate.confidence
                reason = candidate.reason

            entry = CanonicalStemEntry(
                role=canonical_role,
                broad_role=broad_role,
                file_key=stem_key,
                confidence=round(confidence, 4),
                source_type=SOURCE_AI_SEPARATED,
                fallback=fallback,
                parent_broad_stem=broad_name if broad_name != canonical_role else None,
            )
            stem_entries.append(entry)

            logger.debug(
                "Advanced separation [loop=%s]: %s → sub_role=%s conf=%.2f reason=%s",
                loop_id,
                broad_name,
                canonical_role,
                confidence,
                reason,
            )

        return AdvancedSeparationResult(
            succeeded=True,
            backend=backend,
            stem_entries=stem_entries,
        )

    except Exception as exc:
        logger.warning(
            "Advanced stem separation failed for loop_id=%s source_key=%s: %s",
            loop_id,
            source_key,
            exc,
            exc_info=True,
        )
        return AdvancedSeparationResult(
            succeeded=False,
            backend=backend,
            error=str(exc),
        )
