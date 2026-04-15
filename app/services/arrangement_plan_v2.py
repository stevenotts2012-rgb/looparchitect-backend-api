"""
Arrangement Plan V2 — deterministic, stateful producer system.

This module is the primary planning layer when ARRANGEMENT_PLAN_V2=true.  It
produces a structured :class:`ArrangementPlanV2` before any audio is rendered,
giving downstream systems a clear, inspectable plan to honour.

Key design goals:
- Fully deterministic for the same input (no random calls, no LLM dependency).
- Source-quality-aware: true_stems / zip_stems get richer variation; ai_separated
  and stereo_fallback get conservative, safe layering.
- Stateful: uses :class:`ArrangementMemory` to prevent identical repeated
  sections and flat energy progression.
- Inspectable: every decision written to the ``decision_log`` so audits can
  explain *why* a role set or variation strategy was chosen.
- Backward-compatible: the public entry point returns an :class:`ArrangementPlanV2`
  which callers can consume alongside (not replacing) the existing
  ``ArrangementPlan`` schema.

Feature flags:
- ARRANGEMENT_PLAN_V2=true          — enables this module
- ARRANGEMENT_MEMORY_V2=true        — enables stateful memory
- ARRANGEMENT_TRANSITIONS_V2=true   — enables per-boundary transition planning
- ARRANGEMENT_TRUTH_OBSERVABILITY_V2=true — enables richer observability output

Gating is handled by :func:`build_arrangement_plan_v2`; callers should check
``settings.feature_arrangement_plan_v2`` before calling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.arrangement_memory import ArrangementMemory, VARIATION_STRATEGIES
from app.services.section_identity_engine import (
    select_roles_for_section,
    get_transition_events,
    SECTION_IDENTITY_ENGINE_VERSION,
)
from app.services.source_quality import (
    SourceQualityMode,
    get_source_quality_profile,
    classify_source_quality,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLAN_V2_VERSION = "2.0"

CANONICAL_ROLES = frozenset({
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
})

# Energy levels (1–5) per section type for the first occurrence.
_BASE_ENERGY: dict[str, int] = {
    "intro":      1,
    "verse":      3,
    "pre_hook":   4,
    "hook":       5,
    "bridge":     2,
    "breakdown":  2,
    "outro":      1,
}

# Transition types supported by this planning layer.
TRANSITION_TYPES = frozenset({
    "none",
    "riser",
    "drum_fill",
    "reverse_fx",
    "silence_gap",
    "subtractive_entry",
    "re_entry_accent",
    # Legacy aliases kept for compatibility with existing renderer
    "fx_rise",
    "fx_hit",
    "mute_drop",
    "bass_drop",
    "drum_fill",
    "vocal_chop",
    "arp_lift",
    "percussion_fill",
})

# Default transition-in per section type (canonical names for the V2 planner).
_DEFAULT_TRANSITION_IN: dict[str, str] = {
    "intro":      "none",
    "verse":      "drum_fill",
    "pre_hook":   "riser",
    "hook":       "re_entry_accent",
    "bridge":     "subtractive_entry",
    "breakdown":  "silence_gap",
    "outro":      "subtractive_entry",
}

# Default transition-out per section type.
_DEFAULT_TRANSITION_OUT: dict[str, str] = {
    "intro":      "drum_fill",
    "verse":      "riser",
    "pre_hook":   "reverse_fx",
    "hook":       "none",
    "bridge":     "riser",
    "breakdown":  "riser",
    "outro":      "none",
}

# Source-quality-specific energy modifiers (fraction of normal energy range).
_SOURCE_ENERGY_SCALE: dict[str, float] = {
    "true_stems":      1.0,
    "zip_stems":       1.0,
    "ai_separated":    0.8,   # softer ceiling — more conservative arrangement
    "stereo_fallback": 0.6,   # minimal range — single-layer output
}

# Maximum simultaneous layers per source quality at hook sections.
_HOOK_MAX_LAYERS: dict[str, int] = {
    "true_stems":      5,
    "zip_stems":       5,
    "ai_separated":    3,
    "stereo_fallback": 1,
}

# Minimum Jaccard distance required between consecutive same-type sections.
_REPEAT_DISTINCTION_THRESHOLD = 0.20


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class StemRole:
    """A single stem with its associated metadata for role-based selection."""

    stem_id: str                    # Unique identifier (e.g. "drums_01")
    role: str                       # Canonical role (drums, bass, melody, …)
    energy_weight: float            # 0.0–1.0 — contribution to section energy
    source_type: str                # true_stems | zip_stems | ai_separated | stereo_fallback
    confidence: float               # 0.0–1.0 — confidence in role classification

    def __post_init__(self) -> None:
        self.energy_weight = max(0.0, min(1.0, float(self.energy_weight)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if self.role not in CANONICAL_ROLES:
            logger.debug("StemRole: unrecognised role %r — keeping as-is", self.role)


@dataclass
class SectionPlan:
    """Structured plan for one section in the arrangement.

    Produced by :func:`build_arrangement_plan_v2` before rendering.
    """

    name: str                           # e.g. "Hook 2"
    section_type: str                   # canonical type: verse, hook, …
    occurrence: int                     # 1-based occurrence count within this type
    index: int                          # 0-based position in the full arrangement

    # Energy / density targets
    target_energy: int                  # 1–5 integer
    target_density: str                 # sparse | medium | full

    # Role selection
    active_roles: list[str]             # roles selected for this section
    introduced_elements: list[str]      # roles appearing for the first time vs. prev occurrence
    dropped_elements: list[str]         # roles removed vs. prev occurrence

    # Variation
    variation_strategy: str             # from VARIATION_STRATEGIES

    # Transitions
    transition_in: str                  # transition type entering this section
    transition_out: str                 # transition type leaving this section

    # Metadata
    bars: int
    start_bar: int
    notes: str
    rationale: str                      # one-line explanation of decisions made


@dataclass
class TransitionPlanEntry:
    """Planned transition at a section boundary."""

    from_section_index: int
    to_section_index: int
    from_section_type: str
    to_section_type: str
    boundary_bar: int
    transition_type: str
    intensity: float                    # 0.0–1.0
    description: str


@dataclass
class DecisionLogEntry:
    """Single entry in the arrangement decision log."""

    section_index: int
    section_label: str
    decision: str
    reason: str
    flag: str = ""


@dataclass
class ArrangementPlanV2:
    """Top-level structured plan produced by the V2 planning layer.

    This is the primary planning output used downstream.  The render engine
    should honour the ``section_stem_map`` and ``transition_plan``; any
    deviations must be recorded in the observability layer.
    """

    plan_version: str = PLAN_V2_VERSION
    source_quality_mode: str = "true_stems"

    # Ordered section plans
    sections: list[SectionPlan] = field(default_factory=list)

    # Derived flat structures
    structure: list[str] = field(default_factory=list)          # section_type per index
    energy_curve: list[int] = field(default_factory=list)       # target_energy per index
    section_stem_map: list[list[str]] = field(default_factory=list)  # active_roles per index

    # Transition plan
    transition_plan: list[TransitionPlanEntry] = field(default_factory=list)

    # Decision log
    decision_log: list[DecisionLogEntry] = field(default_factory=list)

    # Memory snapshot (for observability)
    memory_snapshot: dict = field(default_factory=dict)

    # Totals
    total_bars: int = 0

    # ---------------------------------------------------------------------------
    # Observability helpers
    # ---------------------------------------------------------------------------

    def to_observability_dict(self) -> dict:
        """Return a JSON-safe dict suitable for embedding in render_metadata."""
        return {
            "plan_version": self.plan_version,
            "source_quality_mode": self.source_quality_mode,
            "total_bars": self.total_bars,
            "structure": list(self.structure),
            "energy_curve": list(self.energy_curve),
            "section_stem_map": [list(r) for r in self.section_stem_map],
            "transition_plan": [
                {
                    "boundary_bar": t.boundary_bar,
                    "from": t.from_section_type,
                    "to": t.to_section_type,
                    "type": t.transition_type,
                    "intensity": t.intensity,
                }
                for t in self.transition_plan
            ],
            "sections": [
                {
                    "index": s.index,
                    "name": s.name,
                    "section_type": s.section_type,
                    "occurrence": s.occurrence,
                    "target_energy": s.target_energy,
                    "target_density": s.target_density,
                    "active_roles": list(s.active_roles),
                    "introduced_elements": list(s.introduced_elements),
                    "dropped_elements": list(s.dropped_elements),
                    "variation_strategy": s.variation_strategy,
                    "transition_in": s.transition_in,
                    "transition_out": s.transition_out,
                    "bars": s.bars,
                    "start_bar": s.start_bar,
                    "notes": s.notes,
                    "rationale": s.rationale,
                }
                for s in self.sections
            ],
            "decision_log": [
                {
                    "section_index": d.section_index,
                    "section_label": d.section_label,
                    "decision": d.decision,
                    "reason": d.reason,
                    "flag": d.flag,
                }
                for d in self.decision_log
            ],
            "memory_snapshot": self.memory_snapshot,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _section_label(section_type: str, occurrence: int) -> str:
    return f"{section_type.replace('_', ' ').title()} {occurrence}" if occurrence > 1 else section_type.replace("_", " ").title()


def _target_energy(
    section_type: str,
    occurrence: int,
    source_quality_mode: str,
) -> int:
    """Return a 1–5 integer energy target, scaled by source quality."""
    base = _BASE_ENERGY.get(section_type, 3)

    # Occurrence-based escalation for verse and hook.
    if section_type == "verse" and occurrence >= 2:
        base = min(5, base + 1)
    elif section_type == "hook" and occurrence == 1:
        base = 4  # restrained first hook so later hooks escalate

    scale = _SOURCE_ENERGY_SCALE.get(source_quality_mode, 1.0)
    # Scale DOWN only — source quality can reduce but not increase energy.
    scaled = max(1, round(base * scale))
    return int(scaled)


def _target_density(section_type: str, energy: int) -> str:
    if section_type in {"intro", "outro", "breakdown", "bridge"}:
        return "sparse"
    if section_type == "hook":
        return "full"
    return "medium" if energy <= 3 else "full"


def _cap_roles_for_quality(
    roles: list[str],
    section_type: str,
    source_quality_mode: str,
) -> list[str]:
    """Enforce source-quality-specific role count caps."""
    profile = get_source_quality_profile(source_quality_mode)
    if section_type == "hook":
        max_layers = profile.max_layers_hook
    elif section_type in {"intro", "verse"}:
        max_layers = profile.max_intro_verse_layers
    elif section_type in {"bridge", "breakdown"}:
        max_layers = profile.max_breakdown_layers
    else:
        max_layers = profile.max_layers_non_hook

    return roles[:max_layers]


def _determine_variation_strategy(
    section_type: str,
    occurrence: int,
    prev_roles: list[str],
    new_roles: list[str],
    memory: ArrangementMemory,
    available_roles: list[str],
) -> str:
    """Decide which named variation strategy was (or should be) applied."""
    if occurrence <= 1:
        return "none"

    prev_set = set(prev_roles)
    new_set = set(new_roles)

    introduced = new_set - prev_set
    dropped = prev_set - new_set

    # Was a drop_kick applied?
    if "drums" in dropped:
        return "drop_kick"

    # Was percussion added?
    if "percussion" in introduced:
        return "add_percussion"

    # Were support roles rotated?
    if introduced and dropped and len(introduced) == len(dropped):
        return "support_swap"

    # New roles were added?
    if introduced and not dropped:
        return "role_rotation"

    # The melody role changed?
    melodic = {"melody", "synth", "arp", "pads", "chords"}
    if (prev_set & melodic) != (new_set & melodic):
        return "change_pattern"

    # Memory suggestion as final fallback.
    return memory.suggest_variation_strategy(
        section_type, occurrence, available_roles, prev_roles
    )


def _notes_for_section(section_type: str, occurrence: int) -> str:
    _NOTES: dict[str, str] = {
        "intro":     "Sparse entry — atmosphere and texture only, no groove.",
        "verse":     "Rhythmic backbone established; melody and bass carry the groove.",
        "pre_hook":  "Tension build — add edge, strip softness, drive toward hook.",
        "hook":      "Hook peak with strongest groove and lead emphasis.",
        "bridge":    "Contrast and reset — stripped groove, melodic or textural focus.",
        "breakdown": "Attention reset — subtractive, atmospheric, maximum space.",
        "outro":     "Resolution — strip layers, fade energy, close cleanly.",
    }
    note = _NOTES.get(section_type, "Controlled section change to preserve progression.")
    if occurrence > 1:
        note = f"{note} (occurrence {occurrence}: evolved from prior {section_type})"
    return note


def _transition_in_for_boundary(
    prev_type: str | None,
    current_type: str,
    prev_energy: int | None,
    current_energy: int,
    transitions_v2_enabled: bool,
) -> str:
    """Select the most appropriate transition-in for a section boundary."""
    if not transitions_v2_enabled:
        # Fall back to legacy mapping without V2 transition types
        return {
            "intro":     "none",
            "verse":     "drum_fill",
            "pre_hook":  "fx_rise",
            "hook":      "fx_rise",
            "bridge":    "mute_drop",
            "breakdown": "fx_hit",
            "outro":     "none",
        }.get(current_type, "none")

    if prev_type is None:
        return "none"

    # Energy jump → use a strong re-entry accent
    energy_jump = (current_energy - (prev_energy or 0)) >= 2
    if current_type == "hook" and energy_jump:
        return "re_entry_accent"
    if current_type == "hook":
        return "riser"
    if current_type in {"bridge", "breakdown"}:
        return "subtractive_entry"
    if current_type == "outro":
        return "subtractive_entry"
    if current_type == "pre_hook":
        return "riser"
    if current_type == "verse" and prev_type == "intro":
        return "drum_fill"
    if current_type == "verse" and prev_type in {"bridge", "breakdown"}:
        return "re_entry_accent"
    # Default: avoid hard cut
    return _DEFAULT_TRANSITION_IN.get(current_type, "none")


def _build_transition_plan(
    sections: list[SectionPlan],
    transitions_v2_enabled: bool,
) -> list[TransitionPlanEntry]:
    """Generate one TransitionPlanEntry per section boundary."""
    plan: list[TransitionPlanEntry] = []
    for idx in range(len(sections) - 1):
        curr = sections[idx]
        nxt = sections[idx + 1]
        boundary_bar = curr.start_bar + curr.bars

        transition_type = curr.transition_out
        energy_delta = abs(nxt.target_energy - curr.target_energy)
        intensity = min(1.0, 0.4 + energy_delta * 0.15)

        if not transitions_v2_enabled:
            # Skip non-rendered boundaries in legacy mode
            if transition_type in {"none"}:
                continue

        plan.append(TransitionPlanEntry(
            from_section_index=curr.index,
            to_section_index=nxt.index,
            from_section_type=curr.section_type,
            to_section_type=nxt.section_type,
            boundary_bar=boundary_bar,
            transition_type=transition_type,
            intensity=round(intensity, 3),
            description=(
                f"{curr.section_type} → {nxt.section_type}: "
                f"{transition_type} at bar {boundary_bar}"
            ),
        ))
    return plan


# ---------------------------------------------------------------------------
# Validation + auto-repair
# ---------------------------------------------------------------------------

@dataclass
class PlanValidationResult:
    """Outcome of the V2 plan validation pass."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repairs_applied: list[str] = field(default_factory=list)


