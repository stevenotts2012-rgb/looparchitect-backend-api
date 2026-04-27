"""
Genre producer profiles for the Generative Producer System.

Each profile encodes real producer behaviour for a genre — what should
happen in each section type, how energy should curve, and what the drum,
bass, melody, and FX policies are.

No copyrighted material is referenced.  All profiles are described in
terms of procedural audio event patterns.
"""

from __future__ import annotations

from typing import Any

from app.services.generative_producer_system.types import GenreProducerProfile

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _section_behavior(
    *,
    drum_density: str = "medium",
    bass_active: bool = True,
    melody_active: bool = True,
    hat_roll: bool = False,
    filter_melody: bool = False,
    fx_riser: bool = False,
    impact: bool = False,
    dropout_roles: list[str] | None = None,
    bass_variation: bool = False,
    reverb_tail: bool = False,
    widen: bool = False,
    chop_melody: bool = False,
    energy: float = 0.5,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "drum_density": drum_density,
        "bass_active": bass_active,
        "melody_active": melody_active,
        "hat_roll": hat_roll,
        "filter_melody": filter_melody,
        "fx_riser": fx_riser,
        "impact": impact,
        "dropout_roles": dropout_roles or [],
        "bass_variation": bass_variation,
        "reverb_tail": reverb_tail,
        "widen": widen,
        "chop_melody": chop_melody,
        "energy": energy,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Trap
# ---------------------------------------------------------------------------

_TRAP_SECTIONS: dict[str, dict[str, Any]] = {
    "intro": _section_behavior(
        drum_density="sparse",
        bass_active=False,
        melody_active=True,
        filter_melody=True,
        energy=0.25,
        notes="Filtered melody only, no 808",
    ),
    "verse": _section_behavior(
        drum_density="medium",
        bass_active=True,
        melody_active=True,
        energy=0.5,
        notes="Simple drums, simple 808, melody reduced",
    ),
    "verse_2": _section_behavior(
        drum_density="medium",
        bass_active=True,
        melody_active=True,
        hat_roll=True,
        bass_variation=True,
        energy=0.55,
        notes="At least 2 behaviour changes vs verse 1",
    ),
    "pre_hook": _section_behavior(
        drum_density="dropout",
        bass_active=False,
        melody_active=True,
        fx_riser=True,
        dropout_roles=["drums"],
        energy=0.6,
        notes="Drop kick or anchor role before hook",
    ),
    "hook": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=True,
        hat_roll=True,
        bass_variation=True,
        impact=True,
        widen=True,
        energy=0.9,
        notes="Full melody, active 808, hat rolls, FX impact",
    ),
    "hook_2": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=True,
        hat_roll=True,
        bass_variation=True,
        impact=True,
        widen=True,
        chop_melody=True,
        energy=1.0,
        notes="Hook 2 is bigger than hook 1",
    ),
    "bridge": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        melody_active=True,
        filter_melody=True,
        energy=0.45,
        notes="Bridge resets tension",
    ),
    "breakdown": _section_behavior(
        drum_density="sparse",
        bass_active=False,
        melody_active=True,
        reverb_tail=True,
        energy=0.3,
    ),
    "outro": _section_behavior(
        drum_density="none",
        bass_active=False,
        melody_active=True,
        reverb_tail=True,
        energy=0.2,
        notes="Drums/808 removed, melody tail",
    ),
}

TRAP = GenreProducerProfile(
    genre="trap",
    section_behaviors=_TRAP_SECTIONS,
    energy_curve_policy="steep_rise_to_hook",
    drum_policy="trap_808_hi_hats",
    bass_policy="808_sub_bass",
    melody_policy="sparse_melodic_chops",
    fx_policy="riser_before_drop",
    variation_policy="hi_hat_rolls_and_fills",
)

# ---------------------------------------------------------------------------
# Drill
# ---------------------------------------------------------------------------

