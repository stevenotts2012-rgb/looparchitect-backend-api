"""
Unit tests for the Pattern Variation Engine.

Coverage:
1.  Drum pattern variation by section type.
2.  Repeated section differentiation (verse 2 ≠ verse 1, hook 2 > hook 1).
3.  Hook escalation (hook 3 is richer than hook 2 is richer than hook 1).
4.  Bass dropout and re-entry behaviour.
5.  Melody delayed entry behaviour.
6.  Graceful degradation for weak sources (ai_separated, stereo_fallback).
7.  Validator failures and auto-repairs.
8.  PatternEvent type contract and bounds checking.
9.  PatternVariationState tracking helpers.
10. Full plan serialisation round-trip.
"""

from __future__ import annotations

import pytest

from app.services.pattern_variation_engine import (
    PatternAction,
    PatternEvent,
    PatternSectionPlan,
    PatternVariationPlan,
    PatternVariationPlanner,
    PatternVariationState,
    PatternVariationValidator,
    build_bass_plan,
    build_drum_plan,
    build_melodic_plan,
)
from app.services.pattern_variation_engine.validator import PatternValidationIssue


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

FULL_SPEC = [
    {"section_type": "intro",     "section_name": "Intro",     "bars": 8},
    {"section_type": "verse",     "section_name": "Verse 1",   "bars": 16},
    {"section_type": "pre_hook",  "section_name": "Pre-Hook 1","bars": 8},
    {"section_type": "hook",      "section_name": "Hook 1",    "bars": 16},
    {"section_type": "verse",     "section_name": "Verse 2",   "bars": 16},
    {"section_type": "pre_hook",  "section_name": "Pre-Hook 2","bars": 8},
    {"section_type": "hook",      "section_name": "Hook 2",    "bars": 16},
    {"section_type": "bridge",    "section_name": "Bridge",    "bars": 8},
    {"section_type": "breakdown", "section_name": "Breakdown", "bars": 8},
    {"section_type": "hook",      "section_name": "Hook 3",    "bars": 16},
    {"section_type": "outro",     "section_name": "Outro",     "bars": 8},
]


def _plan(source_quality: str = "true_stems") -> PatternVariationPlan:
    return PatternVariationPlanner(source_quality=source_quality).build_plan(FULL_SPEC)


def _actions(section: PatternSectionPlan) -> set[PatternAction]:
    return {e.pattern_action for e in section.events}


# ===========================================================================
# 1. PatternEvent type contract
# ===========================================================================

class TestPatternEventContract:
    def test_valid_event_creates_cleanly(self):
        evt = PatternEvent(
            bar_start=1,
            bar_end=4,
            role="drums",
            pattern_action=PatternAction.DROP_KICK,
        )
        assert evt.bar_start == 1
        assert evt.bar_end == 4
        assert evt.intensity == 0.7  # default

    def test_intensity_clamped_high(self):
        evt = PatternEvent(
            bar_start=1, bar_end=1, role="drums",
            pattern_action=PatternAction.SNARE_FILL, intensity=5.0,
        )
        assert evt.intensity == 1.0

    def test_intensity_clamped_low(self):
        evt = PatternEvent(
            bar_start=1, bar_end=1, role="bass",
            pattern_action=PatternAction.BASS_DROPOUT, intensity=-2.0,
        )
        assert evt.intensity == 0.0

    def test_bar_start_must_be_positive(self):
        with pytest.raises(ValueError, match="bar_start"):
            PatternEvent(
                bar_start=0, bar_end=2, role="drums",
                pattern_action=PatternAction.DROP_KICK,
            )

    def test_bar_end_must_be_gte_bar_start(self):
        with pytest.raises(ValueError, match="bar_end"):
            PatternEvent(
                bar_start=5, bar_end=3, role="melody",
                pattern_action=PatternAction.MELODY_DROPOUT,
            )

    def test_empty_role_raises(self):
        with pytest.raises(ValueError, match="role"):
            PatternEvent(
                bar_start=1, bar_end=1, role="",
                pattern_action=PatternAction.BASS_DROPOUT,
            )

    def test_invalid_pattern_action_type_raises(self):
        with pytest.raises(TypeError, match="PatternAction"):
            PatternEvent(
                bar_start=1, bar_end=1, role="drums",
                pattern_action="drop_kick",  # type: ignore[arg-type]
            )


