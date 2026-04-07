"""Arrangement preset system.

Defines genre-specific preset configurations that override the default
per-section identity profiles in section_identity_engine.py.

Each preset specifies:
- Role priority ordering per section type (most-preferred first)
- Density targets (min/max active roles) per section type
- Default transition styles per section type

Presets are applied via ``get_effective_profile()`` in section_identity_engine.py
and threaded through arrangement_planner.py and arrangement_jobs.py.

Supported presets: trap (default), drill, cinematic, lofi, house, afrobeats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

DEFAULT_PRESET = "trap"

VALID_PRESETS = frozenset({"trap", "drill", "cinematic", "lofi", "house", "afrobeats"})


@dataclass(frozen=True)
class PresetSectionOverride:
    """Partial override for a single section type within a preset.

    Fields left as ``None`` fall back to the base ``SectionProfile`` value
    defined in ``SECTION_PROFILES`` in ``section_identity_engine.py``.
    """

    role_priorities: Optional[tuple[str, ...]] = None
    density_min: Optional[int] = None
    density_max: Optional[int] = None
    forbidden_roles: Optional[frozenset[str]] = None
    default_transition_in: Optional[str] = None
    default_transition_out: Optional[str] = None


@dataclass(frozen=True)
class ArrangementPresetConfig:
    """Full preset configuration applied across all sections of an arrangement."""

    name: str
    description: str
    # Per section-type overrides.  Only the provided section keys are overridden;
    # sections not listed keep their base profile values.
    section_overrides: dict[str, PresetSectionOverride] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

ARRANGEMENT_PRESETS: dict[str, ArrangementPresetConfig] = {

    # ---- Trap ----------------------------------------------------------------
    # Drums and 808 bass dominate; sparse intro/outro; melody rides over groove.
    # This mirrors the existing SECTION_PROFILES defaults most closely and is
    # used as the fallback when no preset is specified.
    "trap": ArrangementPresetConfig(
        name="trap",
        description="Hard-hitting drums and 808 bass; sparse intro, dense hook.",
        section_overrides={
            "intro": PresetSectionOverride(
                role_priorities=("pads", "fx", "melody", "arp", "vocal", "synth"),
                density_min=1,
                density_max=2,
                default_transition_in="none",
                default_transition_out="drum_fill",
            ),
            "verse": PresetSectionOverride(
                role_priorities=("drums", "bass", "melody", "vocal", "synth", "percussion", "arp", "pads"),
                density_min=2,
                density_max=3,
                default_transition_in="drum_fill",
                default_transition_out="lift",
            ),
            "pre_hook": PresetSectionOverride(
                role_priorities=("bass", "arp", "fx", "percussion", "melody", "vocal", "synth"),
                density_min=2,
                density_max=3,
                default_transition_in="fx_rise",
                default_transition_out="pull_back",
            ),
            "hook": PresetSectionOverride(
                role_priorities=("drums", "bass", "melody", "synth", "vocal", "percussion", "arp", "pads", "fx"),
                density_min=3,
                density_max=5,
                default_transition_in="bass_drop",
                default_transition_out="drum_fill",
            ),
            "bridge": PresetSectionOverride(
                role_priorities=("pads", "fx", "melody", "vocal", "arp", "synth"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "bass", "percussion"}),
                default_transition_in="mute_drop",
                default_transition_out="riser",
            ),
            "breakdown": PresetSectionOverride(
                role_priorities=("pads", "fx", "vocal", "arp", "melody", "synth"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "bass", "percussion"}),
                default_transition_in="silence_drop",
                default_transition_out="riser",
            ),
            "outro": PresetSectionOverride(
                role_priorities=("pads", "fx", "melody", "arp", "vocal"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "bass", "percussion"}),
                default_transition_in="crossfade",
                default_transition_out="none",
            ),
        },
    ),

    # ---- Drill ---------------------------------------------------------------
    # Minimal verse with sliding 808 bass; low density throughout; slow hook build.
    "drill": ArrangementPresetConfig(
        name="drill",
        description="Sparse verses with sliding 808 bass; minimal melody; heavy hook.",
        section_overrides={
            "intro": PresetSectionOverride(
                role_priorities=("bass", "pads", "fx", "synth"),
                density_min=1,
                density_max=2,
                default_transition_in="none",
                default_transition_out="drum_fill",
            ),
            "verse": PresetSectionOverride(
                role_priorities=("drums", "bass", "percussion", "synth", "melody", "pads"),
                density_min=2,
                density_max=2,
                default_transition_in="drum_fill",
                default_transition_out="lift",
            ),
            "pre_hook": PresetSectionOverride(
                role_priorities=("bass", "drums", "fx", "arp"),
                density_min=2,
                density_max=3,
                default_transition_in="fx_rise",
                default_transition_out="pull_back",
            ),
            "hook": PresetSectionOverride(
                role_priorities=("bass", "drums", "melody", "synth", "vocal", "fx"),
                density_min=3,
                density_max=4,
                default_transition_in="bass_drop",
                default_transition_out="drum_fill",
            ),
            "bridge": PresetSectionOverride(
                role_priorities=("pads", "bass", "fx", "synth"),
                density_min=1,
                density_max=2,
                default_transition_in="mute_drop",
                default_transition_out="riser",
            ),
            "breakdown": PresetSectionOverride(
                role_priorities=("bass", "fx", "pads", "synth"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "percussion"}),
                default_transition_in="silence_drop",
                default_transition_out="riser",
            ),
            "outro": PresetSectionOverride(
                role_priorities=("bass", "pads", "fx", "synth"),
                density_min=1,
                density_max=2,
                default_transition_in="crossfade",
                default_transition_out="none",
            ),
        },
    ),

    # ---- Cinematic -----------------------------------------------------------
    # Orchestral/filmic; pads and melody carry all sections; no drums anywhere;
    # dynamics achieved through density and texture swaps rather than groove.
    "cinematic": ArrangementPresetConfig(
        name="cinematic",
        description="Orchestral feel; pads/strings/melody throughout; no rhythmic groove.",
        section_overrides={
            "intro": PresetSectionOverride(
                role_priorities=("pads", "melody", "synth", "arp", "fx"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "bass", "percussion"}),
                default_transition_in="none",
                default_transition_out="riser",
            ),
            "verse": PresetSectionOverride(
                role_priorities=("melody", "pads", "synth", "arp", "vocal", "fx"),
                density_min=2,
                density_max=3,
                forbidden_roles=frozenset({"drums", "bass", "percussion"}),
                default_transition_in="riser",
                default_transition_out="riser",
            ),
            "pre_hook": PresetSectionOverride(
                role_priorities=("melody", "pads", "arp", "fx", "synth"),
                density_min=2,
                density_max=3,
                forbidden_roles=frozenset({"drums", "bass", "percussion"}),
                default_transition_in="fx_rise",
                default_transition_out="riser",
            ),
            "hook": PresetSectionOverride(
                role_priorities=("melody", "pads", "synth", "vocal", "arp", "fx"),
                density_min=3,
                density_max=4,
                forbidden_roles=frozenset({"drums", "bass", "percussion"}),
                default_transition_in="fx_hit",
                default_transition_out="riser",
            ),
            "bridge": PresetSectionOverride(
                role_priorities=("pads", "fx", "synth", "arp"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "bass", "percussion"}),
                default_transition_in="mute_drop",
                default_transition_out="riser",
            ),
            "breakdown": PresetSectionOverride(
                role_priorities=("pads", "fx", "arp", "synth"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "bass", "percussion"}),
                default_transition_in="silence_drop",
                default_transition_out="riser",
            ),
            "outro": PresetSectionOverride(
                role_priorities=("pads", "melody", "arp", "fx", "synth"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "bass", "percussion"}),
                default_transition_in="crossfade",
                default_transition_out="none",
            ),
        },
    ),

    # ---- Lo-Fi ---------------------------------------------------------------
    # Warm, chill; keys/melody dominant; very sparse; no aggressive FX.
    "lofi": ArrangementPresetConfig(
        name="lofi",
        description="Warm and sparse; melody/pads lead; minimal FX; no drums in bridge/outro.",
        section_overrides={
            "intro": PresetSectionOverride(
                role_priorities=("pads", "melody", "synth"),
                density_min=1,
                density_max=2,
                default_transition_in="none",
                default_transition_out="none",
            ),
            "verse": PresetSectionOverride(
                role_priorities=("melody", "pads", "bass", "drums", "synth"),
                density_min=2,
                density_max=3,
                default_transition_in="none",
                default_transition_out="none",
            ),
            "pre_hook": PresetSectionOverride(
                role_priorities=("melody", "bass", "pads", "synth"),
                density_min=2,
                density_max=3,
                default_transition_in="none",
                default_transition_out="none",
            ),
            "hook": PresetSectionOverride(
                role_priorities=("melody", "pads", "bass", "drums", "synth", "vocal"),
                density_min=2,
                density_max=3,
                default_transition_in="drum_fill",
                default_transition_out="none",
            ),
            "bridge": PresetSectionOverride(
                role_priorities=("pads", "melody", "synth"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "bass", "percussion", "fx", "arp"}),
                default_transition_in="none",
                default_transition_out="none",
            ),
            "breakdown": PresetSectionOverride(
                role_priorities=("pads", "melody", "synth"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "bass", "percussion", "fx"}),
                default_transition_in="none",
                default_transition_out="none",
            ),
            "outro": PresetSectionOverride(
                role_priorities=("pads", "melody", "synth"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "percussion"}),
                default_transition_in="none",
                default_transition_out="none",
            ),
        },
    ),

    # ---- House ---------------------------------------------------------------
    # Four-on-the-floor groove; kick-snare heavy; energy builds through verse to hook.
    "house": ArrangementPresetConfig(
        name="house",
        description="Four-on-the-floor groove; kick/bass dominant; energy builds to hook.",
        section_overrides={
            "intro": PresetSectionOverride(
                role_priorities=("drums", "bass", "pads", "fx", "synth"),
                density_min=2,
                density_max=3,
                default_transition_in="none",
                default_transition_out="drum_fill",
            ),
            "verse": PresetSectionOverride(
                role_priorities=("drums", "bass", "pads", "melody", "synth", "fx"),
                density_min=3,
                density_max=4,
                default_transition_in="drum_fill",
                default_transition_out="fx_rise",
            ),
            "pre_hook": PresetSectionOverride(
                role_priorities=("drums", "bass", "fx", "arp", "synth"),
                density_min=3,
                density_max=4,
                default_transition_in="fx_rise",
                default_transition_out="fx_hit",
            ),
            "hook": PresetSectionOverride(
                role_priorities=("drums", "bass", "melody", "pads", "synth", "fx", "vocal"),
                density_min=4,
                density_max=5,
                default_transition_in="fx_hit",
                default_transition_out="drum_fill",
            ),
            "bridge": PresetSectionOverride(
                role_priorities=("pads", "bass", "fx", "synth"),
                density_min=2,
                density_max=3,
                default_transition_in="mute_drop",
                default_transition_out="fx_rise",
            ),
            "breakdown": PresetSectionOverride(
                role_priorities=("pads", "fx", "synth", "arp"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "percussion"}),
                default_transition_in="silence_drop",
                default_transition_out="riser",
            ),
            "outro": PresetSectionOverride(
                role_priorities=("drums", "bass", "pads", "fx"),
                density_min=2,
                density_max=3,
                default_transition_in="crossfade",
                default_transition_out="none",
            ),
        },
    ),

    # ---- Afrobeats -----------------------------------------------------------
    # Percussion-forward rhythmic palette; melodic call-and-response in hooks.
    "afrobeats": ArrangementPresetConfig(
        name="afrobeats",
        description="Percussion-heavy groove; melodic call-and-response; layered rhythms.",
        section_overrides={
            "intro": PresetSectionOverride(
                role_priorities=("percussion", "pads", "melody", "fx", "synth"),
                density_min=1,
                density_max=2,
                default_transition_in="none",
                default_transition_out="percussion_fill",
            ),
            "verse": PresetSectionOverride(
                role_priorities=("percussion", "drums", "bass", "melody", "synth", "pads"),
                density_min=3,
                density_max=4,
                default_transition_in="percussion_fill",
                default_transition_out="percussion_fill",
            ),
            "pre_hook": PresetSectionOverride(
                role_priorities=("percussion", "drums", "bass", "arp", "fx"),
                density_min=3,
                density_max=4,
                default_transition_in="percussion_fill",
                default_transition_out="fx_rise",
            ),
            "hook": PresetSectionOverride(
                role_priorities=("percussion", "drums", "bass", "melody", "vocal", "pads", "synth"),
                density_min=4,
                density_max=5,
                default_transition_in="fx_hit",
                default_transition_out="percussion_fill",
            ),
            "bridge": PresetSectionOverride(
                role_priorities=("melody", "pads", "vocal", "arp", "synth"),
                density_min=2,
                density_max=3,
                forbidden_roles=frozenset({"drums", "percussion"}),
                default_transition_in="mute_drop",
                default_transition_out="percussion_fill",
            ),
            "breakdown": PresetSectionOverride(
                role_priorities=("pads", "melody", "fx", "vocal"),
                density_min=1,
                density_max=2,
                forbidden_roles=frozenset({"drums", "percussion", "bass"}),
                default_transition_in="silence_drop",
                default_transition_out="riser",
            ),
            "outro": PresetSectionOverride(
                role_priorities=("percussion", "melody", "pads", "bass"),
                density_min=2,
                density_max=3,
                default_transition_in="crossfade",
                default_transition_out="none",
            ),
        },
    ),
}


def get_preset_config(preset_name: str | None) -> ArrangementPresetConfig | None:
    """Return the ``ArrangementPresetConfig`` for *preset_name*, or ``None`` if unknown.

    Performs a case-insensitive lookup; unrecognised names return ``None`` so
    callers can fall back to default section profiles without raising.
    """
    if not preset_name:
        return None
    return ARRANGEMENT_PRESETS.get(str(preset_name).strip().lower())


def resolve_preset_name(preset_name: str | None) -> str:
    """Normalise *preset_name* to a known preset key, falling back to the default.

    Returns ``DEFAULT_PRESET`` when *preset_name* is empty or unrecognised.
    """
    if not preset_name:
        return DEFAULT_PRESET
    normalised = str(preset_name).strip().lower()
    return normalised if normalised in VALID_PRESETS else DEFAULT_PRESET
