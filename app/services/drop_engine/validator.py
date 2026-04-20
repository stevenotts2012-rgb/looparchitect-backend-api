"""
Drop Engine Validator.

Validates a :class:`~app.services.drop_engine.types.DropPlan` for musical
coherence and returns a list of :class:`DropValidationIssue` objects.

The validator NEVER raises — it only accumulates warnings (and in rare cases
errors) so that callers can inspect issues without crashing the pipeline.

Rules enforced:
1. No more than one strong primary drop event per boundary unless justified.
2. Repeated hooks cannot all use identical drop behaviour.
3. Pre-hook → hook must have real payoff when source allows.
4. No silence events that would sound like glitches.
5. Outro must resolve instead of hard-cutting.
6. Bridge return must differ from hook entry when possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.services.drop_engine.types import (
    DropBoundaryPlan,
    DropPlan,
    STRONG_EVENT_TYPES,
)


# ---------------------------------------------------------------------------
# DropValidationIssue
# ---------------------------------------------------------------------------


@dataclass
class DropValidationIssue:
    """A single validation finding from :class:`DropValidator`.

    Attributes:
        severity: ``"warning"`` for issues that are likely audible but not
            fatal; ``"error"`` for structurally broken plans.
        rule: Short machine-readable rule name.
        message: Human-readable description.
        boundary_name: The affected boundary label, or ``None`` for plan-level
            issues.
    """

    severity: str  # "warning" | "error"
    rule: str
    message: str
    boundary_name: str | None = None

    def to_dict(self) -> dict:
        d = {
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
        }
        if self.boundary_name is not None:
            d["boundary_name"] = self.boundary_name
        return d


# ---------------------------------------------------------------------------
# DropValidator
# ---------------------------------------------------------------------------


class DropValidator:
    """Validate a :class:`DropPlan` and return a list of issues.

    Usage::

        validator = DropValidator()
        issues = validator.validate(drop_plan)
        warnings = [i for i in issues if i.severity == "warning"]
        errors = [i for i in issues if i.severity == "error"]
    """

    # Payoff threshold below which a pre-hook → hook boundary is flagged.
    _MIN_HOOK_PAYOFF = 0.50

    # Minimum repeated-hook variation score before raising a warning.
    _MIN_HOOK_VARIATION_SCORE = 0.40

    # Maximum number of silence-based events before warning about overuse.
    _MAX_SILENCE_EVENTS = 2

    # Minimum outro payoff score to avoid "hard-cut" warning.
    _MIN_OUTRO_PAYOFF = 0.20

    def validate(self, plan: DropPlan) -> List[DropValidationIssue]:
        """Run all validation rules against *plan* and return all issues."""
        issues: List[DropValidationIssue] = []

        self._check_empty_plan(plan, issues)
        self._check_strong_event_stacking(plan, issues)
        self._check_repeated_hook_variation(plan, issues)
        self._check_hook_payoff(plan, issues)
        self._check_silence_overuse(plan, issues)
        self._check_outro_resolution(plan, issues)
        self._check_bridge_differs_from_hook(plan, issues)

        return issues

    # ------------------------------------------------------------------
    # Individual rule checks
    # ------------------------------------------------------------------

    def _check_empty_plan(
        self, plan: DropPlan, issues: List[DropValidationIssue]
    ) -> None:
        if not plan.boundaries:
            issues.append(
                DropValidationIssue(
                    severity="warning",
                    rule="empty_plan",
                    message="DropPlan has no boundaries — no drop design was applied.",
                )
            )

    def _check_strong_event_stacking(
        self, plan: DropPlan, issues: List[DropValidationIssue]
    ) -> None:
        for boundary in plan.boundaries:
            strong_count = sum(
                1 for e in boundary.all_events if e.is_strong
            )
            # Primary is strong: allow at most 1 strong event total.
            if (
                boundary.primary_drop_event is not None
                and boundary.primary_drop_event.is_strong
                and strong_count > 1
            ):
                issues.append(
                    DropValidationIssue(
                        severity="warning",
                        rule="strong_event_stacking",
                        message=(
                            f"Boundary '{boundary.boundary_name}' has {strong_count} strong "
                            f"events — only 1 strong primary is recommended."
                        ),
                        boundary_name=boundary.boundary_name,
                    )
                )

    def _check_repeated_hook_variation(
        self, plan: DropPlan, issues: List[DropValidationIssue]
    ) -> None:
        hook_boundaries = [
            b for b in plan.boundaries
            if b.from_section == "pre_hook" and b.to_section == "hook"
        ]
        if len(hook_boundaries) < 2:
            return

        event_types = [
            b.primary_drop_event.event_type
            for b in hook_boundaries
            if b.primary_drop_event is not None
        ]
        if len(set(event_types)) == 1 and len(event_types) >= 2:
            issues.append(
                DropValidationIssue(
                    severity="warning",
                    rule="repeated_hook_identical_drop",
                    message=(
                        f"All {len(event_types)} hook entries use the same primary drop "
                        f"event type '{event_types[0]}' — listeners will notice the repetition."
                    ),
                )
            )

        if (
            plan.repeated_hook_drop_variation_score < self._MIN_HOOK_VARIATION_SCORE
        ):
            issues.append(
                DropValidationIssue(
                    severity="warning",
                    rule="low_hook_variation_score",
                    message=(
                        f"repeated_hook_drop_variation_score "
                        f"({plan.repeated_hook_drop_variation_score:.2f}) is below "
                        f"minimum threshold ({self._MIN_HOOK_VARIATION_SCORE:.2f})."
                    ),
                )
            )

    def _check_hook_payoff(
        self, plan: DropPlan, issues: List[DropValidationIssue]
    ) -> None:
        for boundary in plan.boundaries:
            if boundary.from_section == "pre_hook" and boundary.to_section == "hook":
                if boundary.payoff_score < self._MIN_HOOK_PAYOFF:
                    issues.append(
                        DropValidationIssue(
                            severity="warning",
                            rule="weak_hook_payoff",
                            message=(
                                f"Boundary '{boundary.boundary_name}' has payoff_score "
                                f"{boundary.payoff_score:.2f} — hook entry feels weak."
                            ),
                            boundary_name=boundary.boundary_name,
                        )
                    )
                if boundary.primary_drop_event is None:
                    issues.append(
                        DropValidationIssue(
                            severity="warning",
                            rule="no_primary_event_hook",
                            message=(
                                f"Boundary '{boundary.boundary_name}' (pre_hook → hook) "
                                f"has no primary drop event — hook entry is generic."
                            ),
                            boundary_name=boundary.boundary_name,
                        )
                    )

    def _check_silence_overuse(
        self, plan: DropPlan, issues: List[DropValidationIssue]
    ) -> None:
        silence_types = {"pre_drop_silence", "silence_tease"}
        silence_events = [
            e
            for b in plan.boundaries
            for e in b.all_events
            if e.event_type in silence_types
        ]
        if len(silence_events) > self._MAX_SILENCE_EVENTS:
            issues.append(
                DropValidationIssue(
                    severity="warning",
                    rule="silence_overuse",
                    message=(
                        f"Plan contains {len(silence_events)} silence-based events — "
                        f"exceeds maximum of {self._MAX_SILENCE_EVENTS}; may sound broken."
                    ),
                )
            )

    def _check_outro_resolution(
        self, plan: DropPlan, issues: List[DropValidationIssue]
    ) -> None:
        outro_boundaries = [
            b for b in plan.boundaries if b.to_section == "outro"
        ]
        for boundary in outro_boundaries:
            if boundary.payoff_score < self._MIN_OUTRO_PAYOFF:
                issues.append(
                    DropValidationIssue(
                        severity="warning",
                        rule="hard_cut_outro",
                        message=(
                            f"Boundary '{boundary.boundary_name}' leads into outro with "
                            f"payoff_score {boundary.payoff_score:.2f} — outro may feel "
                            f"like a hard cut."
                        ),
                        boundary_name=boundary.boundary_name,
                    )
                )
            # Strong events at outro are unusual and potentially jarring.
            if boundary.primary_drop_event is not None and boundary.primary_drop_event.is_strong:
                issues.append(
                    DropValidationIssue(
                        severity="warning",
                        rule="strong_event_in_outro",
                        message=(
                            f"Boundary '{boundary.boundary_name}' uses strong drop event "
                            f"'{boundary.primary_drop_event.event_type}' entering outro — "
                            f"should resolve gently."
                        ),
                        boundary_name=boundary.boundary_name,
                    )
                )

    def _check_bridge_differs_from_hook(
        self, plan: DropPlan, issues: List[DropValidationIssue]
    ) -> None:
        bridge_hook_types = set()
        for boundary in plan.boundaries:
            if (
                boundary.from_section in ("bridge", "breakdown")
                and boundary.to_section == "hook"
                and boundary.primary_drop_event is not None
            ):
                bridge_hook_types.add(boundary.primary_drop_event.event_type)

        pre_hook_types = set()
        for boundary in plan.boundaries:
            if (
                boundary.from_section == "pre_hook"
                and boundary.to_section == "hook"
                and boundary.primary_drop_event is not None
            ):
                pre_hook_types.add(boundary.primary_drop_event.event_type)

        overlap = bridge_hook_types & pre_hook_types
        if overlap and bridge_hook_types and pre_hook_types:
            issues.append(
                DropValidationIssue(
                    severity="warning",
                    rule="bridge_hook_same_as_pre_hook",
                    message=(
                        f"Bridge/breakdown → hook entry shares event type(s) "
                        f"{sorted(overlap)} with pre-hook → hook entry — "
                        f"consider differentiating for better contrast."
                    ),
                )
            )