# ===========================================================================
# 2. PatternSectionPlan contract
# ===========================================================================

class TestPatternSectionPlanContract:
    def test_bars_must_be_positive(self):
        with pytest.raises(ValueError, match="bars"):
            PatternSectionPlan(
                section_name="X", section_type="verse",
                occurrence=1, bars=0,
            )

    def test_occurrence_must_be_positive(self):
        with pytest.raises(ValueError, match="occurrence"):
            PatternSectionPlan(
                section_name="X", section_type="verse",
                occurrence=0, bars=8,
            )

    def test_has_action(self):
        sp = PatternSectionPlan(
            section_name="Verse 1", section_type="verse", occurrence=1, bars=8,
        )
        evt = PatternEvent(
            bar_start=1, bar_end=4, role="drums",
            pattern_action=PatternAction.DROP_KICK,
        )
        sp.events.append(evt)
        assert sp.has_action(PatternAction.DROP_KICK)
        assert not sp.has_action(PatternAction.SNARE_FILL)

    def test_active_actions_deduplicated(self):
        sp = PatternSectionPlan(
            section_name="Hook 1", section_type="hook", occurrence=1, bars=16,
        )
        for _ in range(3):
            sp.events.append(PatternEvent(
                bar_start=1, bar_end=4, role="drums",
                pattern_action=PatternAction.HAT_DENSITY_UP,
            ))
        assert len(sp.active_actions) == 1


# ===========================================================================
# 3. Drum pattern variation by section type
# ===========================================================================

