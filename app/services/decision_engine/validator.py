"""
Decision Validator — validates a :class:`~app.services.decision_engine.types.DecisionPlan`
against producer hard constraints.

Rules:
- Verse 1 cannot be full unless source is too limited.
- Pre-hook must subtract when possible.
- Hook must reintroduce something if something was held back (warning if not).
- Bridge must be less full than hook.
- Outro must reduce fullness.
- Repeated sections must differ in decision pattern when enough material exists.

Emits warnings for soft violations and critical issues for clearly broken rules.
"""

from __future__ import annotations

import logging
from typing import List

from app.services.decision_engine.rules import LIMITED_SOURCE_QUALITIES, MIN_ROLES_FOR_SUBTRACTION
from app.services.decision_engine.types import (
    DecisionPlan,
    DecisionValidationIssue,
    SectionDecision,
)

logger = logging.getLogger(__name__)


def _derive_section_type(name: str) -> str:
    """Derive a canonical section type from a raw section name string."""
    n = name.lower().strip()
    for token in ("pre_hook", "pre-hook", "prehook", "buildup", "build"):
        if token in n:
            return "pre_hook"
    for token in ("hook", "chorus", "drop"):
        if token in n:
            return "hook"
    for token in ("verse",):
        if token in n:
            return "verse"
    for token in ("bridge",):
        if token in n:
            return "bridge"
    for token in ("breakdown", "break"):
        if token in n:
            return "breakdown"
    for token in ("intro",):
        if token in n:
            return "intro"
    for token in ("outro",):
        if token in n:
            return "outro"
    return "verse"


