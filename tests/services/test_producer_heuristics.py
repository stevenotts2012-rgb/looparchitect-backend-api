"""
Tests for new Phase 5 ProducerRulesEngine heuristics:
  - verse_2_differs
  - pre_hook_tension
  - change_every_4_8_bars

These tests validate that the new rules auto-repair or flag correctly.
"""

from __future__ import annotations

import pytest

from app.services.producer_rules_engine import ProducerRulesEngine
from app.services.producer_plan_builder import (
    ProducerArrangementPlanV2,
    ProducerSectionPlan,
    SectionKind,
    EnergyLevel,
    DensityLevel,
    VariationStrategy,
    TransitionIntent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_section(
    index: int,
    section_type: SectionKind,
    start_bar: int,
    length_bars: int = 8,
    energy: EnergyLevel = EnergyLevel.MEDIUM,
    density: DensityLevel = DensityLevel.MEDIUM,
    active_roles: list[str] | None = None,
    variation: VariationStrategy = VariationStrategy.REPEAT,
) -> ProducerSectionPlan:
    return ProducerSectionPlan(
        index=index,
        section_type=section_type,
        label=f"{section_type.value.title()} {index + 1}",
        start_bar=start_bar,
        length_bars=length_bars,
        target_energy=energy,
        density=density,
        active_roles=active_roles or ["drums", "bass"],
        muted_roles=[],
        introduced_roles=[],
        removed_roles=[],
        variation_strategy=variation,
        transition_in=TransitionIntent.NONE,
        transition_out=TransitionIntent.NONE,
    )


def _make_plan(
    sections: list[ProducerSectionPlan],
    available_roles: list[str] | None = None,
) -> ProducerArrangementPlanV2:
    return ProducerArrangementPlanV2(
        sections=sections,
        genre="trap",
        tempo=140.0,
        total_bars=sum(s.length_bars for s in sections),
        available_roles=available_roles or ["drums", "bass", "melody"],
    )


def _run_only(rule_name: str, plan: ProducerArrangementPlanV2) -> list:
    """Run only the named rule directly via the engine's classmethod."""
    rule_fn = getattr(ProducerRulesEngine, f"_rule_{rule_name}")
    return rule_fn(plan)


# ---------------------------------------------------------------------------
# verse_2_differs
# ---------------------------------------------------------------------------


class TestVerse2Differs:
    def test_identical_verses_trigger_violation(self):
        sections = [
            _make_section(0, SectionKind.VERSE, 0, energy=EnergyLevel.MEDIUM, active_roles=["drums", "bass"]),
            _make_section(1, SectionKind.VERSE, 8, energy=EnergyLevel.MEDIUM, active_roles=["drums", "bass"]),
        ]
        plan = _make_plan(sections)
        violations = _run_only("verse_2_differs", plan)
        assert len(violations) == 1
        assert violations[0].rule_name == "verse_2_differs"
        assert violations[0].auto_repaired is True

    def test_different_energy_no_violation(self):
        sections = [
            _make_section(0, SectionKind.VERSE, 0, energy=EnergyLevel.MEDIUM, active_roles=["drums", "bass"]),
            _make_section(1, SectionKind.VERSE, 8, energy=EnergyLevel.HIGH, active_roles=["drums", "bass"]),
        ]
        plan = _make_plan(sections)
        violations = _run_only("verse_2_differs", plan)
        assert len(violations) == 0

    def test_different_roles_no_violation(self):
        sections = [
            _make_section(0, SectionKind.VERSE, 0, active_roles=["drums", "bass"]),
            _make_section(1, SectionKind.VERSE, 8, active_roles=["melody", "synth"]),
        ]
        plan = _make_plan(sections)
        violations = _run_only("verse_2_differs", plan)
        assert len(violations) == 0

    def test_only_one_verse_no_violation(self):
        sections = [
            _make_section(0, SectionKind.VERSE, 0, active_roles=["drums", "bass"]),
        ]
        plan = _make_plan(sections)
        violations = _run_only("verse_2_differs", plan)
        assert len(violations) == 0

    def test_repair_boosts_energy_or_changes_strategy(self):
        v1 = _make_section(0, SectionKind.VERSE, 0, energy=EnergyLevel.MEDIUM, active_roles=["drums"])
        v2 = _make_section(1, SectionKind.VERSE, 8, energy=EnergyLevel.MEDIUM, active_roles=["drums"])
        plan = _make_plan([v1, v2])
        _run_only("verse_2_differs", plan)
        # After repair: either verse 2 energy differs or strategy changed
        e_diff = plan.sections[1].target_energy.value != plan.sections[0].target_energy.value
        strat_changed = plan.sections[1].variation_strategy != VariationStrategy.REPEAT
        assert e_diff or strat_changed

    def test_verse_at_max_energy_changes_strategy(self):
        # When verse 2 is at max energy, can't boost → strategy must change
        v1 = _make_section(0, SectionKind.VERSE, 0, energy=EnergyLevel.VERY_HIGH, active_roles=["drums"])
        v2 = _make_section(1, SectionKind.VERSE, 8, energy=EnergyLevel.VERY_HIGH, active_roles=["drums"])
        plan = _make_plan([v1, v2])
        violations = _run_only("verse_2_differs", plan)
        assert len(violations) == 1
        assert plan.sections[1].variation_strategy == VariationStrategy.RHYTHM_VARIATION

    def test_via_full_apply_runs_verse_2_differs(self):
        sections = [
            _make_section(0, SectionKind.INTRO, 0, energy=EnergyLevel.LOW, density=DensityLevel.SPARSE),
            _make_section(1, SectionKind.VERSE, 8, energy=EnergyLevel.MEDIUM, active_roles=["drums", "bass"]),
            _make_section(2, SectionKind.HOOK, 16, energy=EnergyLevel.VERY_HIGH, density=DensityLevel.FULL),
            _make_section(3, SectionKind.VERSE, 24, energy=EnergyLevel.MEDIUM, active_roles=["drums", "bass"]),
        ]
        plan = _make_plan(sections)
        result = ProducerRulesEngine.apply(plan)
        assert "verse_2_differs" in result.rules_run


# ---------------------------------------------------------------------------
# pre_hook_tension
# ---------------------------------------------------------------------------


class TestPreHookTension:
    def test_weak_pre_hook_triggers_violation(self):
        # Pre-hook energy equal to verse energy → violation
        sections = [
            _make_section(0, SectionKind.VERSE, 0, energy=EnergyLevel.MEDIUM),
            _make_section(1, SectionKind.PRE_HOOK, 8, energy=EnergyLevel.MEDIUM),
        ]
        plan = _make_plan(sections)
        violations = _run_only("pre_hook_tension", plan)
        assert len(violations) == 1
        assert violations[0].rule_name == "pre_hook_tension"
        assert violations[0].auto_repaired is True

    def test_full_density_pre_hook_triggers_violation(self):
        sections = [
            _make_section(0, SectionKind.VERSE, 0, energy=EnergyLevel.MEDIUM),
            _make_section(1, SectionKind.PRE_HOOK, 8, energy=EnergyLevel.HIGH, density=DensityLevel.FULL),
        ]
        plan = _make_plan(sections)
        violations = _run_only("pre_hook_tension", plan)
        assert len(violations) == 1
        # Density should be repaired to MEDIUM
        assert plan.sections[1].density == DensityLevel.MEDIUM

    def test_strong_pre_hook_no_violation(self):
        sections = [
            _make_section(0, SectionKind.VERSE, 0, energy=EnergyLevel.MEDIUM),
            _make_section(1, SectionKind.PRE_HOOK, 8, energy=EnergyLevel.HIGH, density=DensityLevel.MEDIUM),
        ]
        plan = _make_plan(sections)
        violations = _run_only("pre_hook_tension", plan)
        assert len(violations) == 0

    def test_no_pre_hooks_no_violation(self):
        sections = [
            _make_section(0, SectionKind.VERSE, 0),
            _make_section(1, SectionKind.HOOK, 8, energy=EnergyLevel.VERY_HIGH),
        ]
        plan = _make_plan(sections)
        violations = _run_only("pre_hook_tension", plan)
        assert len(violations) == 0

    def test_repair_boosts_energy_above_verse(self):
        verse = _make_section(0, SectionKind.VERSE, 0, energy=EnergyLevel.MEDIUM)
        ph = _make_section(1, SectionKind.PRE_HOOK, 8, energy=EnergyLevel.MEDIUM)
        plan = _make_plan([verse, ph])
        _run_only("pre_hook_tension", plan)
        # After repair: pre-hook energy must exceed verse energy
        assert plan.sections[1].target_energy.value > plan.sections[0].target_energy.value

    def test_via_full_apply_runs_pre_hook_tension(self):
        sections = [
            _make_section(0, SectionKind.INTRO, 0, energy=EnergyLevel.LOW, density=DensityLevel.SPARSE),
            _make_section(1, SectionKind.VERSE, 8, energy=EnergyLevel.MEDIUM),
            _make_section(2, SectionKind.PRE_HOOK, 16, energy=EnergyLevel.MEDIUM),
            _make_section(3, SectionKind.HOOK, 24, energy=EnergyLevel.VERY_HIGH, density=DensityLevel.FULL),
        ]
        plan = _make_plan(sections)
        result = ProducerRulesEngine.apply(plan)
        assert "pre_hook_tension" in result.rules_run


# ---------------------------------------------------------------------------
# change_every_4_8_bars
# ---------------------------------------------------------------------------


class TestChangeEvery4To8Bars:
    def test_long_repeat_section_with_3_roles_triggers_warning(self):
        sections = [
            _make_section(0, SectionKind.VERSE, 0, length_bars=16,
                          variation=VariationStrategy.REPEAT),
        ]
        plan = _make_plan(sections, available_roles=["drums", "bass", "melody"])
        violations = _run_only("change_every_4_8_bars", plan)
        assert len(violations) == 1
        assert violations[0].rule_name == "change_every_4_8_bars"
        assert violations[0].severity == "warning"
        assert violations[0].auto_repaired is False

    def test_long_section_with_varied_strategy_no_violation(self):
        sections = [
            _make_section(0, SectionKind.VERSE, 0, length_bars=16,
                          variation=VariationStrategy.LAYER_ADD),
        ]
        plan = _make_plan(sections, available_roles=["drums", "bass", "melody"])
        violations = _run_only("change_every_4_8_bars", plan)
        assert len(violations) == 0

    def test_short_section_no_violation(self):
        # 8-bar section is at boundary — rule fires at > 8 bars
        sections = [
            _make_section(0, SectionKind.VERSE, 0, length_bars=8,
                          variation=VariationStrategy.REPEAT),
        ]
        plan = _make_plan(sections, available_roles=["drums", "bass", "melody"])
        violations = _run_only("change_every_4_8_bars", plan)
        assert len(violations) == 0

    def test_insufficient_roles_no_violation(self):
        # Only 2 roles → rule not applied
        sections = [
            _make_section(0, SectionKind.VERSE, 0, length_bars=16,
                          variation=VariationStrategy.REPEAT, active_roles=["drums"]),
        ]
        plan = _make_plan(sections, available_roles=["drums", "bass"])
        violations = _run_only("change_every_4_8_bars", plan)
        assert len(violations) == 0

    def test_via_full_apply_runs_change_every_4_8_bars(self):
        sections = [
            _make_section(0, SectionKind.INTRO, 0, energy=EnergyLevel.LOW, density=DensityLevel.SPARSE),
            _make_section(1, SectionKind.VERSE, 8, length_bars=16, variation=VariationStrategy.REPEAT),
            _make_section(2, SectionKind.HOOK, 24, energy=EnergyLevel.VERY_HIGH, density=DensityLevel.FULL),
        ]
        plan = _make_plan(sections, available_roles=["drums", "bass", "melody"])
        result = ProducerRulesEngine.apply(plan)
        assert "change_every_4_8_bars" in result.rules_run
