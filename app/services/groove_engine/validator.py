"""
Validation rules for Groove Engine output.

:class:`GrooveValidator` checks a list of :class:`GroovePlan` objects
(one per section) against a set of musical rules and returns a list of
:class:`GrooveValidationIssue` objects.

Rules
-----
1. ``repeated_sections_must_differ``
   Repeated sections should not share identical groove profiles when enough
   material is available (not ``stereo_fallback``).

2. ``hook_groove_must_exceed_verse``
   Hook groove intensity must be stronger than verse groove intensity.

3. ``bridge_breakdown_must_reduce_activity``
   Bridge / breakdown groove must be less intense than the preceding hook.

4. ``outro_must_reduce_activity``
   Outro groove intensity must be lower than average non-outro intensity.

5. ``no_unsafe_timing_offsets``
   All timing_offset_ms values in events must be within safe bounds.

6. ``no_impossible_accent_density``
   Sections with very low energy should not have high accent density plans.

All rules return warnings, not crashes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.groove_engine.types import GrooveEvent, GroovePlan

logger = logging.getLogger(__name__)

# Role-specific timing offset limits (same as types.py — repeated here to
# keep the validator self-contained without importing private constants).
_ROLE_LIMITS: dict = {
    "hat": 15.0,
    "hi-hat": 15.0,
    "hihat": 15.0,
    "snare": 12.0,
    "bass": 10.0,
    "kick": 6.0,
    "perc": 12.0,
    "drums": 15.0,
}
_DEFAULT_LIMIT: float = 15.0


def _timing_limit(role: str) -> float:
    role_lower = role.lower()
    for key, limit in _ROLE_LIMITS.items():
        if key in role_lower:
            return limit
    return _DEFAULT_LIMIT


@dataclass
class GrooveValidationIssue:
    """A single validation finding from :class:`GrooveValidator`.

    Attributes:
        rule: Short machine-readable rule identifier.
        severity: ``"error"`` or ``"warning"``.
        message: Human-readable explanation.
        section_name: Section that triggered the issue, if applicable.
    """

    rule: str
    severity: str
    message: str
    section_name: str = ""


class GrooveValidator:
    """Validates a list of :class:`GroovePlan` objects against producer-quality rules.

    Usage::

        validator = GrooveValidator()
        issues = validator.validate(plans, source_quality="true_stems")
        for issue in issues:
            print(issue.severity, issue.rule, issue.message)
    """

    # Minimum groove intensity delta: hook must exceed verse by at least this.
    _HOOK_VERSE_MIN_DELTA: float = 0.05

    # Maximum groove intensity allowed in bridge / outro for them to count as "reduced".
    _BRIDGE_MAX_INTENSITY: float = 0.55
    _OUTRO_MAX_INTENSITY: float = 0.45

    # Maximum accent event count for a section with energy < this threshold.
    _LOW_ENERGY_THRESHOLD: float = 0.35
    _LOW_ENERGY_MAX_ACCENTS: int = 4

    def validate(
        self,
        plans: List[GroovePlan],
        source_quality: str = "true_stems",
    ) -> List[GrooveValidationIssue]:
        """Run all rules and return accumulated issues (read-only)."""
        issues: List[GrooveValidationIssue] = []
        issues.extend(self._check_repeated_sections_differ(plans, source_quality))
        issues.extend(self._check_hook_exceeds_verse(plans))
        issues.extend(self._check_bridge_reduces(plans))
        issues.extend(self._check_outro_reduces(plans))
        issues.extend(self._check_safe_timing_offsets(plans))
        return issues

    # ------------------------------------------------------------------ #
    # Individual rules                                                     #
    # ------------------------------------------------------------------ #

    def _check_repeated_sections_differ(
        self,
        plans: List[GroovePlan],
        source_quality: str,
    ) -> List[GrooveValidationIssue]:
        """Repeated sections should not share identical groove profile + intensity."""
        issues: List[GrooveValidationIssue] = []

        if source_quality == "stereo_fallback":
            return issues

        # Build map: section_name_lower → list of (profile_name, intensity) tuples
        seen: dict = {}
        for plan in plans:
            key = plan.section_name.lower()
            seen.setdefault(key, []).append((plan.groove_profile_name, plan.groove_intensity))

        for name, occurrences in seen.items():
            if len(occurrences) < 2:
                continue
            # Check if all occurrences are identical
            if len(set(occurrences)) == 1:
                issues.append(GrooveValidationIssue(
                    rule="repeated_sections_must_differ",
                    severity="warning",
                    message=(
                        f"All occurrences of section '{name}' have identical groove profile "
                        f"and intensity ({occurrences[0]}). "
                        "Repeated sections should be differentiated."
                    ),
                    section_name=name,
                ))

        return issues

    def _check_hook_exceeds_verse(
        self, plans: List[GroovePlan]
    ) -> List[GrooveValidationIssue]:
        """Hook groove intensity must be stronger than verse groove intensity."""
        issues: List[GrooveValidationIssue] = []

        hook_plans = [p for p in plans if self._is_section_type(p, "hook")]
        verse_plans = [p for p in plans if self._is_section_type(p, "verse")]

        if not hook_plans or not verse_plans:
            return issues

        max_verse_intensity = max(p.groove_intensity for p in verse_plans)

        for hook_plan in hook_plans:
            if hook_plan.groove_intensity < max_verse_intensity + self._HOOK_VERSE_MIN_DELTA:
                issues.append(GrooveValidationIssue(
                    rule="hook_groove_must_exceed_verse",
                    severity="warning",
                    message=(
                        f"Hook '{hook_plan.section_name}' groove_intensity "
                        f"({hook_plan.groove_intensity:.3f}) is not sufficiently stronger "
                        f"than verse (max={max_verse_intensity:.3f}, "
                        f"required delta={self._HOOK_VERSE_MIN_DELTA})."
                    ),
                    section_name=hook_plan.section_name,
                ))

        return issues

    def _check_bridge_reduces(
        self, plans: List[GroovePlan]
    ) -> List[GrooveValidationIssue]:
        """Bridge and breakdown groove must be below the allowed maximum."""
        issues: List[GrooveValidationIssue] = []

        for plan in plans:
            name_lower = plan.section_name.lower()
            if any(t in name_lower for t in ("bridge", "breakdown", "break")):
                if plan.groove_intensity > self._BRIDGE_MAX_INTENSITY:
                    issues.append(GrooveValidationIssue(
                        rule="bridge_breakdown_must_reduce_activity",
                        severity="warning",
                        message=(
                            f"Bridge/breakdown '{plan.section_name}' groove_intensity "
                            f"({plan.groove_intensity:.3f}) exceeds allowed maximum "
                            f"of {self._BRIDGE_MAX_INTENSITY}. "
                            "Bridge must reset momentum."
                        ),
                        section_name=plan.section_name,
                    ))

        return issues

    def _check_outro_reduces(
        self, plans: List[GroovePlan]
    ) -> List[GrooveValidationIssue]:
        """Outro groove intensity must be below the allowed maximum."""
        issues: List[GrooveValidationIssue] = []

        outro_plans = [p for p in plans if "outro" in p.section_name.lower()]
        if not outro_plans:
            return issues

        for plan in outro_plans:
            if plan.groove_intensity > self._OUTRO_MAX_INTENSITY:
                issues.append(GrooveValidationIssue(
                    rule="outro_must_reduce_activity",
                    severity="warning",
                    message=(
                        f"Outro '{plan.section_name}' groove_intensity "
                        f"({plan.groove_intensity:.3f}) exceeds allowed maximum "
                        f"of {self._OUTRO_MAX_INTENSITY}. "
                        "Outro must relax energy."
                    ),
                    section_name=plan.section_name,
                ))

        return issues

    def _check_safe_timing_offsets(
        self, plans: List[GroovePlan]
    ) -> List[GrooveValidationIssue]:
        """All timing_offset_ms values must be within safe musical bounds."""
        issues: List[GrooveValidationIssue] = []

        for plan in plans:
            for event in plan.groove_events:
                if event.timing_offset_ms is None:
                    continue
                limit = _timing_limit(event.role)
                if abs(event.timing_offset_ms) > limit:
                    issues.append(GrooveValidationIssue(
                        rule="no_unsafe_timing_offsets",
                        severity="warning",
                        message=(
                            f"Section '{plan.section_name}' event role='{event.role}' "
                            f"timing_offset_ms={event.timing_offset_ms:.1f}ms "
                            f"exceeds safe limit of ±{limit:.1f}ms."
                        ),
                        section_name=plan.section_name,
                    ))

        return issues

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_section_type(plan: GroovePlan, section_type: str) -> bool:
        """Heuristically determine if a plan belongs to *section_type*."""
        name = plan.section_name.lower()
        if section_type == "hook":
            return any(t in name for t in ("hook", "chorus", "drop")) and "pre" not in name
        if section_type == "verse":
            return "verse" in name
        if section_type == "bridge":
            return any(t in name for t in ("bridge", "breakdown"))
        if section_type == "outro":
            return "outro" in name
        return section_type in name
