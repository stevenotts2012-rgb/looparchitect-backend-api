"""
Producer Plan Builder V2 — Phase 1 Producer Engine Foundation.

Builds a deterministic, inspectable section-by-section arrangement plan with:
- Structured section types (intro, verse, pre_hook, hook, bridge, breakdown, outro)
- Per-section energy levels, density, active/muted roles
- Variation strategy and transition intent per section
- Producer decision log explaining WHY each choice was made

This is the planning layer that runs BEFORE audio rendering.  It is
controlled by the PRODUCER_ENGINE_V2 feature flag and falls back to the
legacy ProducerEngine path when the flag is disabled.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SectionKind(str, Enum):
    """Canonical section types for a produced arrangement."""

    INTRO = "intro"
    VERSE = "verse"
    PRE_HOOK = "pre_hook"
    HOOK = "hook"
    BRIDGE = "bridge"
    BREAKDOWN = "breakdown"
    OUTRO = "outro"


class EnergyLevel(int, Enum):
    """1–5 energy scale used across the plan."""

    VERY_LOW = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    VERY_HIGH = 5


class DensityLevel(str, Enum):
    SPARSE = "sparse"
    MEDIUM = "medium"
    FULL = "full"


class VariationStrategy(str, Enum):
    """How a section should vary from the previous occurrence."""

    REPEAT = "repeat"               # Identical loop repeat (intentional)
    LAYER_ADD = "layer_add"         # Add an instrument/role
    LAYER_REMOVE = "layer_remove"   # Remove an instrument/role
    OCTAVE_SHIFT = "octave_shift"   # Melody octave change
    RHYTHM_VARIATION = "rhythm_variation"  # Drum pattern variation
    BREAKDOWN = "breakdown"         # Strip-back for contrast
    FILL_EXIT = "fill_exit"         # Exit with a fill


class TransitionIntent(str, Enum):
    """Intended transition entering a section (transition_in) or leaving it (transition_out)."""

    NONE = "none"
    DRUM_FILL = "drum_fill"
    FX_RISE = "fx_rise"
    FX_HIT = "fx_hit"
    MUTE_DROP = "mute_drop"
    BASS_DROP = "bass_drop"
    RISER = "riser"
    PULL_BACK = "pull_back"     # Reduce density before a payoff
    SILENCE_DROP = "silence_drop"
    CROSSFADE = "crossfade"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ProducerSectionPlan:
    """Complete per-section plan produced by the Producer Engine V2."""

    # Identity
    index: int
    section_type: SectionKind
    label: str                      # Human-readable label, e.g. "Hook 1"

    # Bar position
    start_bar: int
    length_bars: int

    # Energy & density
    target_energy: EnergyLevel
    density: DensityLevel

    # Role management
    active_roles: List[str] = field(default_factory=list)
    muted_roles: List[str] = field(default_factory=list)
    introduced_roles: List[str] = field(default_factory=list)
    removed_roles: List[str] = field(default_factory=list)

    # Variation & transition intent
    variation_strategy: VariationStrategy = VariationStrategy.REPEAT
    transition_in: TransitionIntent = TransitionIntent.NONE
    transition_out: TransitionIntent = TransitionIntent.NONE

    # Explainability
    notes: str = ""
    rationale: str = ""

    @property
    def end_bar(self) -> int:
        return self.start_bar + self.length_bars - 1


@dataclass
class ProducerDecisionEntry:
    """A single entry in the producer decision log."""

    section_index: int
    section_label: str
    decision: str
    reason: str
    flag: str = ""          # e.g. which rule triggered this


@dataclass
class ProducerArrangementPlanV2:
    """
    Complete, inspectable V2 arrangement plan.

    This is the output of ProducerPlanBuilderV2 and drives the render pipeline
    when PRODUCER_ENGINE_V2=true.
    """

    # Core structure
    sections: List[ProducerSectionPlan] = field(default_factory=list)

    # Explainability
    decision_log: List[ProducerDecisionEntry] = field(default_factory=list)

    # Metadata
    genre: str = "generic"
    style_tags: List[str] = field(default_factory=list)
    tempo: float = 120.0
    total_bars: int = 0
    source_type: str = "loop"       # "loop" | "stem_pack" | "unknown"
    available_roles: List[str] = field(default_factory=list)

    # Plan generation provenance
    builder_version: str = "2.0"
    rules_applied: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise to a plain dict (JSON-safe)."""
        return {
            "builder_version": self.builder_version,
            "genre": self.genre,
            "style_tags": self.style_tags,
            "tempo": self.tempo,
            "total_bars": self.total_bars,
            "source_type": self.source_type,
            "available_roles": self.available_roles,
            "rules_applied": self.rules_applied,
            "sections": [
                {
                    "index": s.index,
                    "section_type": s.section_type.value,
                    "label": s.label,
                    "start_bar": s.start_bar,
                    "length_bars": s.length_bars,
                    "end_bar": s.end_bar,
                    "target_energy": s.target_energy.value,
                    "density": s.density.value,
                    "active_roles": s.active_roles,
                    "muted_roles": s.muted_roles,
                    "introduced_roles": s.introduced_roles,
                    "removed_roles": s.removed_roles,
                    "variation_strategy": s.variation_strategy.value,
                    "transition_in": s.transition_in.value,
                    "transition_out": s.transition_out.value,
                    "notes": s.notes,
                    "rationale": s.rationale,
                }
                for s in self.sections
            ],
            "decision_log": [
                {
                    "section_index": e.section_index,
                    "section_label": e.section_label,
                    "decision": e.decision,
                    "reason": e.reason,
                    "flag": e.flag,
                }
                for e in self.decision_log
            ],
        }