_DRILL_SECTIONS: dict[str, dict[str, Any]] = {
    "intro": _section_behavior(
        drum_density="sparse",
        bass_active=False,
        melody_active=True,
        filter_melody=True,
        energy=0.2,
    ),
    "verse": _section_behavior(
        drum_density="medium",
        bass_active=True,
        bass_variation=True,
        melody_active=True,
        energy=0.5,
        notes="Longer verse, sliding 808 emphasis, sparse but aggressive drums",
    ),
    "verse_2": _section_behavior(
        drum_density="medium",
        bass_active=True,
        bass_variation=True,
        melody_active=True,
        hat_roll=True,
        energy=0.55,
    ),
    "pre_hook": _section_behavior(
        drum_density="dropout",
        bass_active=True,
        bass_variation=True,
        melody_active=False,
        fx_riser=True,
        energy=0.65,
        notes="Tension-focused transition with sliding low-end",
    ),
    "hook": _section_behavior(
        drum_density="full",
        bass_active=True,
        bass_variation=True,
        melody_active=True,
        impact=True,
        energy=0.85,
        notes="Darker re-entry, sliding low-end",
    ),
    "hook_2": _section_behavior(
        drum_density="full",
        bass_active=True,
        bass_variation=True,
        melody_active=True,
        hat_roll=True,
        impact=True,
        energy=0.95,
    ),
    "bridge": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        bass_variation=True,
        melody_active=True,
        energy=0.4,
    ),
    "breakdown": _section_behavior(
        drum_density="none",
        bass_active=False,
        melody_active=True,
        reverb_tail=True,
        energy=0.25,
    ),
    "outro": _section_behavior(
        drum_density="none",
        bass_active=False,
        melody_active=True,
        reverb_tail=True,
        energy=0.15,
    ),
}

DRILL = GenreProducerProfile(
    genre="drill",
    section_behaviors=_DRILL_SECTIONS,
    energy_curve_policy="slow_build_with_tension",
    drum_policy="sparse_aggressive_syncopated",
    bass_policy="sliding_808_bass",
    melody_policy="dark_melodic_minimal",
    fx_policy="dark_transition_sweeps",
    variation_policy="syncopated_hats_and_percs",
)

# ---------------------------------------------------------------------------
# R&B
# ---------------------------------------------------------------------------

_RNB_SECTIONS: dict[str, dict[str, Any]] = {
    "intro": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        melody_active=True,
        filter_melody=True,
        energy=0.3,
    ),
    "verse": _section_behavior(
        drum_density="medium",
        bass_active=True,
        melody_active=True,
        energy=0.5,
        notes="Melody/chord focused, smoother drums",
    ),
    "verse_2": _section_behavior(
        drum_density="medium",
        bass_active=True,
        melody_active=True,
        widen=True,
        energy=0.55,
    ),
    "pre_hook": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        melody_active=True,
        reverb_tail=True,
        energy=0.6,
        notes="Reverb/delay fade into hook",
    ),
    "hook": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=True,
        widen=True,
        reverb_tail=False,
        energy=0.85,
        notes="Expands chords/melody",
    ),
    "hook_2": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=True,
        widen=True,
        chop_melody=True,
        energy=0.9,
    ),
    "bridge": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        melody_active=True,
        reverb_tail=True,
        widen=True,
        energy=0.55,
        notes="Bridge more important — expands harmonic space",
    ),
    "breakdown": _section_behavior(
        drum_density="none",
        bass_active=False,
        melody_active=True,
        reverb_tail=True,
        energy=0.3,
    ),
    "outro": _section_behavior(
        drum_density="sparse",
        bass_active=False,
        melody_active=True,
        reverb_tail=True,
        energy=0.2,
    ),
}

RNB = GenreProducerProfile(
    genre="rnb",
    section_behaviors=_RNB_SECTIONS,
    energy_curve_policy="smooth_warm_lift",
    drum_policy="smooth_groove_drums",
    bass_policy="warm_bass_groove",
    melody_policy="chord_melody_focused",
    fx_policy="reverb_delay_fades",
    variation_policy="harmonic_expansion",
)

# ---------------------------------------------------------------------------
# Rage
# ---------------------------------------------------------------------------

_RAGE_SECTIONS: dict[str, dict[str, Any]] = {
    "intro": _section_behavior(
        drum_density="medium",
        bass_active=True,
        melody_active=True,
        energy=0.5,
        notes="Faster entry",
    ),
    "verse": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=True,
        hat_roll=True,
        energy=0.7,
        notes="Aggressive drums/hats, shorter sections",
    ),
    "verse_2": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=True,
        hat_roll=True,
        bass_variation=True,
        energy=0.75,
    ),
    "pre_hook": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=False,
        fx_riser=True,
        impact=True,
        energy=0.8,
    ),
    "hook": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=True,
        hat_roll=True,
        impact=True,
        widen=True,
        energy=1.0,
        notes="High-energy hook, distortion/bitcrush",
    ),
    "hook_2": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=True,
        hat_roll=True,
        impact=True,
        widen=True,
        chop_melody=True,
        energy=1.0,
    ),
    "bridge": _section_behavior(
        drum_density="medium",
        bass_active=True,
        melody_active=True,
        energy=0.65,
    ),
    "breakdown": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        melody_active=False,
        energy=0.5,
    ),
    "outro": _section_behavior(
        drum_density="sparse",
        bass_active=False,
        melody_active=True,
        energy=0.3,
    ),
}

