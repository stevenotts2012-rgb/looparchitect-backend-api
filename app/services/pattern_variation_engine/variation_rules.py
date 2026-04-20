"""
Variation rules for the Pattern Variation Engine.

Rules are applied deterministically — same input always yields the same output.

Rule 1 — Variation Frequency
    Every section must have at least one variation event every 4–8 bars.

Rule 2 — No Identical Repeats
    If section_occurrence_index > 0, at least one variation event must be injected.

Rule 3 — Energy Alignment
    Higher energy sections receive more variation density.
    Lower energy sections receive fewer but more noticeable variations.

Rule 4 — Role Safety
    Never mute all drums simultaneously.
    Never mute all bass + drums simultaneously.

Rule 5 — Hook Priority
    Hooks must have the highest variation richness and the strongest
    end-of-section transitions.
"""

from __future__ import annotations

import logging
from typing import List

from app.services.pattern_variation_engine.types import (
    PatternVariationEvent,
    VariationContext,
    VariationPlan,
)

logger = logging.getLogger(__name__)

# Minimum variation density thresholds per energy band
_ENERGY_DENSITY_MAP: List[tuple[float, float]] = [
    # (energy_threshold, minimum_variation_density)
    (0.8, 0.6),   # high energy  → dense variation
    (0.5, 0.35),  # mid energy   → moderate variation
    (0.0, 0.15),  # low energy   → sparse but impactful
]

# Minimum bars between variation events (4–8 bar window)
_MIN_VARIATION_INTERVAL = 4
_MAX_VARIATION_INTERVAL = 8

# Roles considered "drums" for Rule 4 safety checks
_DRUM_ROLES = frozenset({"drums", "percussion"})
# Roles considered "bass" for Rule 4 safety checks
_BASS_ROLES = frozenset({"bass"})

# Variation types that constitute a "mute" action
_MUTE_TYPES = frozenset({
    "bass_dropout",
    "drop_kick",
    "melody_dropout",
    "pre_drop_silence",
    "mute_secondary_elements",
    "strip_percussion_layers",
})


# ---------------------------------------------------------------------------
# Public interface — applied by PatternVariationEngine
# ---------------------------------------------------------------------------

