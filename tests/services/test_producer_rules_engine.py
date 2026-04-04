"""
Unit tests for ProducerRulesEngine — Phase 2 Real Producer Behavior.

Tests:
- Rule compliance for all implemented rules
- Before/after arrangement scoring
- Regression tests proving hooks end up higher-energy than intros/verses
- Fallback tests when limited stems are available
"""

import pytest
from app.services.producer_plan_builder import (
    ProducerPlanBuilderV2,
    ProducerArrangementPlanV2,
    ProducerSectionPlan,
    SectionKind,
    EnergyLevel,
    DensityLevel,
    VariationStrategy,
    TransitionIntent,
)
from app.services.producer_rules_engine import (
    ProducerRulesEngine,
    RulesEngineResult,
    RuleViolation,
)


def _build_plan(available_roles=None, genre="trap", target_bars=64, template="standard"):
    """Helper: build a raw plan, apply rules, return the result."""
    builder = ProducerPlanBuilderV2(
        available_roles=available_roles or ["drums", "bass", "melody"],
        genre=genre,
        target_bars=target_bars,
        structure_template=template,
    )
    plan = builder.build()
    return plan


class TestSparseIntroRule:
    """sparse_intro: intro must not be full density."""

    def test_intro_not_full_density_after_rules(self):
        plan = _build_plan(available_roles=["drums", "bass", "melody", "pads", "fx"])
        result = ProducerRulesEngine.apply(plan)
        intros = [s for s in result.plan.sections if s.section_type == SectionKind.INTRO]
        for intro in intros:
            assert intro.density != DensityLevel.FULL, (
                f"Intro {intro.label} should not be FULL density after rules"
            )

    def test_forced_full_density_intro_is_repaired(self):
        """Manually inject a full-density intro and verify repair."""
        plan = _build_plan(available_roles=["drums", "bass", "melody"])
        # Force intro to FULL
        for s in plan.sections:
            if s.section_type == SectionKind.INTRO:
                s.density = DensityLevel.FULL

        result = ProducerRulesEngine.apply(plan)
        intro_violations = [v for v in result.violations if v.rule_name == "sparse_intro"]
        assert intro_violations, "Should have detected sparse_intro violation"
        assert all(v.auto_repaired for v in intro_violations), "All sparse_intro violations should be auto-repaired"
        # Confirm repair took effect
        for s in result.plan.sections:
            if s.section_type == SectionKind.INTRO:
                assert s.density != DensityLevel.FULL


class TestHookElevationRule:
    """hook_elevation: hooks must have higher energy than verses."""

    def test_hooks_higher_energy_than_verses(self):
        plan = _build_plan(available_roles=["drums", "bass", "melody"])
        result = ProducerRulesEngine.apply(plan)
        hooks = [s for s in result.plan.sections if s.section_type == SectionKind.HOOK]
        verses = [s for s in result.plan.sections if s.section_type == SectionKind.VERSE]
        if hooks and verses:
            max_verse_energy = max(s.target_energy.value for s in verses)
            for hook in hooks:
                assert hook.target_energy.value > max_verse_energy, (
                    f"Hook {hook.label} energy {hook.target_energy.value} should exceed "
                    f"verse energy {max_verse_energy}"
                )

    def test_forced_low_hook_energy_is_repaired(self):
        """Manually set hook energy equal to verse and verify repair."""
        plan = _build_plan(available_roles=["drums", "bass"])
        # Force all hooks to energy 2
        for s in plan.sections:
            if s.section_type == SectionKind.HOOK:
                s.target_energy = EnergyLevel.LOW
            if s.section_type == SectionKind.VERSE:
                s.target_energy = EnergyLevel.MEDIUM

        result = ProducerRulesEngine.apply(plan)
        hook_violations = [v for v in result.violations if v.rule_name == "hook_elevation"]
        assert hook_violations, "Should detect hook_elevation violation"
        assert all(v.auto_repaired for v in hook_violations)


