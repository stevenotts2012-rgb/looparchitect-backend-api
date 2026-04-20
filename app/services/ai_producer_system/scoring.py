"""
Deterministic scoring helpers for the AI Producer System.

All functions are pure and side-effect-free.  No randomness is used.
"""

from __future__ import annotations

import re
from typing import Sequence

from app.services.ai_producer_system.schemas import (
    AISectionPlan,
    AIMicroPlanEvent,
    AIProducerPlan,
    VAGUE_PHRASES,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum Jaccard contrast score to consider two section plans "different enough"
CONTRAST_THRESHOLD = 0.30

# Minimum energy variance across sections to avoid a flat curve
MIN_ENERGY_VARIANCE = 0.10

# Critical subscore threshold — any subscore below this triggers rejection
CRITICAL_SUBSCORE_THRESHOLD = 0.30

# Overall score threshold for acceptance
OVERALL_ACCEPTANCE_THRESHOLD = 0.55


# ---------------------------------------------------------------------------
# Jaccard contrast
# ---------------------------------------------------------------------------

def jaccard_contrast(set_a: set, set_b: set) -> float:
    """Return Jaccard distance between two sets (1.0 − similarity).

    A higher distance means the sets are more different.

    >>> jaccard_contrast({"a", "b"}, {"c", "d"})
    1.0
    >>> jaccard_contrast({"a", "b"}, {"a", "b"})
    0.0
    """
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    intersection = set_a & set_b
    similarity = len(intersection) / len(union)
    return 1.0 - similarity


def section_role_contrast(plan_a: AISectionPlan, plan_b: AISectionPlan) -> float:
    """Jaccard distance between the ``active_roles`` sets of two section plans."""
    return jaccard_contrast(set(plan_a.active_roles), set(plan_b.active_roles))


def section_element_contrast(plan_a: AISectionPlan, plan_b: AISectionPlan) -> float:
    """Measure structural difference between two section plan snapshots.

    Considers active roles, introduced elements, transition types, and energy.
    Returns a value in ``[0.0, 1.0]`` where 1.0 is maximally different.
    """
    role_diff = jaccard_contrast(set(plan_a.active_roles), set(plan_b.active_roles))

    intro_diff = jaccard_contrast(
        set(plan_a.introduced_elements), set(plan_b.introduced_elements)
    )

    trans_diff = float(
        plan_a.transition_in != plan_b.transition_in
        or plan_a.transition_out != plan_b.transition_out
    )

    energy_diff = abs(plan_a.target_energy - plan_b.target_energy)
    density_diff = abs(plan_a.target_density - plan_b.target_density)

    # Weighted composite
    score = (
        role_diff * 0.35
        + intro_diff * 0.25
        + trans_diff * 0.20
        + min(energy_diff, 1.0) * 0.10
        + min(density_diff, 1.0) * 0.10
    )
    return min(1.0, score)


# ---------------------------------------------------------------------------
# Hook novelty
# ---------------------------------------------------------------------------

def hook_novelty_vs_prior_sections(
    hook_plan: AISectionPlan,
    prior_sections: Sequence[AISectionPlan],
) -> float:
    """Score how different a hook is from all prior non-hook sections.

    Returns a value in ``[0.0, 1.0]``.  Higher is more novel.
    """
    if not prior_sections:
        return 1.0

    contrasts = [section_element_contrast(hook_plan, p) for p in prior_sections]
    return sum(contrasts) / len(contrasts)


def hook_payoff_score(
    hook_plan: AISectionPlan,
    verse_plans: Sequence[AISectionPlan],
) -> float:
    """Return a payoff score for a hook relative to its verse counterparts.

    Rules:
    - Hook energy must exceed average verse energy.
    - Hook density must equal or exceed average verse density.
    - Hook must have introduced_elements.

    Returns ``[0.0, 1.0]``.
    """
    if not verse_plans:
        # No verses to compare — give partial credit
        energy_ok = float(hook_plan.target_energy >= 0.7)
        has_intro = float(bool(hook_plan.introduced_elements))
        return (energy_ok * 0.6 + has_intro * 0.4)

    avg_verse_energy = sum(v.target_energy for v in verse_plans) / len(verse_plans)
    avg_verse_density = sum(v.target_density for v in verse_plans) / len(verse_plans)

    energy_margin = hook_plan.target_energy - avg_verse_energy
    density_margin = hook_plan.target_density - avg_verse_density

    energy_score = min(1.0, max(0.0, 0.5 + energy_margin * 2.0))
    density_score = min(1.0, max(0.0, 0.5 + density_margin * 2.0))
    intro_score = min(1.0, len(hook_plan.introduced_elements) * 0.33)

    return (energy_score * 0.45 + density_score * 0.30 + intro_score * 0.25)


# ---------------------------------------------------------------------------
# Energy variance
# ---------------------------------------------------------------------------

def energy_variance(energy_curve: Sequence[float]) -> float:
    """Return the span (max - min) of the energy curve.

    A span of 0 means perfectly flat; 1.0 means maximum variation.
    """
    if not energy_curve:
        return 0.0
    return max(energy_curve) - min(energy_curve)


def energy_curve_score(energy_curve: Sequence[float]) -> float:
    """Score the energy curve on a 0–1 scale.

    Penalises flat curves.  A span >= 0.30 gets full marks.
    """
    span = energy_variance(energy_curve)
    return min(1.0, span / 0.30)


# ---------------------------------------------------------------------------
# Timeline event density
# ---------------------------------------------------------------------------

def timeline_event_density(
    micro_events: Sequence[AIMicroPlanEvent],
    total_bars: int,
) -> float:
    """Return a density score for micro-plan events.

    More events per bar → higher score, capped at 1.0.
    Threshold: at least one event per 8 bars is considered good.
    """
    if total_bars <= 0:
        return 0.0
    events_per_bar = len(micro_events) / total_bars
    # 1 event per 8 bars = score of 1.0
    return min(1.0, events_per_bar * 8.0)


# ---------------------------------------------------------------------------
# Transition diversity
# ---------------------------------------------------------------------------

def transition_diversity(section_plans: Sequence[AISectionPlan]) -> float:
    """Score how varied the transition types are across sections.

    More unique transitions → higher score.  A single repeated transition
    everywhere scores 0.0.
    """
    if not section_plans:
        return 1.0

    transitions: list[str] = []
    for sp in section_plans:
        transitions.append(sp.transition_in)
        transitions.append(sp.transition_out)

    if not transitions:
        return 1.0

    unique = len(set(transitions))
    total = len(transitions)
    raw = unique / total
    # Boost: even 0.3 unique ratio is acceptable
    return min(1.0, raw / 0.3)


# ---------------------------------------------------------------------------
# Vague phrase detection
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def contains_vague_phrase(text: str) -> bool:
    """Return ``True`` if *text* contains any known vague production phrase."""
    normalised = _normalise(text)
    for phrase in VAGUE_PHRASES:
        if phrase in normalised:
            return True
    return False


def vague_phrase_penalty(plan: AIProducerPlan) -> float:
    """Return a vagueness penalty in ``[0.0, 1.0]``.

    0.0 means totally vague; 1.0 means no vague phrases detected.
    """
    fields_to_check: list[str] = [plan.planner_notes]
    for sp in plan.section_plans:
        fields_to_check.extend([
            sp.variation_strategy,
            sp.micro_timeline_notes,
            sp.rationale,
        ])

    total = len(fields_to_check)
    if total == 0:
        return 1.0

    vague_count = sum(1 for t in fields_to_check if contains_vague_phrase(t))
    return 1.0 - (vague_count / total)


# ---------------------------------------------------------------------------
# Plan completeness
# ---------------------------------------------------------------------------

def plan_completeness_score(plan: AIProducerPlan) -> float:
    """Return a completeness score in ``[0.0, 1.0]``.

    Checks that:
    - section_plans is non-empty
    - global_energy_curve matches section count
    - repeated sections have a non-empty variation_strategy
    - all section plans have rationale
    - micro_plan_events is non-empty for plans with many bars
    """
    if not plan.section_plans:
        return 0.0

    checks_passed = 0
    total_checks = 0

    # Check 1: energy curve length matches section count
    total_checks += 1
    if len(plan.global_energy_curve) == len(plan.section_plans):
        checks_passed += 1

    # Check 2: repeated sections have variation_strategy
    name_counts: dict[str, int] = {}
    for sp in plan.section_plans:
        name_counts[sp.section_name] = name_counts.get(sp.section_name, 0) + 1

    for sp in plan.section_plans:
        if name_counts.get(sp.section_name, 1) > 1 and sp.occurrence > 1:
            total_checks += 1
            if sp.variation_strategy and not contains_vague_phrase(sp.variation_strategy):
                checks_passed += 1

    # Check 3: all sections have rationale
    for sp in plan.section_plans:
        total_checks += 1
        if sp.rationale:
            checks_passed += 1

    # Check 4: micro events exist
    total_bars = sum(sp.bars for sp in plan.section_plans)
    if total_bars >= 16:
        total_checks += 1
        if plan.micro_plan_events:
            checks_passed += 1

    if total_checks == 0:
        return 1.0

    return checks_passed / total_checks


# ---------------------------------------------------------------------------
# Repeated section contrast helpers
# ---------------------------------------------------------------------------

def repeated_section_contrast_score(section_plans: Sequence[AISectionPlan]) -> float:
    """Score how different repeated sections are from each other.

    Groups sections by name, then for each group with >1 occurrence computes
    pairwise element contrast.  Returns average across all such groups.
    Returns 1.0 if there are no repeated sections.
    """
    groups: dict[str, list[AISectionPlan]] = {}
    for sp in section_plans:
        groups.setdefault(sp.section_name, []).append(sp)

    repeated_groups = [g for g in groups.values() if len(g) > 1]
    if not repeated_groups:
        return 1.0

    scores: list[float] = []
    for group in repeated_groups:
        for i in range(len(group) - 1):
            contrast = section_element_contrast(group[i], group[i + 1])
            scores.append(contrast)

    return sum(scores) / len(scores) if scores else 1.0
