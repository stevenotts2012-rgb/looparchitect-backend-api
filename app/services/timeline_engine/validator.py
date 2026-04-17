"""
Validation rules for :class:`~app.services.timeline_engine.types.TimelinePlan`.

A validator checks a completed plan against a set of musical rules and returns
a list of :class:`ValidationIssue` objects.  An empty list means the plan is
valid.  Issues carry a ``severity`` of ``"error"`` or ``"warning"`` so callers
can decide whether to reject or merely log.
"""

from dataclasses import dataclass
from typing import List

from app.services.timeline_engine.types import TimelinePlan, TimelineSection


@dataclass
class ValidationIssue:
    """A single validation finding.

    Attributes:
        rule: Short machine-readable rule identifier.
        severity: ``"error"`` or ``"warning"``.
        message: Human-readable explanation.
        section_name: The section that triggered the issue, if applicable.
    """

    rule: str
    severity: str
    message: str
    section_name: str = ""


class TimelineValidator:
    """Validates a :class:`TimelinePlan` against producer-quality rules."""

    # Minimum energy delta across the whole plan to avoid a flat curve
    _FLAT_ENERGY_THRESHOLD = 0.1

    # A long section is one with more bars than this
    _LONG_SECTION_BARS = 12

    def validate(self, plan: TimelinePlan) -> List[ValidationIssue]:
        """Run all rules and return accumulated issues."""
        issues: List[ValidationIssue] = []

        if not plan.sections:
            issues.append(ValidationIssue(
                rule="empty_plan",
                severity="error",
                message="Plan contains no sections.",
            ))
            return issues

        issues.extend(self._check_no_flat_timeline(plan))
        issues.extend(self._check_no_empty_events_on_long_sections(plan))
        issues.extend(self._check_hook_is_highest_energy(plan))
        issues.extend(self._check_outro_reduces_energy(plan))
        issues.extend(self._check_repeated_sections_differ(plan))

        return issues

    # ------------------------------------------------------------------ #
    # Individual rules                                                     #
    # ------------------------------------------------------------------ #

    def _check_no_flat_timeline(self, plan: TimelinePlan) -> List[ValidationIssue]:
        """The energy curve must have meaningful variation."""
        issues: List[ValidationIssue] = []

        if len(plan.energy_curve) < 2:
            return issues

        span = max(plan.energy_curve) - min(plan.energy_curve)
        if span < self._FLAT_ENERGY_THRESHOLD:
            issues.append(ValidationIssue(
                rule="flat_timeline",
                severity="error",
                message=(
                    f"Energy curve is flat (range={span:.3f}). "
                    f"Minimum required variation is {self._FLAT_ENERGY_THRESHOLD}."
                ),
            ))
        return issues

    def _check_no_empty_events_on_long_sections(
        self, plan: TimelinePlan
    ) -> List[ValidationIssue]:
        """Long sections with no events suggest stale arrangement material."""
        issues: List[ValidationIssue] = []
        for section in plan.sections:
            if section.bars > self._LONG_SECTION_BARS and not section.events:
                issues.append(ValidationIssue(
                    rule="empty_events_long_section",
                    severity="warning",
                    message=(
                        f"Section '{section.name}' has {section.bars} bars but no events. "
                        "Consider adding variation events or limiting section length."
                    ),
                    section_name=section.name,
                ))
        return issues

    def _check_hook_is_highest_energy(self, plan: TimelinePlan) -> List[ValidationIssue]:
        """Hooks must be the highest-energy section or tied for highest."""
        issues: List[ValidationIssue] = []

        if not plan.energy_curve:
            return issues

        peak_energy = max(plan.energy_curve)

        for section, energy in zip(plan.sections, plan.energy_curve):
            if section.name.lower() in ("hook", "chorus"):
                if energy < peak_energy - 0.05:
                    issues.append(ValidationIssue(
                        rule="hook_not_peak_energy",
                        severity="error",
                        message=(
                            f"Section '{section.name}' energy ({energy:.2f}) is not the "
                            f"highest in the plan (peak={peak_energy:.2f}). "
                            "Hooks must be at or tied for peak energy."
                        ),
                        section_name=section.name,
                    ))
        return issues

    def _check_outro_reduces_energy(self, plan: TimelinePlan) -> List[ValidationIssue]:
        """The outro must have lower energy than the average non-outro energy."""
        issues: List[ValidationIssue] = []

        outro_pairs = [
            (s, e)
            for s, e in zip(plan.sections, plan.energy_curve)
            if s.name.lower() == "outro"
        ]
        non_outro_energies = [
            e
            for s, e in zip(plan.sections, plan.energy_curve)
            if s.name.lower() != "outro"
        ]

        if not outro_pairs or not non_outro_energies:
            return issues

        avg_non_outro = sum(non_outro_energies) / len(non_outro_energies)

        for section, energy in outro_pairs:
            if energy >= avg_non_outro:
                issues.append(ValidationIssue(
                    rule="outro_not_reduced_energy",
                    severity="error",
                    message=(
                        f"Outro energy ({energy:.2f}) is not lower than the average "
                        f"non-outro energy ({avg_non_outro:.2f}). "
                        "The outro must progressively reduce energy."
                    ),
                    section_name=section.name,
                ))
        return issues

    def _check_repeated_sections_differ(self, plan: TimelinePlan) -> List[ValidationIssue]:
        """Repeated sections should have at least one variation event."""
        issues: List[ValidationIssue] = []

        # Build a map: section_name → list of event-count per occurrence
        occurrence_events: dict = {}
        for section in plan.sections:
            key = section.name.lower()
            occurrence_events.setdefault(key, []).append(len(section.events))

        for name, event_counts in occurrence_events.items():
            if len(event_counts) < 2:
                continue
            if len(set(event_counts)) == 1:
                issues.append(ValidationIssue(
                    rule="repeated_section_no_variation",
                    severity="warning",
                    message=(
                        f"All occurrences of '{name}' have the same number of events "
                        f"({event_counts[0]}). Repeated sections should differ."
                    ),
                    section_name=name,
                ))
        return issues