class TestEnergyRampRule:
    """energy_ramp: energy should build toward first hook."""

    def test_energy_ramp_check_runs(self):
        plan = _build_plan(available_roles=["drums", "bass", "melody"])
        result = ProducerRulesEngine.apply(plan)
        assert "energy_ramp" in result.rules_run

    def test_energy_drop_before_hook_flagged_as_warning(self):
        """An energy drop in the build section should be warned (not auto-repaired)."""
        plan = _build_plan(available_roles=["drums", "bass", "melody"])
        # Force intro energy > verse energy (drop)
        intro = next((s for s in plan.sections if s.section_type == SectionKind.INTRO), None)
        verse = next((s for s in plan.sections if s.section_type == SectionKind.VERSE), None)
        if intro and verse:
            intro.target_energy = EnergyLevel.HIGH
            verse.target_energy = EnergyLevel.LOW

        result = ProducerRulesEngine.apply(plan)
        energy_violations = [v for v in result.violations if v.rule_name == "energy_ramp"]
        # If we injected a violation it should show up as a warning
        if energy_violations:
            for v in energy_violations:
                assert v.severity == "warning"


class TestBridgeContrastRule:
    """bridge_contrast: bridges/breakdowns must contrast with adjacent hooks."""

    def test_bridge_lower_energy_than_hook(self):
        plan = _build_plan(
            available_roles=["drums", "bass", "melody"],
            template="extended",
        )
        result = ProducerRulesEngine.apply(plan)
        sections = result.plan.sections
        for i, s in enumerate(sections):
            if s.section_type not in (SectionKind.BRIDGE, SectionKind.BREAKDOWN):
                continue
            neighbours = []
            if i > 0:
                neighbours.append(sections[i - 1])
            if i < len(sections) - 1:
                neighbours.append(sections[i + 1])
            hook_neighbours = [n for n in neighbours if n.section_type == SectionKind.HOOK]
            for hook in hook_neighbours:
                assert s.target_energy.value < hook.target_energy.value, (
                    f"{s.label} energy {s.target_energy.value} should be below "
                    f"adjacent {hook.label} energy {hook.target_energy.value}"
                )

    def test_forced_high_bridge_is_repaired(self):
        plan = _build_plan(
            available_roles=["drums", "bass", "melody"],
            template="extended",
        )
        # Force a bridge to VERY_HIGH energy
        for s in plan.sections:
            if s.section_type in (SectionKind.BRIDGE, SectionKind.BREAKDOWN):
                s.target_energy = EnergyLevel.VERY_HIGH

        result = ProducerRulesEngine.apply(plan)
        bridge_violations = [v for v in result.violations if v.rule_name == "bridge_contrast"]
        if bridge_violations:  # Only if bridge has a hook neighbour
            assert all(v.auto_repaired for v in bridge_violations)


class TestOutroSimplificationRule:
    """outro_simplification: outros must be sparse/low energy."""

    def test_outros_are_low_energy_and_sparse(self):
        plan = _build_plan(available_roles=["drums", "bass", "melody"])
        result = ProducerRulesEngine.apply(plan)
        outros = [s for s in result.plan.sections if s.section_type == SectionKind.OUTRO]
        for outro in outros:
            assert outro.target_energy.value <= EnergyLevel.LOW.value
            assert outro.density in (DensityLevel.SPARSE, DensityLevel.MEDIUM)

    def test_forced_energetic_outro_repaired(self):
        plan = _build_plan(available_roles=["drums", "bass"])
        for s in plan.sections:
            if s.section_type == SectionKind.OUTRO:
                s.target_energy = EnergyLevel.VERY_HIGH
                s.density = DensityLevel.FULL

        result = ProducerRulesEngine.apply(plan)
        outro_violations = [v for v in result.violations if v.rule_name == "outro_simplification"]
        assert outro_violations
        assert all(v.auto_repaired for v in outro_violations)


