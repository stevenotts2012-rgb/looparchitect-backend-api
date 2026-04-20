"""
Tests for AIMicroPlanner — Phase 5.

Covers:
- Deterministic micro-plan generation from ProducerArrangementPlanV2
- Delayed melody entry (intro/breakdown)
- Hat build (pre-hook)
- Hook kick/bass deltas
- Verse midpoint layer add
- Section-end fill
- Bridge/breakdown drop+reentry
- Outro progressive removal
- Vague delta rejection
- Bar range validation
- Empty plan handling
"""

from __future__ import annotations

import pytest

from app.services.ai_micro_planner import AIMicroPlanner, _is_vague
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
    length_bars: int,
    active_roles: list[str] | None = None,
    label: str = "",
) -> ProducerSectionPlan:
    if active_roles is None:
        active_roles = ["drums", "bass", "melody"]
    return ProducerSectionPlan(
        index=index,
        section_type=section_type,
        label=label or f"{section_type.value.title()} {index + 1}",
        start_bar=start_bar,
        length_bars=length_bars,
        target_energy=EnergyLevel.MEDIUM,
        density=DensityLevel.MEDIUM,
        active_roles=list(active_roles),
        muted_roles=[],
        introduced_roles=[],
        removed_roles=[],
        variation_strategy=VariationStrategy.REPEAT,
        transition_in=TransitionIntent.NONE,
        transition_out=TransitionIntent.NONE,
    )


def _make_plan(sections: list[ProducerSectionPlan], available_roles: list[str] | None = None) -> ProducerArrangementPlanV2:
    return ProducerArrangementPlanV2(
        sections=sections,
        genre="trap",
        tempo=140.0,
        total_bars=sum(s.length_bars for s in sections),
        available_roles=available_roles or ["drums", "bass", "melody", "arp"],
    )


# ---------------------------------------------------------------------------
# _is_vague helper
# ---------------------------------------------------------------------------


class TestIsVague:
    def test_vague_phrase_detected(self):
        assert _is_vague("add more energy")
        assert _is_vague("make it bigger")
        assert _is_vague("keep it the same but stronger")

    def test_concrete_phrase_not_vague(self):
        assert not _is_vague("four_on_floor kick bars 1-8")
        assert not _is_vague("delayed melody entry 4 bars")
        assert not _is_vague("hat_density_up bars 5-8")

    def test_empty_string_not_vague(self):
        assert not _is_vague("")

    def test_case_insensitive(self):
        assert _is_vague("ADD MORE ENERGY")
        assert _is_vague("Make It Bigger")


# ---------------------------------------------------------------------------
# AIMicroPlanner
# ---------------------------------------------------------------------------


class TestAIMicroPlannerBasic:
    def test_empty_plan_returns_empty_micro_plan(self):
        plan = _make_plan([])
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        assert micro.sections == []
        assert micro.total_deltas == 0

    def test_plan_returns_one_micro_section_per_section(self):
        sections = [
            _make_section(0, SectionKind.INTRO, 0, 8),
            _make_section(1, SectionKind.VERSE, 8, 8),
            _make_section(2, SectionKind.HOOK, 16, 8),
        ]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        assert len(micro.sections) == 3

    def test_section_indices_match(self):
        sections = [
            _make_section(0, SectionKind.VERSE, 0, 8),
            _make_section(1, SectionKind.HOOK, 8, 8),
        ]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        indices = [s.section_index for s in micro.sections]
        assert indices == [0, 1]

    def test_total_bars_matches_section_length(self):
        sections = [_make_section(0, SectionKind.VERSE, 0, 12)]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        assert micro.sections[0].total_bars == 12

    def test_generated_by_is_deterministic(self):
        plan = _make_plan([_make_section(0, SectionKind.VERSE, 0, 8)])
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        assert micro.generated_by == "deterministic"


class TestIntroMicroPlan:
    def test_intro_with_melody_has_delayed_entry(self):
        sections = [_make_section(0, SectionKind.INTRO, 0, 8, active_roles=["drums", "melody"])]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        intro_section = micro.sections[0]
        reasons = [d.reason.lower() for d in intro_section.bar_ranges]
        assert any("delayed" in r for r in reasons)

    def test_intro_without_melody_has_no_delay_delta(self):
        sections = [_make_section(0, SectionKind.INTRO, 0, 8, active_roles=["drums", "bass"])]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        intro_section = micro.sections[0]
        delay_deltas = [d for d in intro_section.bar_ranges if "delayed" in d.reason.lower()]
        assert len(delay_deltas) == 0

    def test_intro_delayed_entry_bar_range_is_valid(self):
        sections = [_make_section(0, SectionKind.INTRO, 0, 8, active_roles=["drums", "melody"])]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        intro_section = micro.sections[0]
        for delta in intro_section.bar_ranges:
            assert delta.bar_start >= 1
            assert delta.bar_end >= delta.bar_start


class TestPreHookMicroPlan:
    def test_pre_hook_with_drums_has_hat_build(self):
        sections = [_make_section(0, SectionKind.PRE_HOOK, 0, 8, active_roles=["drums", "bass"])]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        ph_section = micro.sections[0]
        hat_deltas = [d for d in ph_section.bar_ranges if d.hat_behavior]
        assert len(hat_deltas) > 0

    def test_pre_hook_short_has_no_build(self):
        sections = [_make_section(0, SectionKind.PRE_HOOK, 0, 2, active_roles=["drums"])]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        ph_section = micro.sections[0]
        # Short pre-hook (< 4 bars) — no build expected
        hat_deltas = [d for d in ph_section.bar_ranges if "hat_density" in d.hat_behavior.lower()]
        assert len(hat_deltas) == 0


