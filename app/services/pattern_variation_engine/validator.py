"""
Validation rules for :class:`PatternVariationPlan`.

Rules enforced
--------------
1. verse_2_must_differ_from_verse_1
   Verse 2 cannot have the same pattern combination as Verse 1 when sufficient
   source quality allows differentiation (i.e. not stereo_fallback).

2. hook_2_must_differ_from_hook_1
   Hook 2 cannot be identical to Hook 1 when source quality allows.

3. pre_hook_must_create_tension
   Pre-hook sections must contain at least one tension-creating action
   (HAT_DENSITY_DOWN, BASS_DROPOUT, MELODY_DROPOUT, or PRE_DROP_SILENCE).

4. bridge_breakdown_must_reduce_groove
   Bridge / breakdown sections must contain DROP_KICK or HALF_TIME_SWITCH
   or BASS_DROPOUT — they cannot leave the full groove running.

5. outro_must_reduce_activity
   Outro sections must contain at least one reduction action
   (DROP_KICK, HAT_DENSITY_DOWN, BASS_DROPOUT, or MELODY_DROPOUT).

Repair strategies
-----------------
Each rule carries a ``repair()`` call that attempts to auto-fix a failing
:class:`PatternSectionPlan` by injecting the minimum required event(s).
Repair is best-effort and always appended at the end of the event list so
it does not reorder existing events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Set

from app.services.pattern_variation_engine.types import (
    PatternAction,
    PatternEvent,
    PatternSectionPlan,
    PatternVariationPlan,
)

logger = logging.getLogger(__name__)

# Actions that count as "tension" in a pre-hook
_TENSION_ACTIONS: Set[PatternAction] = {
    PatternAction.HAT_DENSITY_DOWN,
    PatternAction.BASS_DROPOUT,
    PatternAction.MELODY_DROPOUT,
    PatternAction.PRE_DROP_SILENCE,
}

# Actions that count as "reduced groove" in bridge / breakdown
_REDUCE_GROOVE_ACTIONS: Set[PatternAction] = {
    PatternAction.DROP_KICK,
    PatternAction.HALF_TIME_SWITCH,
    PatternAction.BASS_DROPOUT,
}

# Actions that count as "reduced activity" in outro
_REDUCE_ACTIVITY_ACTIONS: Set[PatternAction] = {
    PatternAction.DROP_KICK,
    PatternAction.HAT_DENSITY_DOWN,
    PatternAction.BASS_DROPOUT,
    PatternAction.MELODY_DROPOUT,
}

# Source quality tiers
_WEAK_SOURCES = {"stereo_fallback"}


# ---------------------------------------------------------------------------
# Validation issue
# ---------------------------------------------------------------------------

@dataclass
class PatternValidationIssue:
    """A single validation finding.

    Attributes:
        rule: Short machine-readable rule identifier.
        severity: ``"error"`` or ``"warning"``.
        message: Human-readable explanation.
        section_name: Section that triggered the issue, if applicable.
        repaired: Whether the engine successfully auto-repaired the issue.
    """

    rule: str
    severity: str
    message: str
    section_name: str = ""
    repaired: bool = False


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class PatternVariationValidator:
    """Validates a :class:`PatternVariationPlan` against producer-quality rules.

    Usage::

        validator = PatternVariationValidator()
        issues = validator.validate(plan)
        issues = validator.validate_and_repair(plan)  # mutates plan in-place
    """

    def validate(self, plan: PatternVariationPlan) -> List[PatternValidationIssue]:
        """Run all rules and return accumulated issues (read-only)."""
        issues: List[PatternValidationIssue] = []
        issues.extend(self._check_verse_2_differs(plan))
        issues.extend(self._check_hook_2_differs(plan))
        issues.extend(self._check_pre_hook_tension(plan))
        issues.extend(self._check_bridge_breakdown_reduce(plan))
        issues.extend(self._check_outro_reduces(plan))
        return issues

    def validate_and_repair(
        self, plan: PatternVariationPlan
    ) -> List[PatternValidationIssue]:
        """Run all rules and attempt to auto-repair failures.

        Mutates *plan* in place when repair is possible.  Each repaired issue
        has ``repaired=True`` set.

        Returns
        -------
        list[PatternValidationIssue]
            All issues found, including those that were repaired.
        """
        issues = self.validate(plan)
        for issue in issues:
            if not issue.repaired:
                self._attempt_repair(plan, issue)
        plan.validation_issues = [
            f"[{i.severity.upper()}] {i.rule}: {i.message}" for i in issues
        ]
        return issues

    # ------------------------------------------------------------------ #
    # Individual rules                                                     #
    # ------------------------------------------------------------------ #

    def _check_verse_2_differs(
        self, plan: PatternVariationPlan
    ) -> List[PatternValidationIssue]:
        issues: List[PatternValidationIssue] = []
        if plan.source_quality in _WEAK_SOURCES:
            return issues

        verses = plan.section_by_type("verse")
        if len(verses) < 2:
            return issues

        v1_actions = frozenset(e.pattern_action for e in verses[0].events)
        v2_actions = frozenset(e.pattern_action for e in verses[1].events)

        if v1_actions == v2_actions:
            issues.append(PatternValidationIssue(
                rule="verse_2_must_differ_from_verse_1",
                severity="error",
                message=(
                    "Verse 2 has the same pattern combination as Verse 1. "
                    "When enough material exists, Verse 2 must be differentiated."
                ),
                section_name=verses[1].section_name,
            ))
        return issues

    def _check_hook_2_differs(
        self, plan: PatternVariationPlan
    ) -> List[PatternValidationIssue]:
        issues: List[PatternValidationIssue] = []
        if plan.source_quality in _WEAK_SOURCES:
            return issues

        hooks = plan.section_by_type("hook")
        if len(hooks) < 2:
            return issues

        h1_actions = frozenset(e.pattern_action for e in hooks[0].events)
        h2_actions = frozenset(e.pattern_action for e in hooks[1].events)

        if h1_actions == h2_actions:
            issues.append(PatternValidationIssue(
                rule="hook_2_must_differ_from_hook_1",
                severity="error",
                message=(
                    "Hook 2 has the same pattern combination as Hook 1. "
                    "Hook 2 must escalate beyond Hook 1."
                ),
                section_name=hooks[1].section_name,
            ))
        return issues

    def _check_pre_hook_tension(
        self, plan: PatternVariationPlan
    ) -> List[PatternValidationIssue]:
        issues: List[PatternValidationIssue] = []
        for section in plan.section_by_type("pre_hook"):
            actions = {e.pattern_action for e in section.events}
            if not actions.intersection(_TENSION_ACTIONS):
                issues.append(PatternValidationIssue(
                    rule="pre_hook_must_create_tension",
                    severity="error",
                    message=(
                        f"Pre-hook '{section.section_name}' has no tension-creating "
                        f"action. Must include at least one of: "
                        f"{[a.value for a in _TENSION_ACTIONS]}."
                    ),
                    section_name=section.section_name,
                ))
        return issues

    def _check_bridge_breakdown_reduce(
        self, plan: PatternVariationPlan
    ) -> List[PatternValidationIssue]:
        issues: List[PatternValidationIssue] = []
        for stype in ("bridge", "breakdown"):
            for section in plan.section_by_type(stype):
                actions = {e.pattern_action for e in section.events}
                if not actions.intersection(_REDUCE_GROOVE_ACTIONS):
                    issues.append(PatternValidationIssue(
                        rule="bridge_breakdown_must_reduce_groove",
                        severity="error",
                        message=(
                            f"Section '{section.section_name}' ({stype}) does not reduce "
                            f"groove. Must include at least one of: "
                            f"{[a.value for a in _REDUCE_GROOVE_ACTIONS]}."
                        ),
                        section_name=section.section_name,
                    ))
        return issues

    def _check_outro_reduces(
        self, plan: PatternVariationPlan
    ) -> List[PatternValidationIssue]:
        issues: List[PatternValidationIssue] = []
        for section in plan.section_by_type("outro"):
            actions = {e.pattern_action for e in section.events}
            if not actions.intersection(_REDUCE_ACTIVITY_ACTIONS):
                issues.append(PatternValidationIssue(
                    rule="outro_must_reduce_activity",
                    severity="error",
                    message=(
                        f"Outro '{section.section_name}' has no reduction action. "
                        f"Must include at least one of: "
                        f"{[a.value for a in _REDUCE_ACTIVITY_ACTIONS]}."
                    ),
                    section_name=section.section_name,
                ))
        return issues

    # ------------------------------------------------------------------ #
    # Repair strategies                                                    #
    # ------------------------------------------------------------------ #

    def _attempt_repair(
        self, plan: PatternVariationPlan, issue: PatternValidationIssue
    ) -> None:
        """Try to auto-repair *issue* by mutating *plan*."""
        rule = issue.rule
        target_section = self._find_section(plan, issue.section_name)

        if target_section is None:
            return

        if rule == "verse_2_must_differ_from_verse_1":
            self._repair_inject(
                target_section,
                PatternAction.ADD_SYNCOPATED_KICK,
                "drums",
                0.6,
                "auto-repair: injected syncopated kick to differentiate verse 2",
            )
            issue.repaired = True
            logger.info("Repaired: %s on '%s'", rule, issue.section_name)

        elif rule == "hook_2_must_differ_from_hook_1":
            self._repair_inject(
                target_section,
                PatternAction.COUNTER_MELODY_ADD,
                "melody",
                0.7,
                "auto-repair: counter-melody added to escalate hook 2",
            )
            issue.repaired = True
            logger.info("Repaired: %s on '%s'", rule, issue.section_name)

        elif rule == "pre_hook_must_create_tension":
            self._repair_inject(
                target_section,
                PatternAction.PRE_DROP_SILENCE,
                "drums",
                0.75,
                "auto-repair: pre-drop silence injected for tension",
            )
            issue.repaired = True
            logger.info("Repaired: %s on '%s'", rule, issue.section_name)

        elif rule == "bridge_breakdown_must_reduce_groove":
            self._repair_inject(
                target_section,
                PatternAction.DROP_KICK,
                "drums",
                0.65,
                "auto-repair: kick drop injected for groove reduction",
            )
            issue.repaired = True
            logger.info("Repaired: %s on '%s'", rule, issue.section_name)

        elif rule == "outro_must_reduce_activity":
            self._repair_inject(
                target_section,
                PatternAction.HAT_DENSITY_DOWN,
                "drums",
                0.5,
                "auto-repair: hat density down injected for outro reduction",
            )
            issue.repaired = True
            logger.info("Repaired: %s on '%s'", rule, issue.section_name)

    @staticmethod
    def _repair_inject(
        section: PatternSectionPlan,
        action: PatternAction,
        role: str,
        intensity: float,
        notes: str,
    ) -> None:
        """Append a repair event to *section* if the action is not already present."""
        if not section.has_action(action):
            section.events.append(PatternEvent(
                bar_start=1,
                bar_end=section.bars,
                role=role,
                pattern_action=action,
                intensity=intensity,
                notes=notes,
            ))

    @staticmethod
    def _find_section(
        plan: PatternVariationPlan, section_name: str
    ) -> Optional[PatternSectionPlan]:
        for s in plan.sections:
            if s.section_name == section_name:
                return s
        return None