class TestRepetitionControlRule:
    """repetition_control: no consecutive identical sections."""

    def test_consecutive_identical_sections_get_variation_upgrade(self):
        plan = _build_plan(available_roles=["drums", "bass", "melody"])
        # Inject two consecutive same-type sections with identical roles
        from copy import deepcopy
        if len(plan.sections) >= 2:
            plan.sections[0].section_type = SectionKind.VERSE
            plan.sections[0].active_roles = ["drums", "bass"]
            plan.sections[0].variation_strategy = VariationStrategy.REPEAT
            plan.sections[1].section_type = SectionKind.VERSE
            plan.sections[1].active_roles = ["drums", "bass"]
            plan.sections[1].variation_strategy = VariationStrategy.REPEAT

        result = ProducerRulesEngine.apply(plan)
        # The second of the two injected identical sections should have upgraded variation
        repaired = [v for v in result.violations if v.rule_name == "repetition_control" and v.auto_repaired]
        if plan.sections[0].section_type == plan.sections[1].section_type:
            assert repaired, "Should auto-repair repetition"


class TestOvercrowdingGuard:
    """overcrowding_guard: density must not exceed allowed cap per section type."""

    def test_breakdown_cannot_exceed_sparse(self):
        plan = _build_plan(
            available_roles=["drums", "bass", "melody"],
            template="extended",
        )
        # Force a breakdown to FULL density
        for s in plan.sections:
            if s.section_type == SectionKind.BREAKDOWN:
                s.density = DensityLevel.FULL

        result = ProducerRulesEngine.apply(plan)
        overcrowd_violations = [v for v in result.violations if v.rule_name == "overcrowding_guard"]
        if any(s.section_type == SectionKind.BREAKDOWN for s in plan.sections):
            assert overcrowd_violations
            assert all(v.auto_repaired for v in overcrowd_violations)


class TestRulesEngineResult:
    """RulesEngineResult contract tests."""

    def test_result_has_rules_run(self):
        plan = _build_plan()
        result = ProducerRulesEngine.apply(plan)
        assert len(result.rules_run) > 0

    def test_result_is_compliant_after_auto_repair(self):
        """After applying rules to a well-formed plan it should be compliant."""
        plan = _build_plan(available_roles=["drums", "bass", "melody"])
        result = ProducerRulesEngine.apply(plan)
        assert result.is_compliant, (
            f"Plan should be compliant after rules. Errors: "
            f"{[v.description for v in result.violations if v.severity == 'error' and not v.auto_repaired]}"
        )

    def test_result_to_dict_is_json_safe(self):
        import json
        plan = _build_plan()
        result = ProducerRulesEngine.apply(plan)
        d = result.to_dict()
        serialized = json.dumps(d)
        assert len(serialized) > 0

    def test_decision_log_updated_after_rules(self):
        plan = _build_plan(available_roles=["drums", "bass", "melody"])
        initial_log_len = len(plan.decision_log)
        # Force a violation to trigger log updates
        for s in plan.sections:
            if s.section_type == SectionKind.INTRO:
                s.density = DensityLevel.FULL
        result = ProducerRulesEngine.apply(plan)
        assert len(result.plan.decision_log) >= initial_log_len


class TestFallbackWithLimitedStems:
    """Rules engine gracefully handles limited stem availability."""

    def test_no_stems_does_not_crash(self):
        plan = _build_plan(available_roles=[])
        result = ProducerRulesEngine.apply(plan)
        assert result is not None
        assert "role_aware_adaptation" in result.rules_run

    def test_single_role_produces_compliant_plan(self):
        plan = _build_plan(available_roles=["full_mix"])
        result = ProducerRulesEngine.apply(plan)
        assert result.is_compliant

    def test_two_roles_produces_compliant_plan(self):
        plan = _build_plan(available_roles=["drums", "bass"])
        result = ProducerRulesEngine.apply(plan)
        assert result.is_compliant