# ---------------------------------------------------------------------------
# Default configuration tables
# ---------------------------------------------------------------------------

# Base energy targets per section type (before style modulation)
_BASE_ENERGY: dict[SectionKind, EnergyLevel] = {
    SectionKind.INTRO:     EnergyLevel.LOW,
    SectionKind.VERSE:     EnergyLevel.MEDIUM,
    SectionKind.PRE_HOOK:  EnergyLevel.HIGH,
    SectionKind.HOOK:      EnergyLevel.VERY_HIGH,
    SectionKind.BRIDGE:    EnergyLevel.LOW,
    SectionKind.BREAKDOWN: EnergyLevel.VERY_LOW,
    SectionKind.OUTRO:     EnergyLevel.LOW,
}

_BASE_DENSITY: dict[SectionKind, DensityLevel] = {
    SectionKind.INTRO:     DensityLevel.SPARSE,
    SectionKind.VERSE:     DensityLevel.MEDIUM,
    SectionKind.PRE_HOOK:  DensityLevel.MEDIUM,
    SectionKind.HOOK:      DensityLevel.FULL,
    SectionKind.BRIDGE:    DensityLevel.SPARSE,
    SectionKind.BREAKDOWN: DensityLevel.SPARSE,
    SectionKind.OUTRO:     DensityLevel.SPARSE,
}

_TRANSITION_IN_DEFAULTS: dict[SectionKind, TransitionIntent] = {
    SectionKind.INTRO:     TransitionIntent.NONE,
    SectionKind.VERSE:     TransitionIntent.DRUM_FILL,
    SectionKind.PRE_HOOK:  TransitionIntent.FX_RISE,
    SectionKind.HOOK:      TransitionIntent.FX_HIT,
    SectionKind.BRIDGE:    TransitionIntent.MUTE_DROP,
    SectionKind.BREAKDOWN: TransitionIntent.SILENCE_DROP,
    SectionKind.OUTRO:     TransitionIntent.CROSSFADE,
}

_TRANSITION_OUT_DEFAULTS: dict[SectionKind, TransitionIntent] = {
    SectionKind.INTRO:     TransitionIntent.DRUM_FILL,
    SectionKind.VERSE:     TransitionIntent.NONE,
    SectionKind.PRE_HOOK:  TransitionIntent.PULL_BACK,
    SectionKind.HOOK:      TransitionIntent.NONE,
    SectionKind.BRIDGE:    TransitionIntent.RISER,
    SectionKind.BREAKDOWN: TransitionIntent.RISER,
    SectionKind.OUTRO:     TransitionIntent.NONE,
}

