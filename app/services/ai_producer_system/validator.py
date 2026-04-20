"""
Validator — hard-rule validation applied after all repair passes.

Rules
-----
1.  No flat energy curve (span must be >= MIN_ENERGY_SPAN).
2.  No repeated identical section plans when source allows more.
3.  Hooks must tie for or exceed max energy.
4.  Bridge/breakdown must have density < arrangement average.
5.  Outro must have energy AND density below arrangement averages.
6.  No vague phrases remaining in variation strategies or rationale.
7.  No missing transition fields (transition_in / transition_out).
8.  No empty micro plan when plan has >= 16 bars and source is not weak.

Critical violations cause rejection.
Warnings are informational only.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.ai_producer_system.schemas import AIProducerPlan, AISectionPlan
from app.services.ai_producer_system.scoring import (
    MIN_ENERGY_VARIANCE,
    contains_vague_phrase,
    energy_variance,
)

logger = logging.getLogger(__name__)

# Minimum energy span to avoid a flat curve (matches MIN_ENERGY_VARIANCE)
_MIN_ENERGY_SPAN = MIN_ENERGY_VARIANCE

# Roles threshold below which we consider source "too weak" for micro plan enforcement
_WEAK_SOURCE_ROLES_THRESHOLD = 2


class ValidatorError(Exception):
    """Raised when a critical validation rule is violated."""


def validate_plan(
    plan: AIProducerPlan,
    available_roles: Optional[list[str]] = None,
    source_quality: str = "stereo_fallback",
) -> tuple[bool, list[str]]:
    """Validate *plan* against all hard rules.

    Parameters
    ----------
    plan:
        The plan to validate.
    available_roles:
        All stem roles available.  Used to decide whether micro-plan
        enforcement applies.
    source_quality:
        One of ``"true_stems"``, ``"zip_stems"``, ``"ai_separated"``,
        ``"stereo_fallback"``.

    Returns
    -------
    tuple[bool, list[str]]
        ``(passed, warnings)`` where ``passed`` is ``False`` if any
        critical rule was violated.
    """
    warnings: list[str] = []
    critical_violations: list[str] = []

    roles = list(available_roles or [])
    is_weak_source = (
        source_quality == "stereo_fallback"
        or len(roles) < _WEAK_SOURCE_ROLES_THRESHOLD
    )

    section_plans = plan.section_plans

    # ------------------------------------------------------------------
    # Rule 1: No flat energy curve
    # ------------------------------------------------------------------
    span = energy_variance(plan.global_energy_curve)
    if plan.global_energy_curve and span < _MIN_ENERGY_SPAN:
        critical_violations.append(
            f"FLAT_ENERGY_CURVE: span={span:.4f} < {_MIN_ENERGY_SPAN}. "
            "Arrangement must have dynamic range."
        )

    # ------------------------------------------------------------------
    # Rule 2: No repeated identical section plans
    # ------------------------------------------------------------------
    if not is_weak_source:
        seen: dict[str, AISectionPlan] = {}
        for sp in section_plans:
            key = sp.section_name
            if key in seen:
                prior = seen[key]
                # Identical = same energy AND same density AND same roles
                same_energy = abs(sp.target_energy - prior.target_energy) < 0.01
                same_density = abs(sp.target_density - prior.target_density) < 0.01
                same_roles = set(sp.active_roles) == set(prior.active_roles)
                if same_energy and same_density and same_roles:
                    critical_violations.append(
                        f"IDENTICAL_REPEATED_SECTION: '{sp.section_name}' "
                        f"occurrence {sp.occurrence} is identical to occurrence "
                        f"{prior.occurrence} (energy, density, and roles all match)."
                    )
            seen[key] = sp

    # ------------------------------------------------------------------
    # Rule 3: Hooks must tie for or exceed max energy
    # ------------------------------------------------------------------
    if section_plans:
        all_energies = [sp.target_energy for sp in section_plans]
        max_energy = max(all_energies)
        hooks = [sp for sp in section_plans if sp.section_name in ("hook", "chorus", "drop")]
        if hooks:
            hook_max = max(h.target_energy for h in hooks)
            if hook_max < max_energy - 0.01:
                critical_violations.append(
                    f"HOOK_ENERGY_TOO_LOW: max hook energy {hook_max:.3f} < "
                    f"arrangement max {max_energy:.3f}. Hook must equal or exceed max energy."
                )

    # ------------------------------------------------------------------
    # Rule 4: Bridge/breakdown density below average
    # ------------------------------------------------------------------
    if section_plans:
        avg_density = sum(sp.target_density for sp in section_plans) / len(section_plans)
        for sp in section_plans:
            if sp.section_name in ("bridge", "breakdown"):
                if sp.target_density >= avg_density:
                    critical_violations.append(
                        f"BRIDGE_BREAKDOWN_DENSITY: '{sp.section_name}' density "
                        f"{sp.target_density:.3f} >= avg {avg_density:.3f}. "
                        "Must be below average."
                    )

    # ------------------------------------------------------------------
    # Rule 5: Outro energy AND density below average
    # ------------------------------------------------------------------
    if section_plans:
        avg_energy = sum(sp.target_energy for sp in section_plans) / len(section_plans)
        avg_density = sum(sp.target_density for sp in section_plans) / len(section_plans)
        for sp in section_plans:
            if sp.section_name == "outro":
                if sp.target_energy >= avg_energy:
                    critical_violations.append(
                        f"OUTRO_ENERGY: outro energy {sp.target_energy:.3f} >= "
                        f"avg {avg_energy:.3f}. Outro must wind down."
                    )
                if sp.target_density >= avg_density:
                    critical_violations.append(
                        f"OUTRO_DENSITY: outro density {sp.target_density:.3f} >= "
                        f"avg {avg_density:.3f}. Outro must simplify."
                    )

    # ------------------------------------------------------------------
    # Rule 6: No vague phrases
    # ------------------------------------------------------------------
    for sp in section_plans:
        for field_name, text in (
            ("variation_strategy", sp.variation_strategy),
            ("rationale", sp.rationale),
        ):
            if contains_vague_phrase(text):
                critical_violations.append(
                    f"VAGUE_PHRASE in '{sp.section_name}' {field_name}: "
                    f"'{text[:60]}...' — replace with concrete instructions."
                )

    # ------------------------------------------------------------------
    # Rule 7: No missing transition fields
    # ------------------------------------------------------------------
    for sp in section_plans:
        if not sp.transition_in:
            critical_violations.append(
                f"MISSING_TRANSITION_IN: '{sp.section_name}' has no transition_in."
            )
        if not sp.transition_out:
            critical_violations.append(
                f"MISSING_TRANSITION_OUT: '{sp.section_name}' has no transition_out."
            )

    # ------------------------------------------------------------------
    # Rule 8: No empty micro plan on long sections (unless weak source)
    # ------------------------------------------------------------------
    if not is_weak_source:
        total_bars = sum(sp.bars for sp in section_plans)
        if total_bars >= 16 and not plan.micro_plan_events:
            warnings.append(
                "EMPTY_MICRO_PLAN: arrangement has >= 16 bars but no micro-plan events. "
                "Consider adding internal motion events."
            )

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------
    passed = len(critical_violations) == 0

    for v in critical_violations:
        logger.warning("VALIDATOR CRITICAL: %s", v)
    for w in warnings:
        logger.info("VALIDATOR WARNING: %s", w)

    all_messages = critical_violations + warnings
    return passed, all_messages