class TestDrumPatternsBySection:
    def test_intro_drops_kick(self):
        events = build_drum_plan("intro", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.DROP_KICK in actions

    def test_intro_has_low_hat_density(self):
        events = build_drum_plan("intro", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.HAT_DENSITY_DOWN in actions

    def test_verse_1_no_drum_events(self):
        events = build_drum_plan("verse", occurrence=1, bars=16,
                                 source_quality="true_stems")
        assert events == []

    def test_verse_2_adds_syncopated_kick(self):
        events = build_drum_plan("verse", occurrence=2, bars=16,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.ADD_SYNCOPATED_KICK in actions

    def test_verse_2_reduced_quality_uses_hat_density(self):
        events = build_drum_plan("verse", occurrence=2, bars=16,
                                 source_quality="ai_separated")
        actions = {e.pattern_action for e in events}
        assert PatternAction.HAT_DENSITY_UP in actions
        assert PatternAction.ADD_SYNCOPATED_KICK not in actions

    def test_pre_hook_reduces_hats(self):
        events = build_drum_plan("pre_hook", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.HAT_DENSITY_DOWN in actions

    def test_pre_hook_adds_silence(self):
        events = build_drum_plan("pre_hook", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.PRE_DROP_SILENCE in actions

    def test_pre_hook_reduced_uses_snare_fill_not_silence(self):
        events = build_drum_plan("pre_hook", occurrence=1, bars=8,
                                 source_quality="ai_separated")
        actions = {e.pattern_action for e in events}
        assert PatternAction.SNARE_FILL in actions
        assert PatternAction.PRE_DROP_SILENCE not in actions

    def test_hook_1_hats_up(self):
        events = build_drum_plan("hook", occurrence=1, bars=16,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.HAT_DENSITY_UP in actions

    def test_hook_2_escalates_over_hook_1(self):
        hook1 = build_drum_plan("hook", occurrence=1, bars=16,
                                source_quality="true_stems")
        hook2 = build_drum_plan("hook", occurrence=2, bars=16,
                                source_quality="true_stems")
        assert len(hook2) > len(hook1), "Hook 2 must have more events than Hook 1"

    def test_hook_3_maximum_payoff(self):
        events = build_drum_plan("hook", occurrence=3, bars=16,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        # All three escalation actions should be present
        assert PatternAction.HAT_DENSITY_UP in actions
        assert PatternAction.ADD_SYNCOPATED_KICK in actions
        assert PatternAction.SNARE_FILL in actions
        assert PatternAction.PERC_FILL in actions

    def test_bridge_drops_kick(self):
        events = build_drum_plan("bridge", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.DROP_KICK in actions

    def test_bridge_has_halftime_when_long_enough(self):
        events = build_drum_plan("bridge", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.HALF_TIME_SWITCH in actions

    def test_breakdown_drops_kick_and_hats(self):
        events = build_drum_plan("breakdown", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.DROP_KICK in actions
        assert PatternAction.HAT_DENSITY_DOWN in actions

    def test_outro_progressive_strip(self):
        events = build_drum_plan("outro", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.DROP_KICK in actions
        assert PatternAction.HAT_DENSITY_DOWN in actions

    def test_stereo_fallback_no_drum_events(self):
        events = build_drum_plan("hook", occurrence=1, bars=16,
                                 source_quality="stereo_fallback")
        assert events == []

    def test_unknown_section_type_returns_empty(self):
        events = build_drum_plan("unknown_section", occurrence=1, bars=8,
                                 source_quality="true_stems")
        assert events == []


# ===========================================================================
# 4. Repeated section differentiation
# ===========================================================================

class TestRepeatedSectionDifferentiation:
    def test_verse_2_differs_from_verse_1(self):
        plan = _plan("true_stems")
        verses = plan.section_by_type("verse")
        assert len(verses) == 2
        v1_actions = _actions(verses[0])
        v2_actions = _actions(verses[1])
        assert v1_actions != v2_actions, (
            "Verse 2 must have a different action set from Verse 1"
        )

    def test_hook_2_differs_from_hook_1(self):
        plan = _plan("true_stems")
        hooks = plan.section_by_type("hook")
        assert len(hooks) >= 2
        h1_actions = _actions(hooks[0])
        h2_actions = _actions(hooks[1])
        assert h1_actions != h2_actions, (
            "Hook 2 must have a different action set from Hook 1"
        )


# ===========================================================================
# 5. Hook escalation
# ===========================================================================

class TestHookEscalation:
    def test_hook_event_count_escalates(self):
        plan = _plan("true_stems")
        hooks = plan.section_by_type("hook")
        assert len(hooks) == 3
        assert len(hooks[1].events) >= len(hooks[0].events), (
            "Hook 2 must have at least as many events as Hook 1"
        )
        assert len(hooks[2].events) >= len(hooks[1].events), (
            "Hook 3 must have at least as many events as Hook 2"
        )

    def test_hook_3_has_syncopated_kick(self):
        plan = _plan("true_stems")
        hooks = plan.section_by_type("hook")
        h3_actions = _actions(hooks[2])
        assert PatternAction.ADD_SYNCOPATED_KICK in h3_actions

    def test_hook_3_has_808_reentry(self):
        plan = _plan("true_stems")
        hooks = plan.section_by_type("hook")
        h3_bass_actions = {
            e.pattern_action
            for e in hooks[2].events
            if e.role == "bass"
        }
        assert PatternAction.REENTRY_808 in h3_bass_actions


# ===========================================================================
# 6. Bass dropout / re-entry
# ===========================================================================

class TestBassDropoutReentry:
    def test_pre_hook_bass_drops_out(self):
        events = build_bass_plan("pre_hook", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.BASS_DROPOUT in actions

    def test_hook_1_bass_808_reentry(self):
        events = build_bass_plan("hook", occurrence=1, bars=16,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.REENTRY_808 in actions

    def test_bridge_bass_drops_out(self):
        events = build_bass_plan("bridge", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.BASS_DROPOUT in actions

    def test_breakdown_full_bass_dropout(self):
        events = build_bass_plan("breakdown", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.BASS_DROPOUT in actions

    def test_hook_2_adds_octave_lift_full_quality(self):
        events = build_bass_plan("hook", occurrence=2, bars=16,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.OCTAVE_LIFT in actions

    def test_hook_2_no_octave_lift_ai_separated(self):
        events = build_bass_plan("hook", occurrence=2, bars=16,
                                 source_quality="ai_separated")
        actions = {e.pattern_action for e in events}
        # Octave lift risks mud with AI separation
        assert PatternAction.OCTAVE_LIFT not in actions

    def test_outro_progressive_bass_dropout(self):
        events = build_bass_plan("outro", occurrence=1, bars=8,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.BASS_DROPOUT in actions

    def test_verse_1_no_bass_events(self):
        events = build_bass_plan("verse", occurrence=1, bars=16,
                                 source_quality="true_stems")
        assert events == []

    def test_verse_2_syncopated_push(self):
        events = build_bass_plan("verse", occurrence=2, bars=16,
                                 source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.SYNCOPATED_BASS_PUSH in actions

    def test_stereo_fallback_no_bass_events(self):
        events = build_bass_plan("hook", occurrence=1, bars=16,
                                 source_quality="stereo_fallback")
        assert events == []


# ===========================================================================
# 7. Melody delayed entry
# ===========================================================================

class TestMelodyDelayedEntry:
    def test_intro_melody_delayed(self):
        events = build_melodic_plan("intro", occurrence=1, bars=8,
                                    source_quality="true_stems")
        assert events, "Intro must have melody events"
        assert all(
            e.pattern_action == PatternAction.DELAYED_MELODY_ENTRY for e in events
        )

    def test_intro_delay_bar_is_past_bar_1(self):
        events = build_melodic_plan("intro", occurrence=1, bars=8,
                                    source_quality="true_stems")
        assert events[0].bar_start > 1, "Delayed entry must start after bar 1"

    def test_verse_1_no_melody_events(self):
        events = build_melodic_plan("verse", occurrence=1, bars=16,
                                    source_quality="true_stems")
        assert events == []

    def test_pre_hook_melody_dropout(self):
        events = build_melodic_plan("pre_hook", occurrence=1, bars=8,
                                    source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.MELODY_DROPOUT in actions

    def test_hook_1_no_melody_events(self):
        events = build_melodic_plan("hook", occurrence=1, bars=16,
                                    source_quality="true_stems")
        assert events == [], "Hook 1: straight full melody, no variation events"

    def test_hook_2_counter_melody_full_quality(self):
        events = build_melodic_plan("hook", occurrence=2, bars=16,
                                    source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.COUNTER_MELODY_ADD in actions

    def test_hook_2_no_counter_melody_ai_separated(self):
        events = build_melodic_plan("hook", occurrence=2, bars=16,
                                    source_quality="ai_separated")
        actions = {e.pattern_action for e in events}
        assert PatternAction.COUNTER_MELODY_ADD not in actions
        assert PatternAction.CALL_RESPONSE in actions

    def test_breakdown_full_melody_dropout(self):
        events = build_melodic_plan("breakdown", occurrence=1, bars=8,
                                    source_quality="true_stems")
        actions = {e.pattern_action for e in events}
        assert PatternAction.MELODY_DROPOUT in actions

    def test_stereo_fallback_no_melody_events(self):
        events = build_melodic_plan("hook", occurrence=1, bars=16,
                                    source_quality="stereo_fallback")
        assert events == []


# ===========================================================================
# 8. Graceful degradation for weak sources
# ===========================================================================

class TestGracefulDegradation:
    def test_stereo_fallback_plan_has_no_events(self):
        plan = _plan("stereo_fallback")
        assert plan.total_events == 0, (
            "stereo_fallback must produce a plan with zero pattern events"
        )

    def test_ai_separated_no_syncopated_kick_in_hook(self):
        events = build_drum_plan("hook", occurrence=3, bars=16,
                                 source_quality="ai_separated")
        actions = {e.pattern_action for e in events}
        assert PatternAction.ADD_SYNCOPATED_KICK not in actions

    def test_ai_separated_no_perc_fill(self):
        events = build_drum_plan("hook", occurrence=3, bars=16,
                                 source_quality="ai_separated")
        actions = {e.pattern_action for e in events}
        assert PatternAction.PERC_FILL not in actions

    def test_ai_separated_budget_lower_than_true_stems(self):
        planner_full = PatternVariationPlanner(source_quality="true_stems")
        planner_ai = PatternVariationPlanner(source_quality="ai_separated")
        assert planner_ai._budget < planner_full._budget

    def test_ai_separated_plan_has_fewer_events_than_true_stems(self):
        plan_full = _plan("true_stems")
        plan_ai = _plan("ai_separated")
        assert plan_ai.total_events <= plan_full.total_events

    def test_zip_stems_same_budget_as_true_stems(self):
        # zip_stems is treated like true_stems for richness
        planner_zip = PatternVariationPlanner(source_quality="zip_stems")
        planner_true = PatternVariationPlanner(source_quality="true_stems")
        # zip_stems budget is slightly below true_stems but rich enough to
        # still be > ai_separated
        planner_ai = PatternVariationPlanner(source_quality="ai_separated")
        assert planner_zip._budget >= planner_ai._budget


# ===========================================================================
# 9. Validator — failures and repairs
# ===========================================================================

class TestValidatorFailuresAndRepairs:
    def _make_empty_plan(
        self,
        section_type: str,
        section_name: str,
        occurrence: int = 1,
        bars: int = 8,
        source_quality: str = "true_stems",
    ) -> PatternVariationPlan:
        """Return a plan with a single section that has NO events."""
        sp = PatternSectionPlan(
            section_name=section_name,
            section_type=section_type,
            occurrence=occurrence,
            bars=bars,
            source_quality=source_quality,
        )
        return PatternVariationPlan(
            sections=[sp],
            source_quality=source_quality,
        )

    def test_pre_hook_without_tension_fails(self):
        plan = self._make_empty_plan("pre_hook", "Pre-Hook 1")
        validator = PatternVariationValidator()
        issues = validator.validate(plan)
        rules = [i.rule for i in issues]
        assert "pre_hook_must_create_tension" in rules

    def test_bridge_without_groove_reduction_fails(self):
        plan = self._make_empty_plan("bridge", "Bridge")
        validator = PatternVariationValidator()
        issues = validator.validate(plan)
        rules = [i.rule for i in issues]
        assert "bridge_breakdown_must_reduce_groove" in rules

    def test_breakdown_without_groove_reduction_fails(self):
        plan = self._make_empty_plan("breakdown", "Breakdown")
        validator = PatternVariationValidator()
        issues = validator.validate(plan)
        rules = [i.rule for i in issues]
        assert "bridge_breakdown_must_reduce_groove" in rules

    def test_outro_without_reduction_fails(self):
        plan = self._make_empty_plan("outro", "Outro")
        validator = PatternVariationValidator()
        issues = validator.validate(plan)
        rules = [i.rule for i in issues]
        assert "outro_must_reduce_activity" in rules

    def test_verse_2_identical_to_verse_1_fails(self):
        """Two verse sections with the same (empty) actions → validation error."""
        sp1 = PatternSectionPlan(
            section_name="Verse 1", section_type="verse",
            occurrence=1, bars=16,
        )
        sp2 = PatternSectionPlan(
            section_name="Verse 2", section_type="verse",
            occurrence=2, bars=16,
        )
        plan = PatternVariationPlan(
            sections=[sp1, sp2],
            source_quality="true_stems",
        )
        issues = PatternVariationValidator().validate(plan)
        rules = [i.rule for i in issues]
        assert "verse_2_must_differ_from_verse_1" in rules

    def test_hook_2_identical_to_hook_1_fails(self):
        """Two hook sections with the same (empty) actions → validation error."""
        sp1 = PatternSectionPlan(
            section_name="Hook 1", section_type="hook",
            occurrence=1, bars=16,
        )
        sp2 = PatternSectionPlan(
            section_name="Hook 2", section_type="hook",
            occurrence=2, bars=16,
        )
        plan = PatternVariationPlan(
            sections=[sp1, sp2],
            source_quality="true_stems",
        )
        issues = PatternVariationValidator().validate(plan)
        rules = [i.rule for i in issues]
        assert "hook_2_must_differ_from_hook_1" in rules

    def test_stereo_fallback_skips_verse_hook_rules(self):
        """stereo_fallback cannot differentiate sections; rules must not fire."""
        sp1 = PatternSectionPlan(
            section_name="Verse 1", section_type="verse",
            occurrence=1, bars=16, source_quality="stereo_fallback",
        )
        sp2 = PatternSectionPlan(
            section_name="Verse 2", section_type="verse",
            occurrence=2, bars=16, source_quality="stereo_fallback",
        )
        plan = PatternVariationPlan(
            sections=[sp1, sp2], source_quality="stereo_fallback"
        )
        issues = PatternVariationValidator().validate(plan)
        rules = [i.rule for i in issues]
        assert "verse_2_must_differ_from_verse_1" not in rules
        assert "hook_2_must_differ_from_hook_1" not in rules

    def test_repair_pre_hook_tension_injected(self):
        plan = self._make_empty_plan("pre_hook", "Pre-Hook 1")
        validator = PatternVariationValidator()
        issues = validator.validate_and_repair(plan)
        repaired = [i for i in issues if i.repaired]
        assert any(i.rule == "pre_hook_must_create_tension" for i in repaired)
        # After repair, the section must pass
        section = plan.sections[0]
        assert section.has_action(PatternAction.PRE_DROP_SILENCE)

    def test_repair_bridge_groove_injected(self):
        plan = self._make_empty_plan("bridge", "Bridge")
        validator = PatternVariationValidator()
        issues = validator.validate_and_repair(plan)
        section = plan.sections[0]
        assert section.has_action(PatternAction.DROP_KICK)

    def test_repair_outro_reduction_injected(self):
        plan = self._make_empty_plan("outro", "Outro")
        validator = PatternVariationValidator()
        issues = validator.validate_and_repair(plan)
        section = plan.sections[0]
        assert section.has_action(PatternAction.HAT_DENSITY_DOWN)

    def test_valid_plan_no_issues(self):
        """A plan produced by the planner should pass validation cleanly."""
        plan = _plan("true_stems")
        issues = PatternVariationValidator().validate(plan)
        errors = [i for i in issues if i.severity == "error"]
        assert errors == [], (
            f"Planner-generated plan must produce no validation errors. "
            f"Got: {[i.message for i in errors]}"
        )


# ===========================================================================
# 10. PatternVariationState helpers
# ===========================================================================

class TestPatternVariationState:
    def test_next_occurrence_increments(self):
        state = PatternVariationState()
        assert state.next_occurrence("verse") == 1
        assert state.next_occurrence("verse") == 2
        assert state.next_occurrence("hook") == 1

    def test_occurrence_count_returns_zero_for_unseen(self):
        state = PatternVariationState()
        assert state.occurrence_count("bridge") == 0

    def test_record_and_detect_pattern_combination(self):
        state = PatternVariationState()
        actions = [PatternAction.DROP_KICK, PatternAction.HAT_DENSITY_DOWN]
        state.record_pattern_combination("verse", actions)
        assert state.is_combination_used("verse", actions)
        assert not state.is_combination_used("verse", [PatternAction.SNARE_FILL])

    def test_energy_history_tracked(self):
        state = PatternVariationState()
        state.record_energy(0.3)
        state.record_energy(0.9)
        assert state.energy_history == [0.3, 0.9]

    def test_is_energy_flat_true_when_no_variation(self):
        state = PatternVariationState()
        state.record_energy(0.5)
        state.record_energy(0.5)
        assert state.is_energy_flat()

    def test_is_energy_flat_false_with_variation(self):
        state = PatternVariationState()
        state.record_energy(0.2)
        state.record_energy(0.9)
        assert not state.is_energy_flat()

    def test_to_dict_serialises(self):
        state = PatternVariationState()
        state.next_occurrence("verse")
        state.record_energy(0.5)
        d = state.to_dict()
        assert "section_occurrence_count" in d
        assert "energy_history" in d
        assert d["energy_history"] == [0.5]


# ===========================================================================
# 11. Full plan round-trip
# ===========================================================================

class TestFullPlanRoundTrip:
    def test_plan_to_dict_serialises_cleanly(self):
        plan = _plan("true_stems")
        d = plan.to_dict()
        assert "sections" in d
        assert "source_quality" in d
        assert d["source_quality"] == "true_stems"
        assert isinstance(d["sections"], list)

    def test_plan_has_correct_section_count(self):
        plan = _plan("true_stems")
        assert len(plan.sections) == len(FULL_SPEC)

    def test_plan_decision_log_populated(self):
        plan = _plan("true_stems")
        assert len(plan.decision_log) == len(FULL_SPEC)

    def test_plan_section_types_match_spec(self):
        plan = _plan("true_stems")
        expected_types = [item["section_type"] for item in FULL_SPEC]
        actual_types = [s.section_type for s in plan.sections]
        assert actual_types == expected_types

    def test_total_events_positive_for_rich_source(self):
        plan = _plan("true_stems")
        assert plan.total_events > 0

    def test_total_events_zero_for_stereo_fallback(self):
        plan = _plan("stereo_fallback")
        assert plan.total_events == 0