# Role preference order per section (most preferred first)
_ROLE_PREFERENCE: dict[SectionKind, list[str]] = {
    SectionKind.INTRO:     ["pads", "fx", "melody", "arp", "vocal", "synth", "full_mix"],
    SectionKind.VERSE:     ["drums", "bass", "melody", "vocal", "synth", "percussion", "arp", "pads", "full_mix"],
    SectionKind.PRE_HOOK:  ["drums", "bass", "arp", "fx", "melody", "vocal", "percussion", "synth", "full_mix"],
    SectionKind.HOOK:      ["drums", "bass", "melody", "synth", "vocal", "percussion", "arp", "pads", "fx", "full_mix"],
    SectionKind.BRIDGE:    ["pads", "fx", "melody", "vocal", "arp", "bass", "synth", "full_mix"],
    SectionKind.BREAKDOWN: ["pads", "fx", "vocal", "arp", "melody", "synth", "full_mix"],
    SectionKind.OUTRO:     ["pads", "fx", "melody", "arp", "vocal", "full_mix"],
}

# Maximum concurrent roles per density level
_MAX_ROLES: dict[DensityLevel, int] = {
    DensityLevel.SPARSE: 2,
    DensityLevel.MEDIUM: 3,
    DensityLevel.FULL:   5,
}

# Default bar lengths per section type
_DEFAULT_BARS: dict[SectionKind, int] = {
    SectionKind.INTRO:     8,
    SectionKind.VERSE:     8,
    SectionKind.PRE_HOOK:  4,
    SectionKind.HOOK:      8,
    SectionKind.BRIDGE:    8,
    SectionKind.BREAKDOWN: 8,
    SectionKind.OUTRO:     4,
}

# Default song structure templates (section type sequences)
_STRUCTURE_TEMPLATES: dict[str, list[SectionKind]] = {
    "standard": [
        SectionKind.INTRO,
        SectionKind.VERSE,
        SectionKind.PRE_HOOK,
        SectionKind.HOOK,
        SectionKind.VERSE,
        SectionKind.PRE_HOOK,
        SectionKind.HOOK,
        SectionKind.BRIDGE,
        SectionKind.HOOK,
        SectionKind.OUTRO,
    ],
    "minimal": [
        SectionKind.INTRO,
        SectionKind.VERSE,
        SectionKind.HOOK,
        SectionKind.VERSE,
        SectionKind.HOOK,
        SectionKind.OUTRO,
    ],
    "loop": [
        SectionKind.INTRO,
        SectionKind.VERSE,
        SectionKind.HOOK,
        SectionKind.VERSE,
        SectionKind.HOOK,
        SectionKind.OUTRO,
    ],
    "extended": [
        SectionKind.INTRO,
        SectionKind.VERSE,
        SectionKind.PRE_HOOK,
        SectionKind.HOOK,
        SectionKind.VERSE,
        SectionKind.PRE_HOOK,
        SectionKind.HOOK,
        SectionKind.BREAKDOWN,
        SectionKind.BRIDGE,
        SectionKind.PRE_HOOK,
        SectionKind.HOOK,
        SectionKind.OUTRO,
    ],
}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _select_roles(
    section_type: SectionKind,
    available_roles: list[str],
    density: DensityLevel,
) -> list[str]:
    """Select which roles to activate for a section, respecting density limit."""
    max_roles = _MAX_ROLES[density]
    preferred = _ROLE_PREFERENCE[section_type]

    # Prefer roles in preference order that are actually available
    ordered = [r for r in preferred if r in available_roles]

    # Special override: hooks must have drums and bass when available
    if section_type == SectionKind.HOOK:
        priority = [r for r in ["drums", "bass"] if r in available_roles]
        for r in priority:
            if r not in ordered:
                ordered.insert(0, r)

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for r in ordered:
        if r not in seen:
            seen.add(r)
            deduped.append(r)

    selected = deduped[:max_roles]

    # Fall back to first available if nothing selected
    if not selected and available_roles:
        selected = [available_roles[0]]

    # Prefer avoiding full_mix when 2+ isolated roles exist
    non_full = [r for r in selected if r != "full_mix"]
    if len(non_full) >= 2:
        selected = non_full

    return selected