def validate_and_repair_plan(
    plan: ArrangementPlanV2,
    source_quality_mode: str,
) -> PlanValidationResult:
    """Validate an :class:`ArrangementPlanV2` and auto-repair minor issues.

    Philosophy:
    - Auto-repair when safe (warn in ``repairs_applied``).
    - Hard-fail only when the plan would be misleading or fundamentally broken.
    - Do not fail on minor musical imperfections when a safe repair exists.
    """
    errors: list[str] = []
    warnings: list[str] = []
    repairs: list[str] = []

    if not plan.sections:
        errors.append("Plan contains no sections.")
        return PlanValidationResult(valid=False, errors=errors)

    # --- Energy curve changes over time ---
    hook_energies = [s.target_energy for s in plan.sections if s.section_type == "hook"]
    verse_energies = [s.target_energy for s in plan.sections if s.section_type == "verse"]

    if hook_energies and verse_energies:
        if min(hook_energies) < max(verse_energies):
            # Auto-repair: bump hook energy
            for s in plan.sections:
                if s.section_type == "hook" and s.target_energy < max(verse_energies):
                    s.target_energy = max(verse_energies)
                    plan.energy_curve[s.index] = s.target_energy
            repairs.append("Bumped hook energy to match or exceed verse energy.")

    # --- Missing transitions ---
    if plan.transition_plan:
        hook_boundary_types = {
            t.transition_type
            for t in plan.transition_plan
            if t.to_section_type == "hook"
        }
        if not hook_boundary_types - {"none"}:
            warnings.append(
                "Hooks have no explicit transition-in. "
                "Consider enabling ARRANGEMENT_TRANSITIONS_V2."
            )

    # --- Repeated sections too similar ---
    from app.services.section_identity_engine import MIN_REPEAT_DISTINCTION_THRESHOLD

    section_occurrences: dict[str, list[SectionPlan]] = {}
    for s in plan.sections:
        section_occurrences.setdefault(s.section_type, []).append(s)

    for stype, occurrences in section_occurrences.items():
        for i in range(1, len(occurrences)):
            prev_set = set(occurrences[i - 1].active_roles)
            curr_set = set(occurrences[i].active_roles)
            union = prev_set | curr_set
            jaccard = 1.0 - (len(prev_set & curr_set) / len(union)) if union else 0.0
            if jaccard < MIN_REPEAT_DISTINCTION_THRESHOLD and stype not in {
                "intro",
                "outro",
            }:
                warnings.append(
                    f"Repeated {stype} sections {i} and {i+1} are very similar "
                    f"(Jaccard distance {jaccard:.2f} < {MIN_REPEAT_DISTINCTION_THRESHOLD}). "
                    "Source material may be too limited for stronger variation."
                )

    # --- Hooks must introduce payoff ---
    for s in plan.sections:
        if s.section_type == "hook" and s.occurrence == 1:
            if not s.introduced_elements and len(s.active_roles) < 2:
                warnings.append(
                    f"Hook 1 at section {s.index} introduces no new elements and "
                    "has fewer than 2 active roles — may not provide sufficient payoff."
                )

    # --- Verse density ---
    for s in plan.sections:
        if s.section_type == "verse" and s.target_density == "full":
            # Auto-repair: downgrade to medium
            s.target_density = "medium"
            repairs.append(
                f"Downgraded verse {s.occurrence} density from 'full' to 'medium'."
            )

    # --- Source quality: stereo_fallback should never exceed 1 role ---
    if source_quality_mode == "stereo_fallback":
        for s in plan.sections:
            if len(s.active_roles) > 1:
                s.active_roles = s.active_roles[:1]
                plan.section_stem_map[s.index] = s.active_roles
                repairs.append(
                    f"Clamped section {s.index} to 1 role for stereo_fallback source quality."
                )

    return PlanValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        repairs_applied=repairs,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_arrangement_plan_v2(
    *,
    structure: list[str],
    bars_by_section: list[int],
    available_roles: list[str],
    source_quality_mode: str | SourceQualityMode | None = None,
    arrangement_preset: str | None = None,
    memory: ArrangementMemory | None = None,
    transitions_v2_enabled: bool = False,
    memory_enabled: bool = False,
) -> ArrangementPlanV2:
    """Build a fully-structured :class:`ArrangementPlanV2`.

    Parameters
    ----------
    structure:
        Ordered list of section type strings (e.g. ``["intro", "verse", "hook"]``).
    bars_by_section:
        Number of bars for each section (must be same length as *structure*).
    available_roles:
        All stem roles present in the source material.
    source_quality_mode:
        SourceQualityMode enum or string.  Defaults to ``"true_stems"`` if None.
    arrangement_preset:
        Optional preset name forwarded to the section identity engine.
    memory:
        Pre-existing :class:`ArrangementMemory` to accumulate state into.
        A fresh one is created when None.
    transitions_v2_enabled:
        When True, use V2 transition types (riser, reverse_fx, silence_gap, etc.).
    memory_enabled:
        When True, the ArrangementMemory records and influences planning.
    """
    # Resolve source quality.
    if isinstance(source_quality_mode, SourceQualityMode):
        sqm_str = source_quality_mode.value
    elif source_quality_mode is None:
        sqm_str = SourceQualityMode.TRUE_STEMS.value
    else:
        sqm_str = str(source_quality_mode).strip().lower()
        # Validate
        try:
            SourceQualityMode(sqm_str)
        except ValueError:
            sqm_str = SourceQualityMode.TRUE_STEMS.value

    # Initialise memory.
    if memory is None:
        memory = ArrangementMemory(enabled=memory_enabled)

    if not structure or not bars_by_section:
        return ArrangementPlanV2(source_quality_mode=sqm_str)

    sections: list[SectionPlan] = []
    decision_log: list[DecisionLogEntry] = []
    occurrence_counter: dict[str, int] = {}
    prev_same_type_roles: dict[str, list[str]] = {}
    prev_adjacent_roles: list[str] = []
    bar_cursor = 0

    for idx, section_type in enumerate(structure):
        occurrence_counter[section_type] = occurrence_counter.get(section_type, 0) + 1
        occurrence = occurrence_counter[section_type]

        energy = _target_energy(section_type, occurrence, sqm_str)
        density = _target_density(section_type, energy)

        # Role selection via the existing section identity engine.
        try:
            raw_roles = select_roles_for_section(
                section_type=section_type,
                available_roles=available_roles,
                occurrence=occurrence,
                prev_same_type_roles=prev_same_type_roles.get(section_type),
                prev_adjacent_roles=prev_adjacent_roles if idx > 0 else None,
                preset_name=arrangement_preset,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "select_roles_for_section failed for %s (occ=%d): %s",
                section_type,
                occurrence,
                exc,
            )
            raw_roles = available_roles[:2] if available_roles else []

        # Cap based on source quality.
        roles = _cap_roles_for_quality(raw_roles, section_type, sqm_str)
        if not roles and available_roles:
            roles = available_roles[:1]

        # Determine what was introduced / dropped vs. previous occurrence.
        prev_roles = prev_same_type_roles.get(section_type, [])
        prev_set = set(prev_roles)
        curr_set = set(roles)
        introduced = sorted(curr_set - prev_set)
        dropped = sorted(prev_set - curr_set)

        # Determine variation strategy.
        variation_strategy = _determine_variation_strategy(
            section_type=section_type,
            occurrence=occurrence,
            prev_roles=prev_roles,
            new_roles=roles,
            memory=memory,
            available_roles=available_roles,
        )

        # Choose transitions.
        prev_energy = memory.last_energy() if memory.enabled else None
        transition_in = _transition_in_for_boundary(
            prev_type=structure[idx - 1] if idx > 0 else None,
            current_type=section_type,
            prev_energy=prev_energy,
            current_energy=energy,
            transitions_v2_enabled=transitions_v2_enabled,
        )
        transition_out = _DEFAULT_TRANSITION_OUT.get(section_type, "none")

        # Build rationale string.
        rationale_parts: list[str] = []
        if occurrence > 1 and variation_strategy != "none":
            rationale_parts.append(f"variation={variation_strategy}")
        if introduced:
            rationale_parts.append(f"introduced=[{', '.join(introduced)}]")
        if dropped:
            rationale_parts.append(f"dropped=[{', '.join(dropped)}]")
        rationale_parts.append(f"quality={sqm_str}")
        rationale = "; ".join(rationale_parts) or f"first occurrence, quality={sqm_str}"

        bars = int(bars_by_section[idx]) if idx < len(bars_by_section) else 8
        label = _section_label(section_type, occurrence)

        section_plan = SectionPlan(
            name=label,
            section_type=section_type,
            occurrence=occurrence,
            index=idx,
            target_energy=energy,
            target_density=density,
            active_roles=list(roles),
            introduced_elements=introduced,
            dropped_elements=dropped,
            variation_strategy=variation_strategy,
            transition_in=transition_in,
            transition_out=transition_out,
            bars=bars,
            start_bar=bar_cursor,
            notes=_notes_for_section(section_type, occurrence),
            rationale=rationale,
        )
        sections.append(section_plan)

        # Decision log entry.
        decision_log.append(DecisionLogEntry(
            section_index=idx,
            section_label=label,
            decision=f"roles={roles}; energy={energy}; density={density}",
            reason=rationale,
            flag="ARRANGEMENT_PLAN_V2",
        ))

        # Update tracking state.
        prev_same_type_roles[section_type] = list(roles)
        prev_adjacent_roles = list(roles)
        bar_cursor += bars

        # Commit to memory.
        memory.record_section(
            section_type=section_type,
            roles=roles,
            energy=energy,
            variation_strategy=variation_strategy,
        )

    # Build plan-level flat structures.
    plan_structure = [s.section_type for s in sections]
    energy_curve = [s.target_energy for s in sections]
    section_stem_map = [list(s.active_roles) for s in sections]

    # Build transition plan.
    transition_plan = _build_transition_plan(sections, transitions_v2_enabled)

    plan = ArrangementPlanV2(
        plan_version=PLAN_V2_VERSION,
        source_quality_mode=sqm_str,
        sections=sections,
        structure=plan_structure,
        energy_curve=energy_curve,
        section_stem_map=section_stem_map,
        transition_plan=transition_plan,
        decision_log=decision_log,
        memory_snapshot=memory.to_dict() if memory.enabled else {},
        total_bars=bar_cursor,
    )

    # Validate and auto-repair.
    validation = validate_and_repair_plan(plan, sqm_str)
    if validation.repairs_applied:
        for repair in validation.repairs_applied:
            logger.info("ArrangementPlanV2 auto-repair: %s", repair)
            decision_log.append(DecisionLogEntry(
                section_index=-1,
                section_label="[auto-repair]",
                decision=repair,
                reason="validation_auto_repair",
                flag="ARRANGEMENT_PLAN_V2",
            ))
    if validation.warnings:
        for w in validation.warnings:
            logger.warning("ArrangementPlanV2 validation warning: %s", w)
    if not validation.valid:
        for e in validation.errors:
            logger.error("ArrangementPlanV2 validation error: %s", e)

    return plan