class DecisionValidator:
    """Validate a :class:`~app.services.decision_engine.types.DecisionPlan`.

    Parameters
    ----------
    source_quality:
        Source quality mode.  Used to relax constraints when material is limited.
    available_roles:
        Instrument roles present in the source material.  Used to determine
        whether non-trivial subtractions were feasible.
    """

    def __init__(
        self,
        source_quality: str = "stereo_fallback",
        available_roles: List[str] | None = None,
    ) -> None:
        self.source_quality = source_quality
        self.available_roles: List[str] = list(available_roles or [])

    def validate(self, plan: DecisionPlan) -> List[DecisionValidationIssue]:
        """Validate *plan* and return a list of :class:`DecisionValidationIssue`.

        Parameters
        ----------
        plan:
            The plan produced by :class:`~app.services.decision_engine.planner.DecisionPlanner`.

        Returns
        -------
        list[DecisionValidationIssue]
            Ordered list of issues, empty when the plan is valid.
        """
        issues: List[DecisionValidationIssue] = []
        is_limited = self.source_quality in LIMITED_SOURCE_QUALITIES
        enough_roles = len(self.available_roles) >= MIN_ROLES_FOR_SUBTRACTION

        if not plan.section_decisions:
            return issues

        # Build a per-type lookup for easy validation.
        by_type: dict[str, List[SectionDecision]] = {}
        for decision in plan.section_decisions:
            stype = _derive_section_type(decision.section_name)
            by_type.setdefault(stype, []).append(decision)

        # --- Rule: Verse 1 cannot be full unless source is too limited ---
        verse_decisions = by_type.get("verse", [])
        if verse_decisions and not is_limited:
            verse_1 = verse_decisions[0]
            if verse_1.allow_full_stack:
                issues.append(
                    DecisionValidationIssue(
                        severity="critical",
                        rule="verse_1_full_stack",
                        section_name=verse_1.section_name,
                        message=(
                            f"Verse 1 ('{verse_1.section_name}') allows full stack but "
                            "source quality is not limited.  Full stack in Verse 1 is "
                            "a hard constraint violation."
                        ),
                    )
                )
            if verse_1.target_fullness == "full" and enough_roles:
                issues.append(
                    DecisionValidationIssue(
                        severity="critical",
                        rule="verse_1_full_target",
                        section_name=verse_1.section_name,
                        message=(
                            f"Verse 1 ('{verse_1.section_name}') has target_fullness='full' "
                            "with enough roles available — violates no-full-stack constraint."
                        ),
                    )
                )

        # --- Rule: Pre-hook must subtract when possible ---
        pre_hook_decisions = by_type.get("pre_hook", [])
        if pre_hook_decisions and enough_roles and not is_limited:
            for ph in pre_hook_decisions:
                if ph.subtraction_count == 0:
                    issues.append(
                        DecisionValidationIssue(
                            severity="warning",
                            rule="pre_hook_no_subtraction",
                            section_name=ph.section_name,
                            message=(
                                f"Pre-hook '{ph.section_name}' has no required subtractions "
                                "despite enough source material being available.  Pre-hook "
                                "should create tension through subtraction."
                            ),
                        )
                    )

        # --- Rule: Hook must reintroduce something if something was held back ---
        hook_decisions = by_type.get("hook", [])
        if hook_decisions:
            # Inspect cumulative held-back roles up to each hook.
            cumulative_held: set[str] = set()
            prev_was_pre_hook = False
            prev_pre_hook_had_subtraction = False

            for decision in plan.section_decisions:
                stype = _derive_section_type(decision.section_name)
                for action in decision.required_subtractions:
                    if action.target_role and action.action_type in (
                        "hold_back_role",
                        "pre_hook_subtraction",
                        "remove_role",
                    ):
                        cumulative_held.add(action.target_role)

                if stype == "pre_hook":
                    prev_was_pre_hook = True
                    prev_pre_hook_had_subtraction = decision.subtraction_count > 0

                elif stype == "hook":
                    reintroduced = {
                        a.target_role
                        for a in decision.required_reentries
                        if a.target_role and a.action_type == "reintroduce_role"
                    }
                    if cumulative_held and not reintroduced and enough_roles:
                        issues.append(
                            DecisionValidationIssue(
                                severity="warning",
                                rule="hook_no_reintroduction",
                                section_name=decision.section_name,
                                message=(
                                    f"Hook '{decision.section_name}' has held-back roles "
                                    f"({sorted(cumulative_held)}) but no reintroductions.  "
                                    "Hook payoff should release held-back material."
                                ),
                            )
                        )
                    # Remove reintroduced roles from cumulative_held.
                    cumulative_held -= reintroduced
                    prev_was_pre_hook = False
                    prev_pre_hook_had_subtraction = False
                else:
                    prev_was_pre_hook = False
                    prev_pre_hook_had_subtraction = False

        # --- Rule: Bridge must be less full than hook ---
        bridge_decisions = by_type.get("bridge", []) + by_type.get("breakdown", [])
        if bridge_decisions and hook_decisions:
            hook_fullness_set = {d.target_fullness for d in hook_decisions}
            for bridge in bridge_decisions:
                if bridge.target_fullness == "full" and "full" in hook_fullness_set:
                    issues.append(
                        DecisionValidationIssue(
                            severity="critical",
                            rule="bridge_too_full",
                            section_name=bridge.section_name,
                            message=(
                                f"Bridge/Breakdown '{bridge.section_name}' has "
                                f"target_fullness='full' while hooks are also 'full'.  "
                                "Bridge must be meaningfully less full than hook."
                            ),
                        )
                    )
                elif bridge.target_fullness == "medium" and enough_roles:
                    issues.append(
                        DecisionValidationIssue(
                            severity="warning",
                            rule="bridge_not_sparse",
                            section_name=bridge.section_name,
                            message=(
                                f"Bridge/Breakdown '{bridge.section_name}' has "
                                f"target_fullness='medium' — consider 'sparse' for a "
                                "stronger reset contrast."
                            ),
                        )
                    )

        # --- Rule: Outro must reduce fullness ---
        outro_decisions = by_type.get("outro", [])
        if outro_decisions:
            for outro in outro_decisions:
                if outro.target_fullness == "full":
                    issues.append(
                        DecisionValidationIssue(
                            severity="critical",
                            rule="outro_unresolved",
                            section_name=outro.section_name,
                            message=(
                                f"Outro '{outro.section_name}' has target_fullness='full' "
                                "— outro must reduce fullness, not end on full stack."
                            ),
                        )
                    )
                elif outro.target_fullness == "medium" and enough_roles:
                    issues.append(
                        DecisionValidationIssue(
                            severity="warning",
                            rule="outro_not_sparse",
                            section_name=outro.section_name,
                            message=(
                                f"Outro '{outro.section_name}' has target_fullness='medium' "
                                "— consider 'sparse' for a clean resolution."
                            ),
                        )
                    )

        # --- Rule: Repeated sections must differ when enough material exists ---
        if enough_roles and not is_limited:
            for stype, type_decisions in by_type.items():
                if len(type_decisions) < 2:
                    continue
                # Compare decision fingerprints.
                fingerprints = [
                    frozenset(
                        [(a.action_type, a.target_role) for a in d.required_subtractions]
                        + [(a.action_type, a.target_role) for a in d.required_reentries]
                        + [("fullness", d.target_fullness)]
                    )
                    for d in type_decisions
                ]
                if len(set(fingerprints)) == 1:
                    issues.append(
                        DecisionValidationIssue(
                            severity="warning",
                            rule="repeated_section_identical",
                            section_name=None,
                            message=(
                                f"All {len(type_decisions)} '{stype}' sections have identical "
                                "decision patterns.  Repeated sections should differ when "
                                "enough material exists."
                            ),
                        )
                    )

        logger.debug(
            "DecisionValidator: found %d issues (%d critical)",
            len(issues),
            sum(1 for i in issues if i.is_critical),
        )

        return issues
