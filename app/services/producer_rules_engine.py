"""
Producer Rules Engine — Phase 2: Real Producer Behavior.

Applies a deterministic set of musical arrangement rules to a
ProducerArrangementPlanV2 to make it behave like a real producer rather
than a loop repeater.

Rules implemented:
    sparse_intro          — Intros must be low-density
    hook_elevation        — Hooks must have higher energy than adjacent verses
    energy_ramp           — Energy should build from intro toward first hook
    bridge_contrast       — Bridges/breakdowns must contrast with surrounding sections
    outro_simplification  — Outros wind down
    repetition_control    — No two consecutive sections with identical roles
    overcrowding_guard    — Maximum density caps per section type
    role_aware_adaptation — Graceful fallback when stems are missing
    quality_guards        — High-level quality checks flagged as warnings

The engine is purely additive: it annotates the plan's decision_log with
any violations found and returns a (possibly corrected) plan.  It does NOT
break the plan — it repairs where possible and flags the rest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from app.services.producer_plan_builder import (
    ProducerArrangementPlanV2,
    ProducerSectionPlan,
    ProducerDecisionEntry,
    SectionKind,
    EnergyLevel,
    DensityLevel,
    VariationStrategy,
    TransitionIntent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class RuleViolation:
    """A single rule violation found during plan evaluation."""

    rule_name: str
    section_index: int
    section_label: str
    description: str
    severity: str = "warning"   # "warning" | "error"
    auto_repaired: bool = False
    repair_description: str = ""


@dataclass
class RulesEngineResult:
    """Output of running the rules engine on a plan."""

    plan: ProducerArrangementPlanV2     # Potentially repaired plan
    violations: List[RuleViolation] = field(default_factory=list)
    rules_run: List[str] = field(default_factory=list)
    repair_count: int = 0

    @property
    def is_compliant(self) -> bool:
        """True when no error-severity violations remain after repair."""
        return all(v.severity != "error" or v.auto_repaired for v in self.violations)

    def to_dict(self) -> dict:
        return {
            "is_compliant": self.is_compliant,
            "rules_run": self.rules_run,
            "repair_count": self.repair_count,
            "violations": [
                {
                    "rule_name": v.rule_name,
                    "section_index": v.section_index,
                    "section_label": v.section_label,
                    "description": v.description,
                    "severity": v.severity,
                    "auto_repaired": v.auto_repaired,
                    "repair_description": v.repair_description,
                }
                for v in self.violations
            ],
        }


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------


class ProducerRulesEngine:
    """
    Validates and repairs a ProducerArrangementPlanV2 against musical rules.

    Usage::

        result = ProducerRulesEngine.apply(plan)
        plan = result.plan          # Use the (possibly repaired) plan
        if not result.is_compliant:
            for v in result.violations:
                logger.warning(v.description)
    """

    # Maximum density per section type (hard cap)
    _MAX_DENSITY: dict[SectionKind, DensityLevel] = {
        SectionKind.INTRO:     DensityLevel.MEDIUM,
        SectionKind.VERSE:     DensityLevel.MEDIUM,
        SectionKind.PRE_HOOK:  DensityLevel.FULL,
        SectionKind.HOOK:      DensityLevel.FULL,
        SectionKind.BRIDGE:    DensityLevel.MEDIUM,
        SectionKind.BREAKDOWN: DensityLevel.SPARSE,
        SectionKind.OUTRO:     DensityLevel.MEDIUM,
    }

    # Minimum energy level for hooks compared to adjacent verses
    _HOOK_ENERGY_ADVANTAGE = 1   # hooks must be at least N levels above adjacent verses

    @classmethod
    def apply(cls, plan: ProducerArrangementPlanV2) -> RulesEngineResult:
        """Run all rules over *plan* and return a (repaired) result."""
        violations: list[RuleViolation] = []
        rules_run: list[str] = []
        repair_count = 0

        rules = [
            ("sparse_intro",         cls._rule_sparse_intro),
            ("hook_elevation",       cls._rule_hook_elevation),
            ("energy_ramp",          cls._rule_energy_ramp),
            ("bridge_contrast",      cls._rule_bridge_contrast),
            ("outro_simplification", cls._rule_outro_simplification),
            ("repetition_control",   cls._rule_repetition_control),
            ("overcrowding_guard",   cls._rule_overcrowding_guard),
            ("role_aware_adaptation",cls._rule_role_aware_adaptation),
            ("quality_guards",       cls._rule_quality_guards),
        ]

        for rule_name, rule_fn in rules:
            rule_violations = rule_fn(plan)
            for v in rule_violations:
                if v.auto_repaired:
                    repair_count += 1
            violations.extend(rule_violations)
            rules_run.append(rule_name)

        # Append rule violations to plan decision_log
        for v in violations:
            plan.decision_log.append(
                ProducerDecisionEntry(
                    section_index=v.section_index,
                    section_label=v.section_label,
                    decision=v.repair_description if v.auto_repaired else f"VIOLATION: {v.description}",
                    reason=v.description,
                    flag=v.rule_name,
                )
            )

        for rn in rules_run:
            if rn not in plan.rules_applied:
                plan.rules_applied.append(rn)

        logger.info(
            "ProducerRulesEngine: %d violations found, %d auto-repaired across %d rules",
            len(violations),
            repair_count,
            len(rules_run),
        )

        return RulesEngineResult(
            plan=plan,
            violations=violations,
            rules_run=rules_run,
            repair_count=repair_count,
        )

    # ------------------------------------------------------------------
    # Individual rules
    # ------------------------------------------------------------------

    @classmethod
    def _rule_sparse_intro(cls, plan: ProducerArrangementPlanV2) -> list[RuleViolation]:
        """Intro must not be full density."""
        violations: list[RuleViolation] = []
        for s in plan.sections:
            if s.section_type != SectionKind.INTRO:
                continue
            if s.density == DensityLevel.FULL:
                s.density = DensityLevel.SPARSE
                # Trim active roles to sparse max
                s.active_roles = s.active_roles[:2]
                s.muted_roles = [r for r in plan.available_roles if r not in s.active_roles]
                violations.append(RuleViolation(
                    rule_name="sparse_intro",
                    section_index=s.index,
                    section_label=s.label,
                    description="Intro was full-density — too busy for an opening section",
                    severity="error",
                    auto_repaired=True,
                    repair_description="Intro density forced to sparse; active roles trimmed to 2",
                ))
        return violations

    @classmethod
    def _rule_hook_elevation(cls, plan: ProducerArrangementPlanV2) -> list[RuleViolation]:
        """Every hook must have strictly higher energy than every verse."""
        violations: list[RuleViolation] = []
        hooks = [s for s in plan.sections if s.section_type == SectionKind.HOOK]
        verses = [s for s in plan.sections if s.section_type == SectionKind.VERSE]

        if not hooks or not verses:
            return violations

        max_verse_energy = max(s.target_energy.value for s in verses)

        for hook in hooks:
            if hook.target_energy.value <= max_verse_energy:
                # Boost hook energy
                new_energy_val = min(EnergyLevel.VERY_HIGH.value, max_verse_energy + cls._HOOK_ENERGY_ADVANTAGE)
                hook.target_energy = EnergyLevel(new_energy_val)
                violations.append(RuleViolation(
                    rule_name="hook_elevation",
                    section_index=hook.index,
                    section_label=hook.label,
                    description=(
                        f"Hook energy ({hook.target_energy.value}) not elevated above "
                        f"verse energy ({max_verse_energy})"
                    ),
                    severity="error",
                    auto_repaired=True,
                    repair_description=f"Hook energy boosted to {new_energy_val}",
                ))

        return violations

    @classmethod
    def _rule_energy_ramp(cls, plan: ProducerArrangementPlanV2) -> list[RuleViolation]:
        """
        Energy should generally increase from intro toward the first hook.
        Flag (but do not auto-repair) if it drops between consecutive build sections.
        """
        violations: list[RuleViolation] = []
        build_types = {SectionKind.INTRO, SectionKind.VERSE, SectionKind.PRE_HOOK, SectionKind.HOOK}

        first_hook_idx = next(
            (i for i, s in enumerate(plan.sections) if s.section_type == SectionKind.HOOK),
            len(plan.sections),
        )
        build_sections = [s for s in plan.sections[:first_hook_idx] if s.section_type in build_types]

        for i in range(1, len(build_sections)):
            prev = build_sections[i - 1]
            curr = build_sections[i]
            if curr.target_energy.value < prev.target_energy.value:
                violations.append(RuleViolation(
                    rule_name="energy_ramp",
                    section_index=curr.index,
                    section_label=curr.label,
                    description=(
                        f"Energy drops from {prev.label} (energy={prev.target_energy.value}) "
                        f"to {curr.label} (energy={curr.target_energy.value}) before first hook"
                    ),
                    severity="warning",
                    auto_repaired=False,
                    repair_description="",
                ))

        return violations

    @classmethod
    def _rule_bridge_contrast(cls, plan: ProducerArrangementPlanV2) -> list[RuleViolation]:
        """Bridges and breakdowns must have lower energy than adjacent hooks."""
        violations: list[RuleViolation] = []
        contrast_types = {SectionKind.BRIDGE, SectionKind.BREAKDOWN}

        sections = plan.sections
        for i, s in enumerate(sections):
            if s.section_type not in contrast_types:
                continue

            # Compare with nearest hook (either side)
            adjacent = []
            if i > 0:
                adjacent.append(sections[i - 1])
            if i < len(sections) - 1:
                adjacent.append(sections[i + 1])

            hook_neighbours = [a for a in adjacent if a.section_type == SectionKind.HOOK]
            for hook in hook_neighbours:
                if s.target_energy.value >= hook.target_energy.value:
                    # Force bridge energy below hook
                    s.target_energy = EnergyLevel(max(EnergyLevel.VERY_LOW.value, hook.target_energy.value - 2))
                    s.density = DensityLevel.SPARSE
                    violations.append(RuleViolation(
                        rule_name="bridge_contrast",
                        section_index=s.index,
                        section_label=s.label,
                        description=(
                            f"{s.label} energy not lower than adjacent {hook.label}"
                        ),
                        severity="error",
                        auto_repaired=True,
                        repair_description=(
                            f"{s.label} energy reduced to {s.target_energy.value}, density set to sparse"
                        ),
                    ))

        return violations

    @classmethod
    def _rule_outro_simplification(cls, plan: ProducerArrangementPlanV2) -> list[RuleViolation]:
        """Outro must be sparse and low energy."""
        violations: list[RuleViolation] = []
        for s in plan.sections:
            if s.section_type != SectionKind.OUTRO:
                continue
            repaired = False
            if s.density not in (DensityLevel.SPARSE, DensityLevel.MEDIUM):
                s.density = DensityLevel.SPARSE
                repaired = True
            if s.target_energy.value > EnergyLevel.LOW.value:
                s.target_energy = EnergyLevel.LOW
                repaired = True
            if repaired:
                violations.append(RuleViolation(
                    rule_name="outro_simplification",
                    section_index=s.index,
                    section_label=s.label,
                    description="Outro was too energetic/dense for a closing section",
                    severity="error",
                    auto_repaired=True,
                    repair_description="Outro energy set to LOW, density to SPARSE",
                ))
        return violations

    @classmethod
    def _rule_repetition_control(cls, plan: ProducerArrangementPlanV2) -> list[RuleViolation]:
        """
        Consecutive sections should not have identical active role sets.
        When they do, upgrade the variation strategy to LAYER_ADD or RHYTHM_VARIATION.
        """
        violations: list[RuleViolation] = []
        sections = plan.sections

        for i in range(1, len(sections)):
            prev = sections[i - 1]
            curr = sections[i]

            if (
                curr.section_type == prev.section_type
                and sorted(curr.active_roles) == sorted(prev.active_roles)
                and curr.variation_strategy == VariationStrategy.REPEAT
            ):
                curr.variation_strategy = VariationStrategy.RHYTHM_VARIATION
                violations.append(RuleViolation(
                    rule_name="repetition_control",
                    section_index=curr.index,
                    section_label=curr.label,
                    description=(
                        f"{curr.label} has identical roles to {prev.label} "
                        "and variation_strategy=REPEAT — sounds like copy-paste"
                    ),
                    severity="warning",
                    auto_repaired=True,
                    repair_description=f"variation_strategy upgraded to {VariationStrategy.RHYTHM_VARIATION.value}",
                ))

        return violations

    @classmethod
    def _rule_overcrowding_guard(cls, plan: ProducerArrangementPlanV2) -> list[RuleViolation]:
        """Density must not exceed the allowed cap for each section type."""
        violations: list[RuleViolation] = []
        density_order = [DensityLevel.SPARSE, DensityLevel.MEDIUM, DensityLevel.FULL]

        for s in plan.sections:
            max_density = cls._MAX_DENSITY.get(s.section_type, DensityLevel.FULL)
            if density_order.index(s.density) > density_order.index(max_density):
                s.density = max_density
                violations.append(RuleViolation(
                    rule_name="overcrowding_guard",
                    section_index=s.index,
                    section_label=s.label,
                    description=(
                        f"{s.label} density exceeds allowed maximum ({max_density.value}) "
                        f"for section type {s.section_type.value}"
                    ),
                    severity="error",
                    auto_repaired=True,
                    repair_description=f"Density capped at {max_density.value}",
                ))

        return violations

    @classmethod
    def _rule_role_aware_adaptation(cls, plan: ProducerArrangementPlanV2) -> list[RuleViolation]:
        """
        When no stems are available, flag any section that relies on empty active_roles
        and add a rationale note recommending full_mix or stem upload.
        """
        violations: list[RuleViolation] = []
        if plan.available_roles:
            return violations  # Stems exist — nothing to do

        for s in plan.sections:
            if not s.active_roles:
                violations.append(RuleViolation(
                    rule_name="role_aware_adaptation",
                    section_index=s.index,
                    section_label=s.label,
                    description=(
                        f"{s.label} has no active roles and no stems available — "
                        "section will render silence or require full_mix fallback"
                    ),
                    severity="warning",
                    auto_repaired=False,
                    repair_description="",
                ))

        return violations

    @classmethod
    def _rule_quality_guards(cls, plan: ProducerArrangementPlanV2) -> list[RuleViolation]:
        """
        High-level quality checks that flag potential production issues.
        These are warnings only (not auto-repaired).
        """
        violations: list[RuleViolation] = []
        sections = plan.sections

        if not sections:
            return violations

        hooks = [s for s in sections if s.section_type == SectionKind.HOOK]
        verses = [s for s in sections if s.section_type == SectionKind.VERSE]

        # Guard: full_mix over-reliance when isolated stems exist
        if len(plan.available_roles) > 1:
            full_mix_sections = [s for s in sections if s.active_roles == ["full_mix"]]
            if len(full_mix_sections) > len(sections) // 2:
                violations.append(RuleViolation(
                    rule_name="quality_guards",
                    section_index=-1,
                    section_label="global",
                    description=(
                        f"{len(full_mix_sections)}/{len(sections)} sections use only full_mix "
                        "despite isolated stems being available — consider using individual roles"
                    ),
                    severity="warning",
                    auto_repaired=False,
                    repair_description="",
                ))

        # Guard: no hooks in arrangement
        if not hooks:
            violations.append(RuleViolation(
                rule_name="quality_guards",
                section_index=-1,
                section_label="global",
                description="Arrangement has no hook sections — lacks a payoff moment",
                severity="warning",
                auto_repaired=False,
                repair_description="",
            ))

        # Guard: too many consecutive same-type sections
        for i in range(2, len(sections)):
            if (
                sections[i].section_type == sections[i - 1].section_type == sections[i - 2].section_type
                and sections[i].section_type not in (SectionKind.HOOK,)
            ):
                violations.append(RuleViolation(
                    rule_name="quality_guards",
                    section_index=sections[i].index,
                    section_label=sections[i].label,
                    description=(
                        f"Three consecutive {sections[i].section_type.value} sections detected — "
                        "consider adding contrast"
                    ),
                    severity="warning",
                    auto_repaired=False,
                    repair_description="",
                ))

        return violations