# ---------------------------------------------------------------------------
# Observability: plan-vs-actual comparison
# ---------------------------------------------------------------------------

def compare_plan_vs_actual(
    plan: ArrangementPlanV2,
    actual_stem_map_by_section: list[dict],
) -> dict:
    """Compare the V2 plan's stem map against the actual rendered stem map.

    Returns a dict with:
    - ``match_count``: sections where planned == actual roles
    - ``mismatch_count``: sections where they differ
    - ``plan_honored``: True when all sections matched
    - ``section_diffs``: list of per-section comparison dicts
    - ``unique_plan_signature_count``: unique role-set hashes in the plan
    - ``unique_actual_signature_count``: unique role-set hashes in actuals
    """
    import hashlib

    plan_map = {s.index: frozenset(s.active_roles) for s in plan.sections}
    actual_map = {
        sec.get("section_index", i): frozenset(sec.get("roles", []))
        for i, sec in enumerate(actual_stem_map_by_section)
    }

    match_count = 0
    mismatch_count = 0
    diffs: list[dict] = []

    plan_sigs: list[str] = []
    actual_sigs: list[str] = []

    for idx in range(len(plan.sections)):
        planned = plan_map.get(idx, frozenset())
        actual = actual_map.get(idx, frozenset())

        match = planned == actual
        if match:
            match_count += 1
        else:
            mismatch_count += 1

        plan_sig = hashlib.md5("|".join(sorted(planned)).encode()).hexdigest()[:12]
        actual_sig = hashlib.md5("|".join(sorted(actual)).encode()).hexdigest()[:12]
        plan_sigs.append(plan_sig)
        actual_sigs.append(actual_sig)

        diffs.append({
            "section_index": idx,
            "section_type": plan.structure[idx] if idx < len(plan.structure) else "unknown",
            "planned_roles": sorted(planned),
            "actual_roles": sorted(actual),
            "match": match,
            "plan_signature": plan_sig,
            "actual_signature": actual_sig,
        })

    return {
        "match_count": match_count,
        "mismatch_count": mismatch_count,
        "plan_honored": mismatch_count == 0,
        "section_diffs": diffs,
        "unique_plan_signature_count": len(set(plan_sigs)),
        "unique_actual_signature_count": len(set(actual_sigs)),
    }
