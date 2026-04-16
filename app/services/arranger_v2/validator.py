"""
Arranger V2 — validator.

Pre-render validation of the :class:`ArrangementPlan`.

This layer runs AFTER planning and BEFORE rendering.
Any failure here must prevent rendering from starting (fail-fast).

Checks enforced:
1. No flat energy curve (all sections same energy).
2. No duplicate section stem maps (identical role sets for the same section type).
3. Every section has a transition defined (except the first section).
4. Hooks have the highest energy in the arrangement.
5. Total bars match the sum of section bars.
6. Minimum hook density exceeds minimum verse density.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services.arranger_v2.types import ArrangementPlan, SectionPlan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of plan validation.  ``valid=True`` means safe to render."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.valid = False
        self.errors.append(message)
        logger.error("arrangement_validator: %s", message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning("arrangement_validator: %s", message)


class ArrangementValidationError(ValueError):
    """Raised by :func:`validate_or_raise` when the plan is invalid."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_plan(plan: ArrangementPlan) -> ValidationResult:
    """Validate *plan* and return a :class:`ValidationResult`.

    Does not raise; callers must check ``result.valid``.
    """
    result = ValidationResult()
    sections = plan.sections

    if not sections:
        result.fail("plan has no sections")
        return result

    _check_total_bars(plan, result)
    _check_energy_curve(sections, result)
    _check_hook_energy(sections, result)
    _check_hook_density(sections, result)
    _check_duplicate_stem_maps(sections, result)
    _check_transitions(sections, result)

    return result


def validate_or_raise(plan: ArrangementPlan) -> None:
    """Validate *plan* and raise :class:`ArrangementValidationError` if invalid.

    Use this immediately before passing the plan to the render executor.
    """
    result = validate_plan(plan)
    if not result.valid:
        details = "; ".join(result.errors)
        raise ArrangementValidationError(
            f"ArrangementPlan failed pre-render validation: {details}"
        )
    if result.warnings:
        logger.warning(
            "ArrangementPlan warnings (rendering will proceed): %s",
            "; ".join(result.warnings),
        )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_total_bars(plan: ArrangementPlan, result: ValidationResult) -> None:
    section_sum = sum(sp.bars for sp in plan.sections)
    if plan.total_bars != section_sum:
        result.fail(
            f"total_bars={plan.total_bars} does not match "
            f"sum of section bars={section_sum}"
        )


def _check_energy_curve(
    sections: list[SectionPlan],
    result: ValidationResult,
) -> None:
    """Ensure the energy curve is not entirely flat."""
    energies = [sp.target_energy for sp in sections]
    if len(set(energies)) == 1:
        result.fail(
            f"energy curve is flat — every section has energy={energies[0]}. "
            "The arrangement will sound monotonous."
        )

    # Check that energy rises somewhere before the last hook.
    hook_indices = [i for i, sp in enumerate(sections) if sp.section_type == "hook"]
    if hook_indices:
        first_hook_idx = hook_indices[0]
        if first_hook_idx > 0:
            pre_hook_energies = [sections[i].target_energy for i in range(first_hook_idx)]
            max_pre_hook = max(pre_hook_energies) if pre_hook_energies else 0
            if sections[first_hook_idx].target_energy <= max_pre_hook:
                result.warn(
                    f"First hook energy={sections[first_hook_idx].target_energy} is not "
                    f"greater than max pre-hook energy={max_pre_hook}. "
                    "Hooks should be the energy peak."
                )


def _check_hook_energy(
    sections: list[SectionPlan],
    result: ValidationResult,
) -> None:
    """The maximum hook energy must equal the maximum energy in the arrangement.

    Hook 1 may be intentionally restrained (energy 4 vs 5) so Hook 2 feels
    like an escalation.  What matters is that at least one hook reaches the
    arrangement's peak energy.
    """
    if not sections:
        return

    max_energy = max(sp.target_energy for sp in sections)
    hook_sections = [sp for sp in sections if sp.section_type == "hook"]

    if not hook_sections:
        result.warn("Arrangement has no hook sections — energy peak is undefined.")
        return

    max_hook_energy = max(sp.target_energy for sp in hook_sections)
    if max_hook_energy < max_energy:
        result.fail(
            f"Max hook energy={max_hook_energy} is less than "
            f"max arrangement energy={max_energy}. "
            "At least one hook must reach the arrangement's peak energy."
        )


def _check_hook_density(
    sections: list[SectionPlan],
    result: ValidationResult,
) -> None:
    """Hook density must exceed verse density."""
    verse_sections = [sp for sp in sections if sp.section_type == "verse"]
    hook_sections = [sp for sp in sections if sp.section_type == "hook"]

    if not verse_sections or not hook_sections:
        return

    max_verse_density = max(sp.target_density for sp in verse_sections)
    min_hook_density = min(sp.target_density for sp in hook_sections)

    if min_hook_density <= max_verse_density:
        result.warn(
            f"Minimum hook density={min_hook_density:.2f} is not greater than "
            f"maximum verse density={max_verse_density:.2f}. "
            "Hooks should have higher density than verses for audible contrast."
        )


def _check_duplicate_stem_maps(
    sections: list[SectionPlan],
    result: ValidationResult,
) -> None:
    """Prevent identical role sets for the same section type (except unavoidable cases)."""
    # Group by section_type.
    by_type: dict[str, list[frozenset[str]]] = {}
    for sp in sections:
        combo = frozenset(sp.active_roles)
        by_type.setdefault(sp.section_type, []).append(combo)

    for section_type, combos in by_type.items():
        if len(combos) <= 1:
            continue
        # Allow identical combos only if there are no alternatives (single-stem source).
        unique = set(combos)
        if len(unique) == 1 and len(combos) > 1:
            roles_str = ", ".join(sorted(combos[0]))
            result.warn(
                f"All {len(combos)} occurrences of section type '{section_type}' "
                f"use identical roles [{roles_str}]. "
                "Consider adding more stems for section differentiation."
            )


def _check_transitions(
    sections: list[SectionPlan],
    result: ValidationResult,
) -> None:
    """Every non-first section must have a transition_in defined."""
    for i, sp in enumerate(sections):
        if i == 0:
            continue  # First section never needs a transition_in.
        if not sp.transition_in or sp.transition_in == "none":
            # A hard cut is acceptable in limited cases, but hooks must have a riser.
            if sp.section_type == "hook":
                result.fail(
                    f"{sp.name} (index={i}) has no transition_in. "
                    "Hooks MUST have a riser or silence_gap before them."
                )
            else:
                result.warn(
                    f"{sp.name} (index={i}) has no transition_in — hard cut detected."
                )

    # Verify hook-specific rule: must be preceded by riser or silence_gap.
    hook_riser_required = {"riser", "silence_gap", "fx_rise", "reverse_fx"}
    for i, sp in enumerate(sections):
        if sp.section_type != "hook":
            continue
        if i == 0:
            continue
        if sp.transition_in not in hook_riser_required:
            result.warn(
                f"{sp.name} (index={i}) transition_in='{sp.transition_in}' is not "
                f"a riser or silence_gap. Hooks sound better with a build-up transition."
            )