def apply_variation_frequency_rule(
    context: VariationContext,
    variations: List[PatternVariationEvent],
) -> List[str]:
    """Rule 1: Ensure at least one variation event per 4–8 bar window.

    Returns a list of applied strategy names.
    """
    applied: List[str] = []
    if context.bars < _MIN_VARIATION_INTERVAL:
        return applied

    # Check each window
    window = _MAX_VARIATION_INTERVAL
    covered_windows: set[int] = set()

    for var in variations:
        window_index = (var.bar_start - 1) // window
        covered_windows.add(window_index)

    total_windows = max(1, (context.bars - 1) // window + 1)
    missing_windows = set(range(total_windows)) - covered_windows

    if missing_windows:
        # Inject fill events in uncovered windows
        for win_idx in sorted(missing_windows):
            bar_start = win_idx * window + 1
            bar_end = min(bar_start + window - 1, context.bars)
            # Choose an appropriate fill based on available roles
            role, vtype = _choose_fill_event(context.active_roles, bar_start)
            if role and vtype:
                variations.append(PatternVariationEvent(
                    bar_start=bar_start,
                    bar_end=bar_end,
                    role=role,
                    variation_type=vtype,
                    intensity=0.5,
                    parameters={"source": "frequency_rule"},
                ))
                applied.append(f"variation_frequency:{vtype}@bar{bar_start}")
                logger.debug(
                    "variation_rules: Rule1 injected %s on %s bars %d-%d",
                    vtype, role, bar_start, bar_end,
                )

    return applied


def apply_no_identical_repeat_rule(
    context: VariationContext,
    variations: List[PatternVariationEvent],
) -> List[str]:
    """Rule 2: Repeated sections must have at least one variation event.

    Returns a list of applied strategy names.
    """
    applied: List[str] = []
    if context.section_occurrence_index == 0:
        return applied  # First occurrence — rule does not apply

    if variations:
        return applied  # Already has variations

    # Inject a minimal distinguishing variation
    role, vtype = _choose_fill_event(context.active_roles, bar_start=1)
    if role and vtype:
        variations.append(PatternVariationEvent(
            bar_start=1,
            bar_end=context.bars,
            role=role,
            variation_type=vtype,
            intensity=0.4 + 0.1 * min(context.section_occurrence_index, 4),
            parameters={"source": "no_repeat_rule", "occurrence": context.section_occurrence_index},
        ))
        applied.append(f"no_identical_repeat:{vtype}")
        logger.debug(
            "variation_rules: Rule2 injected %s on %s for occurrence %d",
            vtype, role, context.section_occurrence_index,
        )

    return applied


def apply_energy_alignment_rule(
    context: VariationContext,
    variations: List[PatternVariationEvent],
) -> List[str]:
    """Rule 3: Align variation density with section energy.

    High energy → more variations; Low energy → fewer but impactful.
    Returns a list of applied strategy names.
    """
    applied: List[str] = []
    target_density = _target_density_for_energy(context.energy)

    if not context.active_roles:
        return applied

    max_variations = max(1, int(target_density * len(context.active_roles) * 3))
    current_count = len(variations)

    if context.energy >= 0.8 and current_count < max_variations:
        # High energy: add density boosters
        role, vtype = _choose_energy_booster(context.active_roles, context.energy)
        if role and vtype:
            mid = max(1, context.bars // 2)
            variations.append(PatternVariationEvent(
                bar_start=mid,
                bar_end=context.bars,
                role=role,
                variation_type=vtype,
                intensity=0.7 + 0.15 * min(context.section_occurrence_index, 2),
                parameters={"source": "energy_alignment", "energy": context.energy},
            ))
            applied.append(f"energy_alignment_high:{vtype}")

    elif context.energy < 0.5 and current_count > max_variations:
        # Low energy: trim to most impactful (keep highest intensity)
        variations.sort(key=lambda v: v.intensity, reverse=True)
        trimmed = current_count - max_variations
        del variations[max_variations:]
        if trimmed > 0:
            applied.append(f"energy_alignment_trim:{trimmed}_events_removed")

    return applied


def apply_role_safety_rule(
    context: VariationContext,
    variations: List[PatternVariationEvent],
) -> List[str]:
    """Rule 4: Never mute all drums or all bass+drums simultaneously.

    Removes or downgrades conflicting mute events in-place.
    Returns a list of applied strategy names.
    """
    applied: List[str] = []
    active_drum_roles = _DRUM_ROLES & set(context.active_roles)
    active_bass_roles = _BASS_ROLES & set(context.active_roles)

    if not active_drum_roles and not active_bass_roles:
        return applied

    # Check per-bar windows for simultaneous mutes
    bar_muted_roles: dict[int, set[str]] = {}
    for var in variations:
        if var.variation_type.lower() in _MUTE_TYPES:
            for bar in range(var.bar_start, var.bar_end + 1):
                bar_muted_roles.setdefault(bar, set()).add(var.role)

    violated = False
    for bar, muted in bar_muted_roles.items():
        all_drums_muted = bool(active_drum_roles) and active_drum_roles.issubset(muted)
        all_bass_muted = bool(active_bass_roles) and active_bass_roles.issubset(muted)

        if all_drums_muted:
            # Remove the last drum mute covering this bar
            for var in reversed(variations):
                if var.role in active_drum_roles and var.variation_type.lower() in _MUTE_TYPES:
                    if var.bar_start <= bar <= var.bar_end:
                        variations.remove(var)
                        applied.append(f"role_safety:removed_drum_mute_at_bar{bar}")
                        violated = True
                        break

        if all_bass_muted and all_drums_muted:
            # Remove the last bass mute covering this bar
            for var in reversed(variations):
                if var.role in active_bass_roles and var.variation_type.lower() in _MUTE_TYPES:
                    if var.bar_start <= bar <= var.bar_end:
                        variations.remove(var)
                        applied.append(f"role_safety:removed_bass_mute_at_bar{bar}")
                        violated = True
                        break

    if violated:
        logger.debug("variation_rules: Rule4 (role safety) removed conflicting mutes")

    return applied


def apply_hook_priority_rule(
    context: VariationContext,
    variations: List[PatternVariationEvent],
) -> List[str]:
    """Rule 5: Hooks must have highest variation richness and strong end transitions.

    Returns a list of applied strategy names.
    """
    applied: List[str] = []
    section_type = context.section_type
    if section_type != "hook":
        return applied

    # End-of-section transition (last 2 bars)
    end_bar = context.bars
    fill_start = max(1, context.bars - 1)
    has_end_transition = any(
        v.bar_end >= fill_start
        for v in variations
        if v.variation_type in {"drum_fill", "snare_roll", "reverse_fx_lead", "snare_fill", "perc_fill"}
    )

    if not has_end_transition and context.bars >= 4:
        role = "drums" if "drums" in context.active_roles else (
            "percussion" if "percussion" in context.active_roles else None
        )
        if role:
            variations.append(PatternVariationEvent(
                bar_start=fill_start,
                bar_end=end_bar,
                role=role,
                variation_type="drum_fill",
                intensity=0.85,
                parameters={"source": "hook_priority", "occurrence": context.occurrence},
            ))
            applied.append("hook_priority:end_transition_drum_fill")

    # Hook escalation: richness scales with occurrence
    occ = context.section_occurrence_index
    if occ >= 1:
        # Hooks 2+ add a counter element if not already present
        melody_counter = any(
            v.variation_type in {"counter_melody_add", "call_response"}
            for v in variations
            if v.role == "melody"
        )
        if not melody_counter and "melody" in context.active_roles:
            mid = max(1, context.bars // 2)
            variations.append(PatternVariationEvent(
                bar_start=mid,
                bar_end=context.bars,
                role="melody",
                variation_type="call_response",
                intensity=0.65 + 0.1 * min(occ, 3),
                parameters={"source": "hook_priority", "occurrence": context.occurrence},
            ))
            applied.append(f"hook_priority:counter_element_hook{occ + 1}")

    logger.debug(
        "variation_rules: Rule5 hook priority applied %d strategies for occ=%d",
        len(applied), occ,
    )
    return applied


# ---------------------------------------------------------------------------
# Repetition scoring
# ---------------------------------------------------------------------------

def score_repetition(active_roles: List[str], plan: VariationPlan) -> float:
    """Compute a repetition score for *plan*.

    Heuristics
    ----------
    * No variation events at all  → heavy penalty (0.0)
    * Each unique variation type adds score
    * More roles covered → higher score
    * Density influences score

    Returns a float in [0.0, 1.0].

    0.0 = fully repetitive, 1.0 = maximally varied.
    Plans scoring below 0.3 should be rejected.
    """
    if not plan.variations:
        return 0.0

    # Unique variation types
    unique_types = len({v.variation_type for v in plan.variations})
    # Roles covered
    covered_roles = len({v.role for v in plan.variations})
    total_roles = max(1, len(active_roles))

    # Base score from unique types (up to 6 unique types = full score)
    type_score = min(1.0, unique_types / 6.0)
    # Role coverage score
    role_score = min(1.0, covered_roles / total_roles)
    # Density contribution (normalised)
    density_score = max(0.0, min(1.0, plan.variation_density))

    # Combined score: weighted average
    score = 0.45 * type_score + 0.35 * role_score + 0.20 * density_score

    # Bonus for using multiple strategies
    strategy_bonus = min(0.1, len(plan.applied_strategies) * 0.02)
    score = min(1.0, score + strategy_bonus)

    logger.debug(
        "variation_rules: score_repetition section=%r → %.3f "
        "(types=%d roles=%d/%d density=%.2f strategies=%d)",
        plan.section_name,
        score,
        unique_types,
        covered_roles,
        total_roles,
        density_score,
        len(plan.applied_strategies),
    )
    return round(score, 4)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _target_density_for_energy(energy: float) -> float:
    """Return the target variation density for the given energy level."""
    for threshold, density in _ENERGY_DENSITY_MAP:
        if energy >= threshold:
            return density
    return _ENERGY_DENSITY_MAP[-1][1]


def _choose_fill_event(
    active_roles: List[str], bar_start: int
) -> tuple[str | None, str | None]:
    """Choose the most appropriate (role, variation_type) pair for a fill event."""
    if "drums" in active_roles:
        # Alternate fill types based on bar position for variety
        vtype = "drum_fill" if bar_start % 8 < 4 else "hi_hat_pattern_shift"
        return "drums", vtype
    if "percussion" in active_roles:
        return "percussion", "drum_fill"
    if "bass" in active_roles:
        return "bass", "syncopated_bass_push"
    if "melody" in active_roles:
        return "melody", "call_response"
    if active_roles:
        return active_roles[0], "reduce_high_freq_content"
    return None, None


def _choose_energy_booster(
    active_roles: List[str], energy: float
) -> tuple[str | None, str | None]:
    """Choose the most appropriate (role, variation_type) for energy boosting."""
    if "drums" in active_roles:
        return "drums", "add_ghost_notes"
    if "percussion" in active_roles:
        return "percussion", "perc_fill"
    if "bass" in active_roles:
        return "bass", "octave_lift"
    if "melody" in active_roles:
        return "melody", "counter_melody_add"
    if active_roles:
        return active_roles[0], "hat_density_up"
    return None, None
