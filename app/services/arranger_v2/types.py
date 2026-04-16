"""
Arranger V2 — core type definitions.

All types are pure Python dataclasses with no audio or I/O dependencies.
These types are the contract between the planning and rendering layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Canonical role set
# ---------------------------------------------------------------------------

CANONICAL_ROLES: frozenset[str] = frozenset({
    "drums",
    "bass",
    "melody",
    "chords",
    "texture",
    "fx",
    "vocal",
    "percussion",
    "pads",
    "arp",
    "synth",
    "full_mix",
})

# Energy weight of each role when computing section density score.
ROLE_ENERGY_WEIGHTS: dict[str, float] = {
    "drums":      0.9,
    "bass":       0.8,
    "percussion": 0.7,
    "melody":     0.6,
    "synth":      0.6,
    "arp":        0.5,
    "chords":     0.5,
    "pads":       0.4,
    "texture":    0.3,
    "vocal":      0.6,
    "fx":         0.3,
    "full_mix":   1.0,
}

# Allowed transition identifiers (planning layer — not DSP).
TRANSITION_TYPES: frozenset[str] = frozenset({
    "none",
    "riser",
    "drum_fill",
    "reverse_fx",
    "silence_gap",
    "subtractive_entry",
    "re_entry_accent",
    # Legacy renderer aliases kept for compatibility.
    "fx_rise",
    "fx_hit",
    "mute_drop",
    "bass_drop",
    "vocal_chop",
    "arp_lift",
    "percussion_fill",
})

# Transition types that constitute a valid "build-up" for hook entry.
# Used by the validator and tests to verify hook transitions.
HOOK_RISER_TRANSITIONS: frozenset[str] = frozenset({
    "riser",
    "silence_gap",
    "fx_rise",
    "reverse_fx",
})

# Allowed variation strategy names.
VARIATION_STRATEGIES: frozenset[str] = frozenset({
    "none",
    "drop_kick",
    "add_percussion",
    "layer_extra",
    "filter",
    "role_rotation",
    "support_swap",
    "change_pattern",
    "half_time",
})

# Allowed section type names.
SECTION_TYPES: frozenset[str] = frozenset({
    "intro",
    "verse",
    "pre_hook",
    "hook",
    "bridge",
    "breakdown",
    "outro",
})


# ---------------------------------------------------------------------------
# Stem model
# ---------------------------------------------------------------------------

@dataclass
class StemRoleModel:
    """A single stem track with its role and energy characteristics.

    Any stem without a ``role`` in :data:`CANONICAL_ROLES` is invalid and
    must be rejected by the :mod:`role_engine` before planning begins.
    """

    stem_id: str            # Unique identifier (e.g. "drums_01", "bass")
    role: str               # Must be in CANONICAL_ROLES
    energy_weight: float    # 0.0–1.0, contribution to section energy

    def __post_init__(self) -> None:
        self.energy_weight = max(0.0, min(1.0, float(self.energy_weight)))
        if self.role not in CANONICAL_ROLES:
            raise ValueError(
                f"StemRoleModel: role {self.role!r} is not in CANONICAL_ROLES. "
                f"Valid roles: {sorted(CANONICAL_ROLES)}"
            )


# ---------------------------------------------------------------------------
# Section plan
# ---------------------------------------------------------------------------

@dataclass
class SectionPlan:
    """Complete production plan for one section of the arrangement.

    Produced exclusively by :mod:`planner`; consumed by the render executor.
    Every field is deterministic — no random values are permitted.
    """

    # Identity
    name: str               # Human-readable label, e.g. "Hook 2"
    section_type: str       # Canonical type from SECTION_TYPES
    occurrence: int         # 1-based counter within section type
    index: int              # 0-based position in the full arrangement

    # Energy / density targets
    target_density: float       # 0.0–1.0 numeric density (used by density_engine)
    target_density_label: str   # "sparse" | "medium" | "full"
    target_energy: int          # 1–5 integer energy level
    active_roles: list[str]     # Roles selected for this section

    # Variation (only meaningful when occurrence > 1)
    variation_strategy: str     # From VARIATION_STRATEGIES
    introduced_elements: list[str] = field(default_factory=list)  # Roles added vs prev
    dropped_elements: list[str] = field(default_factory=list)     # Roles removed vs prev

    # Transitions
    transition_in: str = "none"    # Type entering this section
    transition_out: str = "none"   # Type leaving this section

    # Timing
    bars: int = 8
    start_bar: int = 0

    # Human-readable notes
    notes: str = ""
    rationale: str = ""


# ---------------------------------------------------------------------------
# Arrangement plan
# ---------------------------------------------------------------------------

@dataclass
class ArrangementPlan:
    """Top-level plan for the full arrangement.

    The renderer must not make any arrangement decisions.  All decisions
    (section order, stem selection, transitions, variation) are encoded here.
    """

    # Ordered section plans
    sections: list[SectionPlan] = field(default_factory=list)

    # Derived flat structures (convenience projections)
    structure: list[str] = field(default_factory=list)          # section_type per index
    energy_curve: list[int] = field(default_factory=list)       # target_energy per index
    section_stem_map: list[list[str]] = field(default_factory=list)  # active_roles per index

    # Totals
    total_bars: int = 0
    bpm: float = 120.0
    key: str = "C"

    # Plan metadata
    plan_version: str = "3.0"
    source_quality_mode: str = "true_stems"
    decision_log: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------------------
    # Serialisation
    # ---------------------------------------------------------------------------

    def to_render_sections(self) -> list[dict]:
        """Convert to the list-of-dicts format expected by ``render_from_plan``."""
        result: list[dict] = []
        for sp in self.sections:
            result.append({
                "name": sp.name,
                "type": sp.section_type,
                "bar_start": sp.start_bar,
                "bars": sp.bars,
                "energy": sp.target_density,   # render_executor uses float 0.0–1.0
                "instruments": list(sp.active_roles),
                "active_stem_roles": list(sp.active_roles),
                "transition_in": sp.transition_in,
                "transition_out": sp.transition_out,
                "variations": _build_section_variations(sp),
                "boundary_events": _build_boundary_events(sp),
            })
        return result

    def to_render_plan(self, *, arrangement_id: int = 0) -> dict:
        """Build the render_plan dict consumed by ``render_from_plan``."""
        sections = self.to_render_sections()
        events = _build_render_events(self.sections)
        transition_boundaries = _build_transition_boundaries(self.sections)
        return {
            "arrangement_id": arrangement_id,
            "bpm": self.bpm,
            "key": self.key,
            "total_bars": self.total_bars,
            "sections": sections,
            "events": events,
            "section_boundaries": transition_boundaries,
            "transitions": transition_boundaries,
            "sections_count": len(sections),
            "events_count": len(events),
            "tracks": [],
            "energy_curve": [
                {"bar": sp.start_bar, "energy": sp.target_density}
                for sp in self.sections
            ],
            "loop_variations": {
                "active": False,
                "count": 0,
                "names": [],
                "files": {},
                "stems_used": False,
            },
            "render_profile": {
                "genre_profile": "generic",
                "producer_arrangement_used": False,
                "arranger_v2_used": True,
                "plan_version": self.plan_version,
                "source_quality_mode": self.source_quality_mode,
                "loop_variations": {
                    "active": False,
                    "count": 0,
                    "names": [],
                    "files": {},
                    "stems_used": False,
                },
                "stem_separation": {"enabled": False, "succeeded": False},
            },
            "arranger_v2_plan": {
                "plan_version": self.plan_version,
                "structure": list(self.structure),
                "energy_curve": list(self.energy_curve),
                "section_stem_map": [list(r) for r in self.section_stem_map],
                "decision_log": list(self.decision_log),
                "total_bars": self.total_bars,
            },
        }


# ---------------------------------------------------------------------------
# Private render-format helpers
# ---------------------------------------------------------------------------

def _build_section_variations(sp: SectionPlan) -> list[dict]:
    """Translate planning variation strategy into render-executor event dicts."""
    if sp.variation_strategy == "none" or sp.occurrence <= 1:
        return []
    strategy_map = {
        "drop_kick":       "drop_kick",
        "add_percussion":  "variation",
        "layer_extra":     "hook_expansion",
        "filter":          "stem_filter",
        "role_rotation":   "variation",
        "support_swap":    "variation",
        "change_pattern":  "variation",
        "half_time":       "halftime_drop",
    }
    event_type = strategy_map.get(sp.variation_strategy, "variation")
    return [{
        "bar": sp.start_bar,
        "variation_type": event_type,
        "intensity": 0.75,
        "duration_bars": 2,
        "description": f"{sp.variation_strategy} on {sp.name}",
        "params": {},
    }]


def _build_boundary_events(sp: SectionPlan) -> list[dict]:
    """Convert transition_in into a boundary_event for the render executor."""
    if sp.transition_in in ("none", ""):
        return []
    boundary_type_map = {
        "riser":             "riser_fx",
        "drum_fill":         "drum_fill",
        "reverse_fx":        "reverse_cymbal",
        "silence_gap":       "pre_hook_silence_drop",
        "subtractive_entry": "pre_hook_mute",
        "re_entry_accent":   "crash_hit",
        "fx_rise":           "riser_fx",
        "fx_hit":            "crash_hit",
        "mute_drop":         "pre_hook_mute",
        "bass_drop":         "bass_pause",
        "vocal_chop":        "variation",
        "arp_lift":          "riser_fx",
        "percussion_fill":   "snare_pickup",
    }
    b_type = boundary_type_map.get(sp.transition_in, sp.transition_in)
    return [{
        "type": b_type,
        "bar": sp.start_bar,
        "placement": "entry",
        "boundary": "section_start",
        "intensity": 0.80,
        "params": {},
    }]


def _build_render_events(sections: list[SectionPlan]) -> list[dict]:
    """Build the flat events list from section plans."""
    events: list[dict] = []
    for sp in sections:
        events.append({
            "type": "section_start",
            "bar": sp.start_bar,
            "description": f"{sp.name} starts",
        })
        if sp.transition_in not in ("none", ""):
            t_map = {
                "riser":             "riser_fx",
                "drum_fill":         "drum_fill",
                "reverse_fx":        "reverse_cymbal",
                "silence_gap":       "silence_drop",
                "subtractive_entry": "pre_hook_mute",
                "re_entry_accent":   "crash_hit",
                "fx_rise":           "riser_fx",
                "fx_hit":            "fx_hit",
                "mute_drop":         "pre_hook_mute",
                "bass_drop":         "bass_pause",
                "vocal_chop":        "variation",
                "arp_lift":          "riser_fx",
                "percussion_fill":   "snare_pickup",
            }
            e_type = t_map.get(sp.transition_in, sp.transition_in)
            events.append({
                "type": e_type,
                "bar": max(0, sp.start_bar - 1),
                "description": f"Transition into {sp.name}: {sp.transition_in}",
                "intensity": 0.80,
            })
        if sp.variation_strategy not in ("none", "") and sp.occurrence > 1:
            s_map = {
                "drop_kick":      "drop_kick",
                "add_percussion": "variation",
                "layer_extra":    "hook_expansion",
                "filter":         "stem_filter",
                "role_rotation":  "variation",
                "support_swap":   "variation",
                "change_pattern": "variation",
                "half_time":      "halftime_drop",
            }
            v_type = s_map.get(sp.variation_strategy, "variation")
            events.append({
                "type": v_type,
                "bar": sp.start_bar + 1,
                "description": f"{sp.variation_strategy} variation in {sp.name}",
                "intensity": 0.75,
            })
    return events


def _build_transition_boundaries(sections: list[SectionPlan]) -> list[dict]:
    """Build transition boundaries list from section transition metadata."""
    boundaries: list[dict] = []
    for i, sp in enumerate(sections):
        if i == 0:
            continue  # No boundary before first section
        prev = sections[i - 1]
        if sp.transition_in in ("none", ""):
            continue
        boundaries.append({
            "bar": sp.start_bar,
            "from_section": prev.section_type,
            "to_section": sp.section_type,
            "transition_type": sp.transition_in,
            "intensity": 0.80,
            "description": f"{prev.section_type} → {sp.section_type} via {sp.transition_in}",
        })
    return boundaries
