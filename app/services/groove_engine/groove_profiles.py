"""
Named groove profiles for the Groove Engine.

Each profile defines the full feel characteristics for a section type:
swing, microtiming behaviour, accent density, and section suitability.

All profiles are deterministic constants — they never use random values.
"""

from __future__ import annotations

from typing import Dict, Optional

from app.services.groove_engine.types import GrooveProfile


# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------

# Ordered list of all built-in profiles.
_PROFILES: Dict[str, GrooveProfile] = {}


def _register(profile: GrooveProfile) -> GrooveProfile:
    _PROFILES[profile.name] = profile
    return profile


# ---------------------------------------------------------------------------
# Individual profiles
# ---------------------------------------------------------------------------

sparse_intro = _register(GrooveProfile(
    name="sparse_intro",
    swing_amount=0.05,
    hat_push_ms=0.0,
    snare_layback_ms=0.0,
    kick_tightness=0.95,
    accent_density=0.1,
    bass_lag_ms=0.0,
    section_bias="intro",
    notes=(
        "Minimal movement, atmosphere-first. "
        "Straight timing with almost no swing. "
        "Low accent density — let the listener settle in."
    ),
))

steady_verse = _register(GrooveProfile(
    name="steady_verse",
    swing_amount=0.15,
    hat_push_ms=-3.0,
    snare_layback_ms=4.0,
    kick_tightness=0.90,
    accent_density=0.35,
    bass_lag_ms=3.0,
    section_bias="verse",
    notes=(
        "Stable, moderate groove. "
        "Slight hat push keeps forward momentum. "
        "Light snare layback gives a relaxed pocket. "
        "Suits first verse — confident without over-animating."
    ),
))

bounce_verse = _register(GrooveProfile(
    name="bounce_verse",
    swing_amount=0.28,
    hat_push_ms=-5.0,
    snare_layback_ms=6.0,
    kick_tightness=0.85,
    accent_density=0.50,
    bass_lag_ms=5.0,
    section_bias="verse",
    notes=(
        "More groove complexity than steady_verse. "
        "Increased swing and hat push creates a bouncy feel. "
        "Suits Verse 2 or higher — builds on the established pocket."
    ),
))

tension_pre_hook = _register(GrooveProfile(
    name="tension_pre_hook",
    swing_amount=0.10,
    hat_push_ms=-8.0,
    snare_layback_ms=2.0,
    kick_tightness=0.95,
    accent_density=0.20,
    bass_lag_ms=1.0,
    section_bias="pre_hook",
    notes=(
        "Reduced density creates anticipation. "
        "Tight kick and minimal swing give a compressed, leaning feel. "
        "Hat push forward makes everything feel impatient for the hook."
    ),
))

explosive_hook = _register(GrooveProfile(
    name="explosive_hook",
    swing_amount=0.20,
    hat_push_ms=-8.0,
    snare_layback_ms=8.0,
    kick_tightness=0.88,
    accent_density=0.75,
    bass_lag_ms=6.0,
    section_bias="hook",
    notes=(
        "Confident drum pocket with controlled energy lift. "
        "Strong hat push against snare layback creates maximum groove tension. "
        "High accent density rewards the listener after the pre-hook build."
    ),
))

halftime_bridge = _register(GrooveProfile(
    name="halftime_bridge",
    swing_amount=0.25,
    hat_push_ms=2.0,
    snare_layback_ms=10.0,
    kick_tightness=0.75,
    accent_density=0.25,
    bass_lag_ms=8.0,
    section_bias="bridge",
    notes=(
        "Deliberate half-time feel. "
        "Deep snare layback and loose kick tightness give a heavy, slow groove. "
        "Reduced accent density creates space and resets momentum."
    ),
))

stripped_outro = _register(GrooveProfile(
    name="stripped_outro",
    swing_amount=0.08,
    hat_push_ms=0.0,
    snare_layback_ms=2.0,
    kick_tightness=0.92,
    accent_density=0.12,
    bass_lag_ms=2.0,
    section_bias="outro",
    notes=(
        "Minimal motion — energy release. "
        "Near-straight timing with very low accent density. "
        "Let the arrangement breathe out naturally."
    ),
))