class TestHookMicroPlan:
    def test_hook_with_drums_has_kick_delta(self):
        sections = [_make_section(0, SectionKind.HOOK, 0, 8, active_roles=["drums", "bass"])]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        hook_section = micro.sections[0]
        kick_deltas = [d for d in hook_section.bar_ranges if d.kick_behavior]
        assert len(kick_deltas) > 0

    def test_hook_with_bass_has_bass_delta(self):
        sections = [_make_section(0, SectionKind.HOOK, 0, 8, active_roles=["drums", "bass"])]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        hook_section = micro.sections[0]
        bass_deltas = [d for d in hook_section.bar_ranges if d.bass_behavior]
        assert len(bass_deltas) > 0

    def test_hook_kick_behavior_is_concrete(self):
        sections = [_make_section(0, SectionKind.HOOK, 0, 8, active_roles=["drums"])]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        hook_section = micro.sections[0]
        for delta in hook_section.bar_ranges:
            if delta.kick_behavior:
                assert not _is_vague(delta.kick_behavior)


class TestVerseMicroPlan:
    def test_verse_8_bars_has_midpoint_role_add(self):
        # Give 4 roles so there's a role available to add
        sections = [
            _make_section(0, SectionKind.VERSE, 0, 8, active_roles=["drums", "bass"])
        ]
        plan = _make_plan(sections, available_roles=["drums", "bass", "melody", "arp"])
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        verse_section = micro.sections[0]
        add_deltas = [d for d in verse_section.bar_ranges if d.role_add]
        assert len(add_deltas) > 0

    def test_verse_4_bars_no_midpoint_add(self):
        # 4-bar verse is too short for midpoint add (bars < 8)
        sections = [_make_section(0, SectionKind.VERSE, 0, 4, active_roles=["drums", "bass"])]
        plan = _make_plan(sections, available_roles=["drums", "bass", "melody"])
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        verse_section = micro.sections[0]
        add_deltas = [d for d in verse_section.bar_ranges if d.role_add]
        assert len(add_deltas) == 0


class TestFillDeltas:
    def test_verse_8_bars_has_fill(self):
        sections = [_make_section(0, SectionKind.VERSE, 0, 8, active_roles=["drums"])]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        verse_section = micro.sections[0]
        fill_deltas = [d for d in verse_section.bar_ranges if d.fill_at is not None]
        assert len(fill_deltas) > 0

    def test_intro_no_fill(self):
        # Intro is excluded from fill rule
        sections = [_make_section(0, SectionKind.INTRO, 0, 8, active_roles=["drums"])]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        intro_section = micro.sections[0]
        fill_deltas = [d for d in intro_section.bar_ranges if d.fill_at is not None]
        assert len(fill_deltas) == 0


class TestBreakdownMicroPlan:
    def test_breakdown_has_drop_delta(self):
        sections = [
            _make_section(0, SectionKind.BREAKDOWN, 0, 8, active_roles=["drums", "bass", "pads"])
        ]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        bd_section = micro.sections[0]
        drop_deltas = [d for d in bd_section.bar_ranges if d.drop_at is not None]
        assert len(drop_deltas) > 0

    def test_breakdown_has_reentry_delta(self):
        sections = [
            _make_section(0, SectionKind.BREAKDOWN, 0, 8, active_roles=["drums", "bass"])
        ]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        bd_section = micro.sections[0]
        reentry_deltas = [d for d in bd_section.bar_ranges if d.reentry_at is not None]
        assert len(reentry_deltas) > 0


class TestOutroMicroPlan:
    def test_outro_8_bars_has_progressive_removal(self):
        sections = [
            _make_section(0, SectionKind.OUTRO, 0, 8, active_roles=["drums", "bass", "melody"])
        ]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        outro_section = micro.sections[0]
        remove_deltas = [d for d in outro_section.bar_ranges if d.role_remove]
        assert len(remove_deltas) > 0

    def test_outro_short_no_progressive_removal(self):
        sections = [
            _make_section(0, SectionKind.OUTRO, 0, 2, active_roles=["drums"])
        ]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        outro_section = micro.sections[0]
        remove_deltas = [d for d in outro_section.bar_ranges if d.role_remove]
        assert len(remove_deltas) == 0


class TestDeltaValidation:
    def test_no_validation_errors_for_standard_plan(self):
        sections = [
            _make_section(0, SectionKind.INTRO, 0, 8),
            _make_section(1, SectionKind.VERSE, 8, 8),
            _make_section(2, SectionKind.PRE_HOOK, 16, 4),
            _make_section(3, SectionKind.HOOK, 20, 8),
            _make_section(4, SectionKind.OUTRO, 28, 4),
        ]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        assert micro.validation_errors == []

    def test_bar_ranges_are_sorted(self):
        sections = [_make_section(0, SectionKind.HOOK, 0, 8)]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        for sec in micro.sections:
            starts = [d.bar_start for d in sec.bar_ranges]
            assert starts == sorted(starts)

    def test_all_bar_starts_are_positive(self):
        sections = [
            _make_section(0, SectionKind.INTRO, 0, 8),
            _make_section(1, SectionKind.HOOK, 8, 8),
            _make_section(2, SectionKind.BREAKDOWN, 16, 8),
            _make_section(3, SectionKind.OUTRO, 24, 8),
        ]
        plan = _make_plan(sections)
        planner = AIMicroPlanner()
        micro = planner.plan(plan)
        for sec in micro.sections:
            for delta in sec.bar_ranges:
                assert delta.bar_start >= 1
                assert delta.bar_end >= delta.bar_start