def _muted_roles(available_roles: list[str], active_roles: list[str]) -> list[str]:
    """Compute muted roles as (available - active)."""
    return [r for r in available_roles if r not in active_roles]


def _section_label(section_type: SectionKind, occurrence: int) -> str:
    """Human-readable label like 'Hook 1', 'Verse 2'."""
    return f"{section_type.value.replace('_', ' ').title()} {occurrence}"


def _variation_strategy(
    section_type: SectionKind,
    occurrence: int,
    prev_active_roles: list[str],
    curr_active_roles: list[str],
) -> VariationStrategy:
    """Decide the variation strategy for this section occurrence."""
    if occurrence == 1:
        # First occurrence — no variation context
        return VariationStrategy.REPEAT

    added = set(curr_active_roles) - set(prev_active_roles)
    removed = set(prev_active_roles) - set(curr_active_roles)

    if section_type in (SectionKind.BRIDGE, SectionKind.BREAKDOWN):
        return VariationStrategy.BREAKDOWN
    if added:
        return VariationStrategy.LAYER_ADD
    if removed:
        return VariationStrategy.LAYER_REMOVE
    if section_type == SectionKind.HOOK and occurrence > 1:
        return VariationStrategy.FILL_EXIT
    return VariationStrategy.RHYTHM_VARIATION


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class ProducerPlanBuilderV2:
    """
    Builds a deterministic ProducerArrangementPlanV2 from loop/stem metadata.

    Usage::

        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody"],
            genre="trap",
            tempo=140.0,
            target_bars=64,
        )
        plan = builder.build()

    The plan is always deterministic for the same inputs.  No randomness is
    introduced here — that belongs in the render layer.
    """

    def __init__(
        self,
        available_roles: Sequence[str],
        genre: str = "generic",
        tempo: float = 120.0,
        target_bars: Optional[int] = None,
        source_type: str = "loop",
        structure_template: str = "standard",
        style_tags: Optional[list[str]] = None,
    ) -> None:
        self.available_roles = list(available_roles)
        self.genre = genre
        self.tempo = tempo
        self.target_bars = target_bars
        self.source_type = source_type
        self.structure_template = structure_template
        self.style_tags = style_tags or []

        self._decision_log: list[ProducerDecisionEntry] = []
        self._rules_applied: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> ProducerArrangementPlanV2:
        """Build and return the complete arrangement plan."""
        self._decision_log = []
        self._rules_applied = []

        section_sequence = self._resolve_structure()
        section_plans = self._build_sections(section_sequence)

        total_bars = sum(s.length_bars for s in section_plans)

        plan = ProducerArrangementPlanV2(
            sections=section_plans,
            decision_log=self._decision_log,
            genre=self.genre,
            style_tags=self.style_tags,
            tempo=self.tempo,
            total_bars=total_bars,
            source_type=self.source_type,
            available_roles=list(self.available_roles),
            builder_version="2.0",
            rules_applied=list(self._rules_applied),
        )

        logger.info(
            "ProducerPlanBuilderV2: built %d sections, %d bars, genre=%s",
            len(section_plans),
            total_bars,
            self.genre,
        )
        return plan

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_structure(self) -> list[SectionKind]:
        """Return the section type sequence for the chosen template."""
        template = self.structure_template
        if template not in _STRUCTURE_TEMPLATES:
            logger.warning(
                "Unknown structure template '%s'; falling back to 'standard'", template
            )
            template = "standard"

        # Use 'loop' template for single-loop sources without stems
        if self.source_type == "loop" and template == "standard" and len(self.available_roles) <= 1:
            template = "loop"
            self._log(
                section_index=-1,
                section_label="global",
                decision="Using simplified 'loop' structure template",
                reason=f"Only {len(self.available_roles)} roles available for a single-loop source",
                flag="sparse_source",
            )

        return _STRUCTURE_TEMPLATES[template]

    def _build_sections(
        self, sequence: list[SectionKind]
    ) -> list[ProducerSectionPlan]:
        """Build per-section plans from a section type sequence."""
        sections: list[ProducerSectionPlan] = []
        occurrence_counter: dict[SectionKind, int] = {}
        prev_active_roles_by_type: dict[SectionKind, list[str]] = {}
        bar_cursor = 0

        for idx, section_type in enumerate(sequence):
            occurrence_counter[section_type] = occurrence_counter.get(section_type, 0) + 1
            occurrence = occurrence_counter[section_type]
            label = _section_label(section_type, occurrence)

            # Determine bar length
            length_bars = self._resolve_bar_length(section_type, idx, len(sequence))

            # Determine energy & density (with rules applied inline)
            target_energy, density = self._resolve_energy_density(section_type, idx, occurrence)

            # Select roles
            active_roles = _select_roles(section_type, self.available_roles, density)
            muted = _muted_roles(self.available_roles, active_roles)

            # Introduced / removed vs previous occurrence of this section type
            prev_active = prev_active_roles_by_type.get(section_type, [])
            introduced = [r for r in active_roles if r not in prev_active] if prev_active else []
            removed = [r for r in prev_active if r not in active_roles]

            variation = _variation_strategy(section_type, occurrence, prev_active, active_roles)
            transition_in = _TRANSITION_IN_DEFAULTS[section_type]
            transition_out = _TRANSITION_OUT_DEFAULTS[section_type]

            notes, rationale = self._build_notes(
                section_type, idx, occurrence, active_roles, muted, density
            )

            section_plan = ProducerSectionPlan(
                index=idx,
                section_type=section_type,
                label=label,
                start_bar=bar_cursor,
                length_bars=length_bars,
                target_energy=target_energy,
                density=density,
                active_roles=active_roles,
                muted_roles=muted,
                introduced_roles=introduced,
                removed_roles=removed,
                variation_strategy=variation,
                transition_in=transition_in,
                transition_out=transition_out,
                notes=notes,
                rationale=rationale,
            )
            sections.append(section_plan)
            prev_active_roles_by_type[section_type] = active_roles
            bar_cursor += length_bars

        # Post-process: adjust bar lengths to hit target_bars if specified
        if self.target_bars and sections:
            sections = self._fit_to_target_bars(sections, self.target_bars)

        return sections

    def _resolve_bar_length(
        self, section_type: SectionKind, idx: int, total_sections: int
    ) -> int:
        default = _DEFAULT_BARS[section_type]

        # Scale toward target_bars if known
        if self.target_bars:
            avg_per_section = max(4, self.target_bars // max(1, total_sections))
            if section_type in (SectionKind.VERSE, SectionKind.HOOK, SectionKind.BRIDGE, SectionKind.BREAKDOWN):
                # Scale-able sections snap to nearest multiple of 4
                scaled = max(4, (avg_per_section // 4) * 4)
                return scaled

        return default

    def _resolve_energy_density(
        self, section_type: SectionKind, idx: int, occurrence: int
    ) -> tuple[EnergyLevel, DensityLevel]:
        energy = _BASE_ENERGY[section_type]
        density = _BASE_DENSITY[section_type]

        # Sparse-intro rule: intro is always sparse regardless of available roles
        if section_type == SectionKind.INTRO:
            if len(self.available_roles) > 2:
                density = DensityLevel.SPARSE
                self._log(
                    section_index=idx,
                    section_label=_section_label(section_type, occurrence),
                    decision="Intro forced to sparse density",
                    reason=f"{len(self.available_roles)} roles available but intro must be sparse",
                    flag="sparse_intro",
                )
                self._add_rule("sparse_intro")

        # Hook must be full when drums+bass available
        if section_type == SectionKind.HOOK:
            has_groove = any(r in self.available_roles for r in ["drums", "bass", "full_mix"])
            if has_groove:
                density = DensityLevel.FULL
                energy = EnergyLevel.VERY_HIGH
                self._log(
                    section_index=idx,
                    section_label=_section_label(section_type, occurrence),
                    decision="Hook promoted to full density and max energy",
                    reason="drums/bass/full_mix available — hook must deliver maximum impact",
                    flag="hook_elevation",
                )
                self._add_rule("hook_elevation")
            else:
                # Sparse hook fallback when no groove stems
                self._log(
                    section_index=idx,
                    section_label=_section_label(section_type, occurrence),
                    decision="Hook kept at medium density — no groove stems",
                    reason="Neither drums, bass, nor full_mix found in available roles",
                    flag="hook_sparse_fallback",
                )

        # Bridge/breakdown contrast
        if section_type in (SectionKind.BRIDGE, SectionKind.BREAKDOWN):
            density = DensityLevel.SPARSE
            energy = EnergyLevel.VERY_LOW
            self._log(
                section_index=idx,
                section_label=_section_label(section_type, occurrence),
                decision="Bridge/Breakdown forced sparse for contrast",
                reason="Contrast before final hook payoff requires reduced density",
                flag="bridge_contrast",
            )
            self._add_rule("bridge_contrast")

        # Outro simplification
        if section_type == SectionKind.OUTRO:
            density = DensityLevel.SPARSE
            energy = EnergyLevel.LOW
            self._log(
                section_index=idx,
                section_label=_section_label(section_type, occurrence),
                decision="Outro set to sparse/low energy",
                reason="Outros should wind down, not overcrowd the exit",
                flag="outro_simplification",
            )
            self._add_rule("outro_simplification")

        return energy, density

    def _build_notes(
        self,
        section_type: SectionKind,
        idx: int,
        occurrence: int,
        active_roles: list[str],
        muted_roles: list[str],
        density: DensityLevel,
    ) -> tuple[str, str]:
        notes_parts = []
        rationale_parts = []

        if not self.available_roles:
            notes_parts.append("No roles available — section will use full-mix fallback")
            rationale_parts.append("Source has no separated stems; full mix used as single layer")
            return " ".join(notes_parts), " ".join(rationale_parts)

        if muted_roles:
            notes_parts.append(f"Muted: {', '.join(muted_roles)}")
            rationale_parts.append(
                f"{len(muted_roles)} role(s) silenced to maintain {density.value} density"
            )

        if section_type == SectionKind.INTRO and len(self.available_roles) > 2:
            rationale_parts.append(
                f"intro kept sparse because {len(self.available_roles)} stems exist — "
                "only light elements should open the track"
            )

        if section_type == SectionKind.HOOK:
            if "drums" in active_roles and "bass" in active_roles:
                rationale_parts.append(
                    "hook promoted full drums and bass for max energy"
                )
            elif not active_roles:
                rationale_parts.append(
                    "hook limited by stem availability — add drums/bass stems for full impact"
                )

        if section_type in (SectionKind.BRIDGE, SectionKind.BREAKDOWN):
            rationale_parts.append(
                "bridge/breakdown reduced density before final payoff"
            )

        notes = "; ".join(notes_parts) if notes_parts else f"Active: {', '.join(active_roles) or 'none'}"
        rationale = " | ".join(rationale_parts) if rationale_parts else f"{section_type.value} with {density.value} density"
        return notes, rationale

    def _fit_to_target_bars(
        self, sections: list[ProducerSectionPlan], target: int
    ) -> list[ProducerSectionPlan]:
        """Adjust scaleable sections to hit target bar count."""
        current = sum(s.length_bars for s in sections)
        if current == target:
            return sections

        delta = target - current
        scaleable_types = {SectionKind.VERSE, SectionKind.HOOK, SectionKind.BRIDGE, SectionKind.BREAKDOWN}
        scaleable = [s for s in sections if s.section_type in scaleable_types]
        if not scaleable:
            return sections

        idx = 0
        iterations = 0
        max_iterations = 512
        while delta != 0 and iterations < max_iterations:
            section = scaleable[idx % len(scaleable)]
            step = 4 if delta > 0 else -4
            if step < 0 and section.length_bars <= 4:
                idx += 1
                iterations += 1
                continue
            section.length_bars += step
            delta -= step
            idx += 1
            iterations += 1

        # Recompute start_bars after length adjustments
        bar_cursor = 0
        for s in sections:
            s.start_bar = bar_cursor
            bar_cursor += s.length_bars

        return sections

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log(
        self,
        section_index: int,
        section_label: str,
        decision: str,
        reason: str,
        flag: str = "",
    ) -> None:
        self._decision_log.append(
            ProducerDecisionEntry(
                section_index=section_index,
                section_label=section_label,
                decision=decision,
                reason=reason,
                flag=flag,
            )
        )

    def _add_rule(self, rule_name: str) -> None:
        if rule_name not in self._rules_applied:
            self._rules_applied.append(rule_name)