dark_trap = _register(GrooveProfile(
    name="dark_trap",
    swing_amount=0.12,
    hat_push_ms=-6.0,
    snare_layback_ms=5.0,
    kick_tightness=0.80,
    accent_density=0.55,
    bass_lag_ms=7.0,
    section_bias="verse",
    notes=(
        "Trap pocket: tight 808 bass lag with loose kick. "
        "Slightly dragged snare against a forward hat creates dark urgency. "
        "Works on verse and hook for trap / drill-influenced arrangements."
    ),
))

melodic_bounce = _register(GrooveProfile(
    name="melodic_bounce",
    swing_amount=0.35,
    hat_push_ms=-4.0,
    snare_layback_ms=7.0,
    kick_tightness=0.82,
    accent_density=0.60,
    bass_lag_ms=4.0,
    section_bias="hook",
    notes=(
        "High swing with moderate microtiming for melodic / bouncy styles. "
        "Snare layback against swing creates a bobbing, melodic trap feel. "
        "Suits melodic rap, R&B, and bounce-oriented hooks."
    ),
))

aggressive_drill = _register(GrooveProfile(
    name="aggressive_drill",
    swing_amount=0.08,
    hat_push_ms=-12.0,
    snare_layback_ms=3.0,
    kick_tightness=0.70,
    accent_density=0.65,
    bass_lag_ms=8.0,
    section_bias="hook",
    notes=(
        "UK / Chicago drill aesthetic: maximum hat push, very loose kick, "
        "deep bass lag. Near-straight swing keeps the grid aggressive. "
        "High accent density drives relentless forward motion."
    ),
))


# ---------------------------------------------------------------------------
# Profile selection helpers
# ---------------------------------------------------------------------------

# Primary section-type → profile mapping.
# Higher-occurrence hooks and verses use different profiles; the selector
# function handles escalation logic via the occurrence parameter.
_PRIMARY_PROFILE_MAP: Dict[str, str] = {
    "intro": "sparse_intro",
    "verse": "steady_verse",
    "pre_hook": "tension_pre_hook",
    "hook": "explosive_hook",
    "bridge": "halftime_bridge",
    "breakdown": "halftime_bridge",
    "outro": "stripped_outro",
}

# Escalation map: for repeated hooks / verses choose a richer profile.
_ESCALATION_MAP: Dict[str, Dict[int, str]] = {
    "verse": {
        1: "steady_verse",
        2: "bounce_verse",
    },
    "hook": {
        1: "explosive_hook",
        2: "melodic_bounce",
        3: "aggressive_drill",
    },
}


def get_profile(name: str) -> Optional[GrooveProfile]:
    """Return the named :class:`GrooveProfile` or ``None`` if not found."""
    return _PROFILES.get(name)


def get_profile_for_section(
    section_type: str,
    occurrence: int = 1,
    energy: float = 0.5,
    source_quality: str = "true_stems",
) -> GrooveProfile:
    """Return the most appropriate :class:`GrooveProfile` for a section.

    Parameters
    ----------
    section_type:
        Canonical section type (e.g. ``"verse"``, ``"hook"``).
    occurrence:
        1-based occurrence index within the section type.
    energy:
        Section energy level [0.0, 1.0].
    source_quality:
        Source quality mode.  Weak sources fall back to conservative profiles.

    Returns
    -------
    GrooveProfile
        Always returns a valid profile — never raises.
    """
    # Weak sources: always use the most conservative profile for the section type.
    if source_quality == "stereo_fallback":
        conservative_map = {
            "intro": "sparse_intro",
            "verse": "steady_verse",
            "pre_hook": "tension_pre_hook",
            "hook": "steady_verse",
            "bridge": "stripped_outro",
            "breakdown": "stripped_outro",
            "outro": "stripped_outro",
        }
        name = conservative_map.get(section_type, "steady_verse")
        return _PROFILES[name]

    # Check escalation map first.
    escalation = _ESCALATION_MAP.get(section_type)
    if escalation:
        # Use the highest occurrence key that is <= actual occurrence.
        for occ in sorted(escalation.keys(), reverse=True):
            if occurrence >= occ:
                return _PROFILES[escalation[occ]]

    # Fall back to the primary map.
    name = _PRIMARY_PROFILE_MAP.get(section_type, "steady_verse")
    return _PROFILES[name]


def list_profiles() -> Dict[str, GrooveProfile]:
    """Return a copy of the full profile registry."""
    return dict(_PROFILES)