RAGE = GenreProducerProfile(
    genre="rage",
    section_behaviors=_RAGE_SECTIONS,
    energy_curve_policy="high_energy_throughout",
    drum_policy="aggressive_fast_hats",
    bass_policy="heavy_distorted_bass",
    melody_policy="aggressive_chops",
    fx_policy="impact_and_distortion",
    variation_policy="fast_variation_with_impact",
)

# ---------------------------------------------------------------------------
# West Coast
# ---------------------------------------------------------------------------

_WEST_COAST_SECTIONS: dict[str, dict[str, Any]] = {
    "intro": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        melody_active=True,
        energy=0.3,
    ),
    "verse": _section_behavior(
        drum_density="medium",
        bass_active=True,
        bass_variation=True,
        melody_active=True,
        energy=0.5,
        notes="Bounce-focused drums, bass groove",
    ),
    "verse_2": _section_behavior(
        drum_density="medium",
        bass_active=True,
        bass_variation=True,
        melody_active=True,
        hat_roll=True,
        energy=0.55,
        notes="Call-and-response elements",
    ),
    "pre_hook": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        melody_active=True,
        fx_riser=True,
        energy=0.65,
    ),
    "hook": _section_behavior(
        drum_density="full",
        bass_active=True,
        bass_variation=True,
        melody_active=True,
        widen=True,
        energy=0.85,
        notes="Smooth hook lift with percussion accents",
    ),
    "hook_2": _section_behavior(
        drum_density="full",
        bass_active=True,
        bass_variation=True,
        melody_active=True,
        widen=True,
        impact=True,
        energy=0.9,
    ),
    "bridge": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        melody_active=True,
        energy=0.45,
    ),
    "breakdown": _section_behavior(
        drum_density="sparse",
        bass_active=False,
        melody_active=True,
        reverb_tail=True,
        energy=0.3,
    ),
    "outro": _section_behavior(
        drum_density="sparse",
        bass_active=False,
        melody_active=True,
        reverb_tail=True,
        energy=0.2,
    ),
}

WEST_COAST = GenreProducerProfile(
    genre="west_coast",
    section_behaviors=_WEST_COAST_SECTIONS,
    energy_curve_policy="bouncy_groove_with_smooth_lift",
    drum_policy="bounce_groove_drums",
    bass_policy="groove_bass_changes",
    melody_policy="call_response_melody",
    fx_policy="smooth_transitions",
    variation_policy="percussion_accents",
)

# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------

_GENERIC_SECTIONS: dict[str, dict[str, Any]] = {
    "intro": _section_behavior(
        drum_density="sparse",
        bass_active=False,
        melody_active=True,
        energy=0.2,
    ),
    "verse": _section_behavior(
        drum_density="medium",
        bass_active=True,
        melody_active=True,
        energy=0.5,
    ),
    "verse_2": _section_behavior(
        drum_density="medium",
        bass_active=True,
        melody_active=True,
        energy=0.55,
    ),
    "pre_hook": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        melody_active=True,
        fx_riser=True,
        energy=0.6,
    ),
    "hook": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=True,
        energy=0.8,
    ),
    "hook_2": _section_behavior(
        drum_density="full",
        bass_active=True,
        melody_active=True,
        widen=True,
        energy=0.85,
    ),
    "bridge": _section_behavior(
        drum_density="sparse",
        bass_active=True,
        melody_active=True,
        energy=0.4,
    ),
    "breakdown": _section_behavior(
        drum_density="none",
        bass_active=False,
        melody_active=True,
        energy=0.25,
    ),
    "outro": _section_behavior(
        drum_density="none",
        bass_active=False,
        melody_active=True,
        reverb_tail=True,
        energy=0.15,
    ),
}

GENERIC = GenreProducerProfile(
    genre="generic",
    section_behaviors=_GENERIC_SECTIONS,
    energy_curve_policy="simple_contrast",
    drum_policy="safe_drums",
    bass_policy="simple_bass",
    melody_policy="simple_melody",
    fx_policy="minimal_fx",
    variation_policy="safe_variation",
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, GenreProducerProfile] = {
    "trap": TRAP,
    "drill": DRILL,
    "rnb": RNB,
    "rage": RAGE,
    "west_coast": WEST_COAST,
    "generic": GENERIC,
}


def get_genre_profile(genre: str) -> GenreProducerProfile:
    """Return the GenreProducerProfile for *genre*, falling back to generic."""
    key = (genre or "generic").lower().strip()
    return _REGISTRY.get(key, GENERIC)


def list_supported_genres() -> list[str]:
    """Return sorted list of supported genre keys."""
    return sorted(_REGISTRY.keys())
