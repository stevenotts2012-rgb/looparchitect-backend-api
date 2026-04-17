"""
Arrangement Scoring: Evaluates arrangement quality before rendering.

Prevents flat, repetitive, low-contrast arrangements from shipping by
scoring six musical dimensions and rejecting plans that fall below thresholds.

Score dimensions:
  energy_curve_score  – how much the energy curve moves (range + transitions)
  contrast_score      – section-to-section energy and density contrast
  repetition_penalty  – 0.0 = no repetition, 1.0 = fully repetitive
  hook_payoff_score   – hooks deliver energy/density uplift relative to verses
  transition_score    – boundary events cover section transitions
  role_diversity_score – variety of instrument roles across all sections

overall_score is a weighted composite (repetition_penalty is inverted).

Rejection thresholds (hard limits):
  overall_score       < OVERALL_REJECT_THRESHOLD  → reject
  energy_curve_score  < ENERGY_CURVE_REJECT_THRESHOLD → reject
  hook_payoff_score   < HOOK_PAYOFF_REJECT_THRESHOLD  → reject
  repetition_penalty  > REPETITION_REJECT_THRESHOLD   → reject
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rejection thresholds
# ---------------------------------------------------------------------------

OVERALL_REJECT_THRESHOLD: float = 0.40
ENERGY_CURVE_REJECT_THRESHOLD: float = 0.15
HOOK_PAYOFF_REJECT_THRESHOLD: float = 0.20
REPETITION_REJECT_THRESHOLD: float = 0.80

# Weights for overall_score (must sum to 1.0)
_WEIGHTS: dict[str, float] = {
    "energy_curve_score": 0.20,
    "contrast_score": 0.20,
    "repetition_score": 0.20,   # = 1 - repetition_penalty
    "hook_payoff_score": 0.20,
    "transition_score": 0.10,
    "role_diversity_score": 0.10,
}

# Section types treated as high-energy climax sections
_HOOK_TYPES: frozenset[str] = frozenset({"hook", "chorus"})

# Hook payoff scoring: how much energy uplift a hook needs for a full score
_HOOK_ENERGY_BASELINE: float = 0.30   # centre of the [lo, hi] energy-uplift window
_HOOK_ENERGY_FULL_RANGE: float = 0.60  # full range (lo = -baseline, hi = full_range - baseline)

# Transition event types that count as real boundary coverage
_TRANSITION_EVENT_TYPES: frozenset[str] = frozenset({
    "drum_fill", "riser_fx", "reverse_cymbal", "crash_hit", "silence_drop",
    "pre_hook_silence", "pre_hook_mute", "pre_hook_drum_mute",
    "silence_drop_before_hook", "snare_roll", "snare_pickup",
    "fill_event", "fill", "riser", "impact", "filter_sweep", "crossfade",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _section_type(section: dict) -> str:
    return str(section.get("type") or section.get("section_type") or "").lower().strip()


def _section_energy(section: dict) -> float:
    raw = section.get("energy") or section.get("energy_level") or 0.0
    return float(raw)


def _instrument_list(section: dict) -> list[str]:
    instruments = section.get("instruments") or section.get("active_stem_roles") or []
    return [str(i).lower().strip() for i in instruments if i]


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Score functions
# ---------------------------------------------------------------------------

def _score_energy_curve(sections: list[dict], energy_curve: list[dict]) -> float:
    """Score how much the energy moves across the arrangement."""
    # Prefer explicit energy_curve; fall back to section energies
    if energy_curve:
        energies = [float(pt.get("energy") or 0.0) for pt in energy_curve]
    elif sections:
        energies = [_section_energy(s) for s in sections]
    else:
        return 0.0

    if len(energies) < 2:
        return 0.0

    lo, hi = min(energies), max(energies)
    energy_range = hi - lo

    # Count direction changes (peaks and valleys)
    direction_changes = 0
    for i in range(1, len(energies) - 1):
        if (energies[i] > energies[i - 1] and energies[i] > energies[i + 1]) or \
           (energies[i] < energies[i - 1] and energies[i] < energies[i + 1]):
            direction_changes += 1

    range_score = _clamp(energy_range / 0.6)          # full marks at 0.6 range
    movement_score = _clamp(direction_changes / 3.0)   # full marks at 3 peaks/valleys
    return round(0.6 * range_score + 0.4 * movement_score, 4)


def _score_contrast(sections: list[dict]) -> float:
    """Score section-to-section energy and density contrast."""
    if len(sections) < 2:
        return 0.0

    energy_diffs: list[float] = []
    density_diffs: list[float] = []

    for i in range(1, len(sections)):
        prev_e = _section_energy(sections[i - 1])
        curr_e = _section_energy(sections[i])
        energy_diffs.append(abs(curr_e - prev_e))

        prev_d = len(_instrument_list(sections[i - 1]))
        curr_d = len(_instrument_list(sections[i]))
        # Normalise density diff against 5 instruments (typical max layering delta)
        density_diffs.append(_clamp(abs(curr_d - prev_d) / 5.0))

    avg_energy_diff = sum(energy_diffs) / len(energy_diffs)
    avg_density_diff = sum(density_diffs) / len(density_diffs)

    # Full marks when avg energy shift ≥ 0.3 and avg density shift ≥ 0.4
    energy_contrast = _clamp(avg_energy_diff / 0.30)
    density_contrast = _clamp(avg_density_diff / 0.40)
    return round(0.5 * energy_contrast + 0.5 * density_contrast, 4)


def _score_repetition_penalty(sections: list[dict]) -> float:
    """Return a repetition penalty in [0, 1] — higher = more repetitive."""
    if len(sections) < 2:
        return 0.0

    # Penalty for consecutive identical section types
    consecutive_same = sum(
        1 for i in range(1, len(sections))
        if _section_type(sections[i]) == _section_type(sections[i - 1])
    )
    type_penalty = _clamp(consecutive_same / max(len(sections) - 1, 1))

    # Penalty for identical instrument sets across sections
    seen_sets: list[frozenset] = []
    duplicate_count = 0
    for s in sections:
        iset = frozenset(_instrument_list(s))
        if iset and iset in seen_sets:
            duplicate_count += 1
        else:
            seen_sets.append(iset)
    instrument_penalty = _clamp(duplicate_count / max(len(sections), 1))

    return round(0.5 * type_penalty + 0.5 * instrument_penalty, 4)


def _score_hook_payoff(sections: list[dict]) -> float:
    """Score whether hook/chorus sections deliver measurable uplift."""
    hook_sections = [s for s in sections if _section_type(s) in _HOOK_TYPES]
    other_sections = [s for s in sections if _section_type(s) not in _HOOK_TYPES]

    if not hook_sections:
        # No hooks — moderate penalty but not total failure
        return 0.30

    if not other_sections:
        return 0.50

    avg_hook_energy = sum(_section_energy(s) for s in hook_sections) / len(hook_sections)
    avg_other_energy = sum(_section_energy(s) for s in other_sections) / len(other_sections)
    energy_uplift = avg_hook_energy - avg_other_energy

    avg_hook_density = sum(len(_instrument_list(s)) for s in hook_sections) / len(hook_sections)
    avg_other_density = sum(len(_instrument_list(s)) for s in other_sections) / len(other_sections)
    density_uplift = avg_hook_density - avg_other_density

    # Energy uplift: full marks at +0.3; density uplift: full marks at +2 instruments
    energy_score = _clamp((energy_uplift + _HOOK_ENERGY_BASELINE) / _HOOK_ENERGY_FULL_RANGE)
    density_score = _clamp((density_uplift + 2.0) / 4.0)
    return round(0.6 * energy_score + 0.4 * density_score, 4)


def _score_transitions(sections: list[dict], events: list[dict]) -> float:
    """Score how well transition events cover section boundaries."""
    n_boundaries = max(len(sections) - 1, 1)

    # Collect bar positions of section boundaries
    boundary_bars: set[int] = set()
    for i in range(1, len(sections)):
        bar_start = int(sections[i].get("bar_start", 0) or 0)
        # Accept events within ±2 bars of the boundary
        for offset in range(-2, 3):
            boundary_bars.add(bar_start + offset)

    # Count events that fall on or near a boundary
    covered_boundaries: set[int] = set()
    transition_types_used: set[str] = set()
    for event in events:
        etype = str(event.get("type") or "").strip().lower()
        if etype not in _TRANSITION_EVENT_TYPES:
            continue
        bar = int(event.get("bar") or 0)
        if bar in boundary_bars:
            covered_boundaries.add(bar)
            transition_types_used.add(etype)

    coverage = _clamp(len(covered_boundaries) / n_boundaries)
    variety = _clamp(len(transition_types_used) / 3.0)   # full marks at 3 distinct types
    return round(0.7 * coverage + 0.3 * variety, 4)


def _score_role_diversity(sections: list[dict]) -> float:
    """Score diversity of instrument roles across the arrangement."""
    if not sections:
        return 0.0

    # Global unique roles
    all_roles: set[str] = set()
    per_section_roles: list[set[str]] = []
    for s in sections:
        roles = set(_instrument_list(s))
        all_roles |= roles
        per_section_roles.append(roles)

    global_diversity = _clamp(len(all_roles) / 8.0)   # full marks at 8 distinct roles

    # Per-section variety: average distinct roles per section
    avg_per_section = (
        sum(len(r) for r in per_section_roles) / len(per_section_roles)
        if per_section_roles else 0
    )
    local_variety = _clamp(avg_per_section / 4.0)   # full marks at 4 roles/section on avg

    return round(0.5 * global_diversity + 0.5 * local_variety, 4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_arrangement(render_plan: dict[str, Any]) -> dict[str, Any]:
    """
    Score a render plan across six musical quality dimensions.

    Args:
        render_plan: Render plan dict (sections, events, energy_curve, …).

    Returns:
        Score breakdown dict with keys:
          energy_curve_score, contrast_score, repetition_penalty,
          hook_payoff_score, transition_score, role_diversity_score,
          overall_score.
    """
    sections: list[dict] = render_plan.get("sections") or []
    events: list[dict] = render_plan.get("events") or []
    energy_curve: list[dict] = render_plan.get("energy_curve") or []

    energy_curve_score = _score_energy_curve(sections, energy_curve)
    contrast_score = _score_contrast(sections)
    repetition_penalty = _score_repetition_penalty(sections)
    hook_payoff_score = _score_hook_payoff(sections)
    transition_score = _score_transitions(sections, events)
    role_diversity_score = _score_role_diversity(sections)

    repetition_score = round(1.0 - repetition_penalty, 4)

    overall_score = round(
        _WEIGHTS["energy_curve_score"] * energy_curve_score
        + _WEIGHTS["contrast_score"] * contrast_score
        + _WEIGHTS["repetition_score"] * repetition_score
        + _WEIGHTS["hook_payoff_score"] * hook_payoff_score
        + _WEIGHTS["transition_score"] * transition_score
        + _WEIGHTS["role_diversity_score"] * role_diversity_score,
        4,
    )

    return {
        "energy_curve_score": energy_curve_score,
        "contrast_score": contrast_score,
        "repetition_penalty": repetition_penalty,
        "hook_payoff_score": hook_payoff_score,
        "transition_score": transition_score,
        "role_diversity_score": role_diversity_score,
        "overall_score": overall_score,
    }


def evaluate_arrangement(render_plan: dict[str, Any]) -> tuple[dict[str, Any], bool, list[str]]:
    """
    Score a render plan and determine whether it passes quality thresholds.

    Returns:
        (score_breakdown, passed, rejection_reasons)
          score_breakdown – full score dict from score_arrangement()
          passed          – True if the plan meets all thresholds
          rejection_reasons – list of human-readable failure messages
    """
    breakdown = score_arrangement(render_plan)
    reasons: list[str] = []

    if breakdown["overall_score"] < OVERALL_REJECT_THRESHOLD:
        reasons.append(
            f"overall_score {breakdown['overall_score']:.2f} is below "
            f"minimum threshold {OVERALL_REJECT_THRESHOLD:.2f} — arrangement lacks quality"
        )

    if breakdown["energy_curve_score"] < ENERGY_CURVE_REJECT_THRESHOLD:
        reasons.append(
            f"energy_curve_score {breakdown['energy_curve_score']:.2f} is below "
            f"minimum threshold {ENERGY_CURVE_REJECT_THRESHOLD:.2f} — energy is completely flat"
        )

    if breakdown["hook_payoff_score"] < HOOK_PAYOFF_REJECT_THRESHOLD:
        reasons.append(
            f"hook_payoff_score {breakdown['hook_payoff_score']:.2f} is below "
            f"minimum threshold {HOOK_PAYOFF_REJECT_THRESHOLD:.2f} — hooks deliver no uplift"
        )

    if breakdown["repetition_penalty"] > REPETITION_REJECT_THRESHOLD:
        reasons.append(
            f"repetition_penalty {breakdown['repetition_penalty']:.2f} exceeds "
            f"maximum threshold {REPETITION_REJECT_THRESHOLD:.2f} — arrangement is too repetitive"
        )

    passed = len(reasons) == 0
    return breakdown, passed, reasons


def score_and_reject(render_plan: dict[str, Any]) -> dict[str, Any]:
    """
    Score a render plan and raise ``ValueError`` if it fails quality thresholds.

    This is the primary integration point: call it after structural validation
    and before invoking the render pipeline.

    Args:
        render_plan: Render plan dict.

    Returns:
        Score breakdown dict (for logging / storage by the caller).

    Raises:
        ValueError: If the arrangement fails one or more quality thresholds,
                    with a message that lists every failing dimension.
    """
    breakdown, passed, reasons = evaluate_arrangement(render_plan)

    sections_count = len(render_plan.get("sections") or [])
    logger.info(
        "ARRANGEMENT_SCORE sections=%d overall=%.2f energy_curve=%.2f contrast=%.2f "
        "repetition_penalty=%.2f hook_payoff=%.2f transition=%.2f role_diversity=%.2f",
        sections_count,
        breakdown["overall_score"],
        breakdown["energy_curve_score"],
        breakdown["contrast_score"],
        breakdown["repetition_penalty"],
        breakdown["hook_payoff_score"],
        breakdown["transition_score"],
        breakdown["role_diversity_score"],
    )

    if not passed:
        rejection_detail = "; ".join(reasons)
        logger.warning(
            "ARRANGEMENT_REJECTED: %s | scores=%s",
            rejection_detail,
            breakdown,
        )
        raise ValueError(
            f"Arrangement rejected by quality scorer ({len(reasons)} issue(s)): {rejection_detail}"
        )

    logger.info("ARRANGEMENT_APPROVED: overall=%.2f", breakdown["overall_score"])
    return breakdown
