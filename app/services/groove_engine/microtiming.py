"""
Microtiming module for the Groove Engine.

Provides deterministic, safe microtiming offset calculations for each
instrument role.  All values stay within the safe musical bounds defined
in ``types.py`` to prevent flamming or broken rhythmic relationships.

Rules summary
-------------
* Hats may push slightly ahead (negative offset) or sit slightly behind —
  the exact amount depends on the groove profile and section energy.
* Snare lays back behind the beat — adds relaxed pocket feel.
* Kick stays tighter than hats unless the profile is explicitly loose (drill/halftime).
* Bass lags slightly for warmth and sub-bass separation from kick.
* Percussion follows a scaled version of hat offset.

All calculations use only arithmetic on profile floats — no randomness.
"""

from __future__ import annotations

from typing import Optional

from app.services.groove_engine.types import GrooveProfile


# ---------------------------------------------------------------------------
# Per-role offset calculators
# ---------------------------------------------------------------------------

def hat_timing_offset(
    profile: GrooveProfile,
    energy: float,
    occurrence: int = 1,
) -> float:
    """Return deterministic hi-hat microtiming offset in milliseconds.

    Negative = push ahead (forward energy).
    Positive = lag behind (laid-back feel).

    The final value is scaled by energy so higher-energy sections push harder.

    Parameters
    ----------
    profile:
        Active groove profile.
    energy:
        Section energy [0.0, 1.0].
    occurrence:
        1-based section occurrence index.  Repeated sections get a slightly
        different feel via a small deterministic nudge.
    """
    base = profile.hat_push_ms
    # Scale by energy: high energy → push more aggressively
    energy_scale = 0.7 + (energy * 0.6)
    # Occurrence nudge: each repeated occurrence adds a tiny deterministic offset
    occurrence_nudge = (occurrence - 1) * 0.5
    offset = (base * energy_scale) - occurrence_nudge
    # Clamp to safe range
    return max(-15.0, min(15.0, offset))


def snare_timing_offset(
    profile: GrooveProfile,
    energy: float,
    occurrence: int = 1,
) -> float:
    """Return deterministic snare layback offset in milliseconds (>= 0).

    Snare always lays behind the beat (positive value).  The amount
    increases slightly with occurrence to differentiate repeated sections.

    Parameters
    ----------
    profile:
        Active groove profile.
    energy:
        Section energy [0.0, 1.0].
    occurrence:
        1-based section occurrence index.
    """
    base = profile.snare_layback_ms
    # Low energy = more laid-back; high energy = tighter
    energy_scale = 1.2 - (energy * 0.4)
    occurrence_nudge = (occurrence - 1) * 0.8
    offset = (base * energy_scale) + occurrence_nudge
    return max(0.0, min(12.0, offset))


def kick_timing_offset(
    profile: GrooveProfile,
    energy: float,
) -> float:
    """Return deterministic kick timing offset in milliseconds.

    Kick stays tighter than hats — mostly near zero unless the profile
    explicitly loosens it (e.g. halftime_bridge, aggressive_drill).

    Negative = slightly ahead (adds punch).
    Positive = slightly behind (adds weight).
    """
    # Tightness → near-zero offset; looseness → slight ahead nudge for punch
    looseness = 1.0 - profile.kick_tightness
    offset = -(looseness * 4.0 * energy)  # push ahead when loose + high energy
    return max(-6.0, min(6.0, offset))


def bass_timing_offset(
    profile: GrooveProfile,
    energy: float,
) -> float:
    """Return deterministic bass lag offset in milliseconds (>= 0).

    Bass lags slightly to sit under the kick — adds warmth and sub separation.
    The lag is conservative and always positive.
    """
    base = profile.bass_lag_ms
    # Reduce lag at very high energy to keep bass punchy in hooks
    energy_scale = 1.0 - (energy * 0.3)
    offset = base * energy_scale
    return max(0.0, min(10.0, offset))


def percussion_timing_offset(
    profile: GrooveProfile,
    energy: float,
    occurrence: int = 1,
) -> float:
    """Return deterministic percussion microtiming offset in milliseconds.

    Percussion follows a scaled version of hat offset — it moves with hats
    but with reduced magnitude to prevent overcrowding.
    """
    hat_offset = hat_timing_offset(profile, energy, occurrence)
    # Percussion moves at ~60% of hat magnitude
    offset = hat_offset * 0.6
    return max(-12.0, min(12.0, offset))


# ---------------------------------------------------------------------------
# Role dispatcher
# ---------------------------------------------------------------------------

def get_timing_offset_for_role(
    role: str,
    profile: GrooveProfile,
    energy: float,
    occurrence: int = 1,
) -> Optional[float]:
    """Return deterministic microtiming offset for *role*, or ``None`` if not applicable.

    Returns ``None`` when a role should not receive an explicit timing nudge
    (e.g. melody, harmony) — callers should omit ``timing_offset_ms`` in that case.

    Parameters
    ----------
    role:
        Instrument role name (e.g. ``"drums"``, ``"bass"``).
    profile:
        Active groove profile.
    energy:
        Section energy [0.0, 1.0].
    occurrence:
        1-based section occurrence index.
    """
    role_lower = role.lower()

    if "hat" in role_lower or "hi-hat" in role_lower or "hihat" in role_lower:
        return hat_timing_offset(profile, energy, occurrence)

    if "snare" in role_lower:
        return snare_timing_offset(profile, energy, occurrence)

    if "kick" in role_lower:
        return kick_timing_offset(profile, energy)

    if "bass" in role_lower:
        return bass_timing_offset(profile, energy)

    if "perc" in role_lower:
        return percussion_timing_offset(profile, energy, occurrence)

    if role_lower == "drums":
        # Generic drums role: use hat push as the representative offset
        return hat_timing_offset(profile, energy, occurrence)

    # Melody, harmony, pads, fx, vocals — no explicit timing nudge
    return None


# ---------------------------------------------------------------------------
# Source quality safety wrapper
# ---------------------------------------------------------------------------

def safe_offset(
    role: str,
    profile: GrooveProfile,
    energy: float,
    occurrence: int,
    source_quality: str,
) -> Optional[float]:
    """Return a timing offset appropriate for *source_quality*.

    * ``true_stems`` / ``zip_stems``: full microtiming applied.
    * ``ai_separated``: offsets halved to reduce risk on uncertain material.
    * ``stereo_fallback``: always returns ``None`` (no microtiming claims).
    """
    if source_quality == "stereo_fallback":
        return None

    offset = get_timing_offset_for_role(role, profile, energy, occurrence)

    if offset is None:
        return None

    if source_quality == "ai_separated":
        # Halve the offset to be conservative with AI-separated stems
        offset = offset * 0.5

    # Round to 1 decimal to avoid spurious precision
    return round(offset, 1)
