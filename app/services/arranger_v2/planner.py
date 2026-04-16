"""
Arranger V2 — planner.

Builds a deterministic :class:`ArrangementPlan` from available roles,
a target bar count, and arrangement state.

The planner is the orchestrator that calls the density engine, variation
engine, and transition engine in the correct order.

Default structure: intro → verse → pre_hook → hook → verse_2 → hook_2 → outro

The structure can be overridden via ``preferred_structure``.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.arranger_v2.density_engine import (
    density_float_to_label,
    density_label_to_float,
    select_stems_for_section,
)
from app.services.arranger_v2.role_engine import get_valid_role_strings
from app.services.arranger_v2.state import ArrangerState
from app.services.arranger_v2.transition_engine import (
    build_transition_plan,
    select_transition_in,
    select_transition_out,
)
from app.services.arranger_v2.types import (
    SECTION_TYPES,
    ArrangementPlan,
    SectionPlan,
)
from app.services.arranger_v2.variation_engine import apply_variation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Energy arc
# ---------------------------------------------------------------------------

# Base energy (1–5) for each section type at first occurrence.
_BASE_ENERGY: dict[str, int] = {
    "intro":     1,
    "verse":     3,
    "pre_hook":  4,
    "hook":      5,
    "bridge":    2,
    "breakdown": 2,
    "outro":     1,
}

# Density targets per section type (0.0–1.0).
_BASE_DENSITY: dict[str, float] = {
    "intro":     0.25,
    "verse":     0.55,
    "pre_hook":  0.70,
    "hook":      1.00,
    "bridge":    0.30,
    "breakdown": 0.25,
    "outro":     0.30,
}

# Default bar lengths per section type.
_DEFAULT_BARS: dict[str, int] = {
    "intro":     4,
    "verse":     8,
    "pre_hook":  4,
    "hook":      8,
    "bridge":    8,
    "breakdown": 8,
    "outro":     4,
}

# Human-readable production notes.
_SECTION_NOTES: dict[str, str] = {
    "intro":     "Sparse entry — atmosphere and texture only, no groove.",
    "verse":     "Rhythmic backbone established; melody and bass carry the groove.",
    "pre_hook":  "Tension build — add edge, strip softness, drive toward hook.",
    "hook":      "Hook peak with strongest groove and lead emphasis.",
    "bridge":    "Contrast and reset — stripped groove, melodic or textural focus.",
    "breakdown": "Attention reset — subtractive, atmospheric, maximum space.",
    "outro":     "Resolution — strip layers, fade energy, close cleanly.",
}


# ---------------------------------------------------------------------------
# Default structures
# ---------------------------------------------------------------------------

_DEFAULT_STRUCTURE_LOOP = [
    "intro", "verse", "pre_hook", "hook",
    "verse", "pre_hook", "hook", "outro",
]

_DEFAULT_STRUCTURE_FULL = [
    "intro", "verse", "pre_hook", "hook",
    "verse", "pre_hook", "hook", "bridge", "outro",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_arrangement_plan(
    available_roles: list[str],
    *,
    target_total_bars: Optional[int] = None,
    preferred_structure: Optional[list[str]] = None,
    bpm: float = 120.0,
    key: str = "C",
    source_quality_mode: str = "true_stems",
    source_type: str = "loop",
) -> ArrangementPlan:
    """Build a complete :class:`ArrangementPlan` deterministically.

    Args:
        available_roles:    Validated role strings (from role_engine).
        target_total_bars:  Desired total bar count (optional, best-effort).
        preferred_structure: Explicit section order (optional).
        bpm:                BPM of the source audio.
        key:                Musical key of the source audio.
        source_quality_mode: "true_stems" | "zip_stems" | "ai_separated" | "stereo_fallback".
        source_type:        "loop" | "full" — controls default structure selection.

    Returns:
        Fully populated :class:`ArrangementPlan`.
    """
    valid_roles = get_valid_role_strings(available_roles, strict=False)
    if not valid_roles:
        raise ValueError(
            "build_arrangement_plan: no valid roles provided.  "
            "At least one role from CANONICAL_ROLES is required."
        )

    structure = _resolve_structure(preferred_structure, source_type)
    bars_by_section = _fit_bars_to_target(structure, target_total_bars)

    state = ArrangerState()
    sections: list[SectionPlan] = []
    occurrence_counter: dict[str, int] = {}
    prev_energy: Optional[int] = None

    for idx, section_type in enumerate(structure):
        occurrence_counter[section_type] = occurrence_counter.get(section_type, 0) + 1
        occurrence = occurrence_counter[section_type]

        target_energy = _compute_energy(section_type, occurrence, state)
        target_density_float = _compute_density(section_type, target_energy, source_quality_mode)
        target_density_label = density_float_to_label(target_density_float)

        # Select roles for this section.
        roles = select_stems_for_section(
            available_roles=valid_roles,
            section_type=section_type,
            target_density=target_density_float,
            state=state,
            occurrence=occurrence,
            force_distinct=(occurrence > 1),
        )

        # Apply variation if this is a repeated section.
        prev_roles_for_type = state.previous_roles_for(section_type)
        if occurrence > 1:
            roles, variation_strategy = apply_variation(
                section_type=section_type,
                occurrence=occurrence,
                current_roles=roles,
                prev_roles=prev_roles_for_type,
                available_roles=valid_roles,
                state=state,
            )
        else:
            variation_strategy = "none"

        introduced = [r for r in roles if r not in set(prev_roles_for_type)]
        dropped = [r for r in prev_roles_for_type if r not in set(roles)]

        # Resolve transitions.
        prev_section = sections[-1] if sections else None
        prev_type = prev_section.section_type if prev_section else None
        t_in = select_transition_in(
            from_section_type=prev_type,
            to_section_type=section_type,
            from_energy=prev_energy,
            to_energy=target_energy,
        )
        # transition_out is resolved retroactively for prev section once we know next section.
        t_out = "none"  # Will be set by next iteration if applicable.

        # Patch previous section's transition_out now that we know the next type.
        if prev_section is not None:
            t_out_prev = select_transition_out(
                from_section_type=prev_type,
                to_section_type=section_type,
                from_energy=prev_energy,
                to_energy=target_energy,
            )
            prev_section.transition_out = t_out_prev

        bars = bars_by_section[idx]
        start_bar = sum(bars_by_section[:idx])

        rationale = _build_rationale(
            section_type=section_type,
            occurrence=occurrence,
            roles=roles,
            energy=target_energy,
            variation_strategy=variation_strategy,
            introduced=introduced,
            dropped=dropped,
        )

        sp = SectionPlan(
            name=_section_label(section_type, occurrence),
            section_type=section_type,
            occurrence=occurrence,
            index=idx,
            target_density=target_density_float,
            target_density_label=target_density_label,
            target_energy=target_energy,
            active_roles=list(roles),
            variation_strategy=variation_strategy,
            introduced_elements=introduced,
            dropped_elements=dropped,
            transition_in=t_in,
            transition_out=t_out,
            bars=bars,
            start_bar=start_bar,
            notes=_SECTION_NOTES.get(section_type, ""),
            rationale=rationale,
        )
        sections.append(sp)

        # Commit to state AFTER building the section plan.
        state.record_section(
            section_type=section_type,
            roles=roles,
            energy=target_energy,
            variation_strategy=variation_strategy,
        )
        prev_energy = target_energy

    total_bars = sum(sp.bars for sp in sections)

    plan = ArrangementPlan(
        sections=sections,
        structure=[sp.section_type for sp in sections],
        energy_curve=[sp.target_energy for sp in sections],
        section_stem_map=[list(sp.active_roles) for sp in sections],
        total_bars=total_bars,
        bpm=bpm,
        key=key,
        plan_version="3.0",
        source_quality_mode=source_quality_mode,
        decision_log=_build_decision_log(sections),
    )
    return plan


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_structure(
    preferred: Optional[list[str]],
    source_type: str,
) -> list[str]:
    """Return the canonical section type list to use."""
    if preferred:
        resolved = [
            s.strip().lower() for s in preferred
            if s.strip().lower() in SECTION_TYPES
        ]
        if resolved:
            return resolved

    return (
        _DEFAULT_STRUCTURE_LOOP if source_type == "loop"
        else _DEFAULT_STRUCTURE_FULL
    )


def _fit_bars_to_target(
    structure: list[str],
    target_total_bars: Optional[int],
) -> list[int]:
    """Compute bar lengths for each section to approximate the target total."""
    bars = [_DEFAULT_BARS.get(s, 8) for s in structure]
    if not target_total_bars:
        return bars

    target = max(4, int(target_total_bars))
    current = sum(bars)
    if current == target:
        return bars

    # Adjust verse, hook, bridge, breakdown sections first.
    adjust_indices = [
        i for i, s in enumerate(structure)
        if s in {"verse", "hook", "bridge", "breakdown"}
    ]
    if not adjust_indices:
        adjust_indices = list(range(len(structure)))

    step = 0
    while current != target and step < 512:
        idx = adjust_indices[step % len(adjust_indices)]
        if current < target:
            bars[idx] += 4
            current += 4
        elif bars[idx] > 4:
            bars[idx] -= 4
            current -= 4
        step += 1

    return bars


def _compute_energy(
    section_type: str,
    occurrence: int,
    state: ArrangerState,
) -> int:
    """Return 1–5 energy integer, accounting for occurrence and energy arc."""
    base = _BASE_ENERGY.get(section_type, 3)

    # Verse escalates on second occurrence.
    if section_type == "verse" and occurrence >= 2:
        base = min(5, base + 1)

    # Hook 1 is slightly restrained so Hook 2+ can escalate.
    if section_type == "hook" and occurrence == 1:
        base = 4

    # Hook 2+ escalates above Hook 1.
    if section_type == "hook" and occurrence >= 2:
        base = 5

    # Prevent flat energy: if the last 3 sections are all the same level,
    # inject a contrast nudge unless this section *should* be at that level.
    if state.is_energy_flat() and section_type not in {"intro", "outro", "bridge", "breakdown"}:
        last = state.last_energy()
        if last is not None and base == last:
            base = min(5, base + 1)

    return int(base)


def _compute_density(
    section_type: str,
    energy: int,
    source_quality_mode: str,
) -> float:
    """Return 0.0–1.0 density, scaled by source quality."""
    base = _BASE_DENSITY.get(section_type, 0.50)

    # Scale down for lower quality sources.
    quality_scale = {
        "true_stems":      1.0,
        "zip_stems":       1.0,
        "ai_separated":    0.80,
        "stereo_fallback": 0.50,
    }.get(source_quality_mode, 1.0)

    return min(1.0, round(base * quality_scale, 4))


def _section_label(section_type: str, occurrence: int) -> str:
    """Return a human-readable section name."""
    name = section_type.replace("_", " ").title()
    return f"{name} {occurrence}" if occurrence > 1 else name


def _build_rationale(
    section_type: str,
    occurrence: int,
    roles: list[str],
    energy: int,
    variation_strategy: str,
    introduced: list[str],
    dropped: list[str],
) -> str:
    parts = [
        f"energy={energy}/5",
        f"roles={','.join(roles) or 'none'}",
    ]
    if occurrence > 1:
        parts.append(f"strategy={variation_strategy}")
        if introduced:
            parts.append(f"added={','.join(introduced)}")
        if dropped:
            parts.append(f"removed={','.join(dropped)}")
    return "; ".join(parts)


def _build_decision_log(sections: list[SectionPlan]) -> list[str]:
    log: list[str] = []
    for sp in sections:
        log.append(
            f"[{sp.index}] {sp.name}: {sp.rationale}"
        )
    return log
