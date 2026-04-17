"""
Unit tests for the timeline_engine module.

Covers:
- Timeline plan creation
- Repeated section variation
- Hook novelty
- Section templates
- Validation failures
- Graceful degradation for limited source material
"""

import pytest

from app.services.timeline_engine.event_engine import (
    SUPPORTED_ACTIONS,
    is_valid_action,
    make_add_layer,
    make_drum_fill,
    make_filter_sweep,
    make_remove_layer,
    make_silence_gap,
)
from app.services.timeline_engine.planner import TimelinePlanner
from app.services.timeline_engine.section_templates import (
    build_breakdown_section,
    build_bridge_section,
    build_hook_section,
    build_intro_section,
    build_outro_section,
    build_pre_hook_section,
    build_verse_section,
    get_section_template,
    list_section_types,
)
from app.services.timeline_engine.state import TimelineState
from app.services.timeline_engine.types import TimelineEvent, TimelinePlan, TimelineSection
from app.services.timeline_engine.validator import TimelineValidator, ValidationIssue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FULL_ROLES = ["kick", "bass", "hats", "melody", "synth", "pad", "percussion"]

STANDARD_SPEC = [
    {"name": "intro", "bars": 8},
    {"name": "verse", "bars": 16},
    {"name": "pre_hook", "bars": 8},
    {"name": "hook", "bars": 16},
    {"name": "bridge", "bars": 8},
    {"name": "verse", "bars": 16},
    {"name": "hook", "bars": 16},
    {"name": "outro", "bars": 8},
]


def _make_planner(roles=None):
    return TimelinePlanner(available_roles=roles or FULL_ROLES)


def _make_plan(spec=None, roles=None):
    return _make_planner(roles).build_plan(spec or STANDARD_SPEC)


# ===========================================================================
# Types
# ===========================================================================

class TestTimelineEvent:
    def test_valid_event_created(self):
        ev = TimelineEvent(bar_start=1, bar_end=4, action="add_layer", target_role="kick")
        assert ev.bar_start == 1
        assert ev.bar_end == 4
        assert ev.action == "add_layer"
        assert ev.target_role == "kick"
        assert ev.parameters == {}

    def test_event_with_parameters(self):
        ev = TimelineEvent(
            bar_start=2, bar_end=2, action="drum_fill", parameters={"intensity": 0.8}
        )
        assert ev.parameters["intensity"] == 0.8

    def test_invalid_bar_start_raises(self):
        with pytest.raises(ValueError, match="bar_start"):
            TimelineEvent(bar_start=0, bar_end=4, action="add_layer")

    def test_bar_end_before_bar_start_raises(self):
        with pytest.raises(ValueError, match="bar_end"):
            TimelineEvent(bar_start=5, bar_end=3, action="add_layer")

    def test_empty_action_raises(self):
        with pytest.raises(ValueError, match="action"):
            TimelineEvent(bar_start=1, bar_end=1, action="")


class TestTimelineSection:
    def test_valid_section_created(self):
        s = TimelineSection(name="verse", bars=16, target_energy=0.5, target_density=0.5)
        assert s.name == "verse"
        assert s.events == []
        assert s.active_roles == []

    def test_invalid_bars_raises(self):
        with pytest.raises(ValueError, match="bars"):
            TimelineSection(name="verse", bars=0, target_energy=0.5, target_density=0.5)

    def test_invalid_energy_raises(self):
        with pytest.raises(ValueError, match="target_energy"):
            TimelineSection(name="verse", bars=8, target_energy=1.5, target_density=0.5)

    def test_invalid_density_raises(self):
        with pytest.raises(ValueError, match="target_density"):
            TimelineSection(name="verse", bars=8, target_energy=0.5, target_density=-0.1)


class TestTimelinePlan:
    def test_valid_plan_created(self):
        plan = TimelinePlan(total_bars=32)
        assert plan.total_bars == 32
        assert plan.sections == []

    def test_negative_total_bars_raises(self):
        with pytest.raises(ValueError, match="total_bars"):
            TimelinePlan(total_bars=-1)


# ===========================================================================
# Event Engine
# ===========================================================================

class TestEventEngine:
    def test_supported_actions_non_empty(self):
        assert len(SUPPORTED_ACTIONS) >= 10

    def test_is_valid_action_known(self):
        for action in SUPPORTED_ACTIONS:
            assert is_valid_action(action)

    def test_is_valid_action_unknown(self):
        assert not is_valid_action("nonexistent_action")

    def test_make_add_layer(self):
        ev = make_add_layer(bar_start=1, bar_end=4, target_role="bass")
        assert ev.action == "add_layer"
        assert ev.target_role == "bass"

    def test_make_remove_layer(self):
        ev = make_remove_layer(bar_start=3, bar_end=4, target_role="hats")
        assert ev.action == "remove_layer"

    def test_make_drum_fill(self):
        ev = make_drum_fill(bar_start=8, duration_bars=2, intensity=1.0)
        assert ev.action == "drum_fill"
        assert ev.bar_end == 9  # bar_start + duration_bars - 1

    def test_make_filter_sweep(self):
        ev = make_filter_sweep(bar_start=1, bar_end=8, direction="low_to_high")
        assert ev.action == "filter_sweep"
        assert ev.parameters["direction"] == "low_to_high"

    def test_make_silence_gap(self):
        ev = make_silence_gap(bar_start=3, bar_end=4)
        assert ev.action == "silence_gap"


# ===========================================================================
# Section Templates
# ===========================================================================

class TestSectionTemplates:
    def test_all_section_types_listed(self):
        types = list_section_types()
        expected = {"intro", "verse", "pre_hook", "hook", "bridge", "breakdown", "outro"}
        assert expected.issubset(set(types))

    def test_get_section_template_returns_callable(self):
        fn = get_section_template("hook")
        assert callable(fn)

    def test_get_section_template_unknown_returns_none(self):
        assert get_section_template("unknown_section") is None

    def test_intro_is_sparse(self):
        section = build_intro_section(bars=8, available_roles=FULL_ROLES)
        assert section.name == "intro"
        assert len(section.active_roles) <= 2, "Intro should be sparse (max 2 roles)"
        assert section.target_energy <= 0.4

    def test_verse_has_groove(self):
        section = build_verse_section(bars=16, available_roles=FULL_ROLES)
        assert section.name == "verse"
        assert len(section.active_roles) >= 2
        assert section.target_energy >= 0.3

    def test_verse_second_occurrence_has_fill(self):
        section = build_verse_section(bars=16, available_roles=FULL_ROLES, occurrence=2)
        fill_events = [e for e in section.events if e.action == "drum_fill"]
        assert fill_events, "Second verse should include a drum fill"

    def test_pre_hook_has_filter_sweep(self):
        section = build_pre_hook_section(bars=8, available_roles=FULL_ROLES)
        sweep_events = [e for e in section.events if e.action == "filter_sweep"]
        assert sweep_events, "pre_hook should have a filter_sweep event"
        assert section.target_energy >= 0.6

    def test_hook_is_high_energy(self):
        section = build_hook_section(bars=16, available_roles=FULL_ROLES)
        assert section.name == "hook"
        assert section.target_energy >= 0.8

    def test_hook_second_occurrence_has_novelty(self):
        section1 = build_hook_section(bars=16, available_roles=FULL_ROLES, occurrence=1)
        section2 = build_hook_section(bars=16, available_roles=FULL_ROLES, occurrence=2)
        # Second occurrence must not be identical to first
        actions1 = {e.action for e in section1.events}
        actions2 = {e.action for e in section2.events}
        # Both should have events; second should differ in some way
        assert section2.events, "Second hook occurrence must have events"
        # The percussion pattern on occurrence 2 should be named differently
        perc_events_2 = [
            e for e in section2.events
            if e.action == "add_percussion" and "hook_perc_v2" in e.parameters.get("pattern", "")
        ]
        assert perc_events_2, "Second hook should add percussion with v2 pattern"

    def test_bridge_reduces_density(self):
        hook = build_hook_section(bars=16, available_roles=FULL_ROLES)
        bridge = build_bridge_section(bars=8, available_roles=FULL_ROLES)
        assert bridge.target_density < hook.target_density

    def test_breakdown_is_stripped(self):
        hook = build_hook_section(bars=16, available_roles=FULL_ROLES)
        breakdown = build_breakdown_section(bars=8, available_roles=FULL_ROLES)
        assert breakdown.target_energy < hook.target_energy
        assert breakdown.target_density < hook.target_density
        silence_events = [e for e in breakdown.events if e.action == "silence_gap"]
        assert silence_events, "Breakdown must include a silence_gap event"

    def test_outro_progressive_removal(self):
        section = build_outro_section(bars=8, available_roles=FULL_ROLES)
        remove_events = [e for e in section.events if e.action == "remove_layer"]
        assert remove_events, "Outro should remove layers progressively"
        assert section.target_energy <= 0.3

    def test_sections_have_correct_bars(self):
        for bars in (4, 8, 16):
            for builder in (
                build_intro_section,
                build_verse_section,
                build_pre_hook_section,
                build_hook_section,
                build_bridge_section,
                build_breakdown_section,
                build_outro_section,
            ):
                s = builder(bars=bars, available_roles=FULL_ROLES)
                assert s.bars == bars


# ===========================================================================
# Planner
# ===========================================================================

class TestTimelinePlanner:
    def test_plan_total_bars(self):
        plan = _make_plan()
        expected = sum(item["bars"] for item in STANDARD_SPEC)
        assert plan.total_bars == expected

    def test_plan_has_correct_section_count(self):
        plan = _make_plan()
        assert len(plan.sections) == len(STANDARD_SPEC)

    def test_plan_section_names_match_spec(self):
        plan = _make_plan()
        names = [s.name for s in plan.sections]
        expected = [item["name"] for item in STANDARD_SPEC]
        assert names == expected

    def test_energy_curve_length_matches_sections(self):
        plan = _make_plan()
        assert len(plan.energy_curve) == len(plan.sections)

    def test_energy_curve_not_flat(self):
        plan = _make_plan()
        span = max(plan.energy_curve) - min(plan.energy_curve)
        assert span >= 0.1, f"Energy curve is flat: {plan.energy_curve}"

    def test_plan_has_variation_log_for_repeated_sections(self):
        plan = _make_plan()
        # spec contains 2 verses and 2 hooks → at least 2 variation attempts
        assert len(plan.variation_log) >= 2

    def test_variation_log_entries_have_required_keys(self):
        plan = _make_plan()
        for entry in plan.variation_log:
            assert "section" in entry
            assert "attempt" in entry
            assert "success" in entry

    def test_state_snapshot_present(self):
        plan = _make_plan()
        snap = plan.state_snapshot
        assert "used_roles" in snap
        assert "energy_history" in snap
        assert "section_occurrence_count" in snap

    def test_hook_is_highest_energy(self):
        plan = _make_plan()
        peak = max(plan.energy_curve)
        hook_energies = [
            e
            for s, e in zip(plan.sections, plan.energy_curve)
            if s.name == "hook"
        ]
        assert hook_energies, "Plan should contain at least one hook"
        # Each hook energy should be within 0.05 of the peak
        for e in hook_energies:
            assert e >= peak - 0.05, f"Hook energy {e} is too far below peak {peak}"

    def test_outro_lower_energy_than_hook(self):
        plan = _make_plan()
        hook_energy = max(
            e for s, e in zip(plan.sections, plan.energy_curve) if s.name == "hook"
        )
        outro_energy = next(
            e for s, e in zip(plan.sections, plan.energy_curve) if s.name == "outro"
        )
        assert outro_energy < hook_energy

    def test_unknown_section_type_degrades_gracefully(self):
        spec = [{"name": "custom_break", "bars": 8}]
        plan = _make_planner().build_plan(spec)
        assert len(plan.sections) == 1
        assert plan.sections[0].name == "custom_break"

    def test_empty_spec_returns_empty_plan(self):
        plan = _make_planner().build_plan([])
        assert plan.sections == []
        assert plan.total_bars == 0


# ===========================================================================
# Graceful degradation — weak source material
# ===========================================================================

class TestGracefulDegradation:
    """Tests that the planner does not crash with minimal source material."""

    def test_single_role_plan_builds(self):
        planner = TimelinePlanner(available_roles=["kick"])
        plan = planner.build_plan(STANDARD_SPEC)
        assert len(plan.sections) == len(STANDARD_SPEC)

    def test_no_roles_plan_builds(self):
        planner = TimelinePlanner(available_roles=[])
        plan = planner.build_plan(STANDARD_SPEC)
        assert len(plan.sections) == len(STANDARD_SPEC)

    def test_weak_source_plan_has_no_forced_fills(self):
        """With weak source material we expect fewer injected events."""
        planner_weak = TimelinePlanner(available_roles=["kick"])
        planner_full = TimelinePlanner(available_roles=FULL_ROLES)
        spec = [{"name": "verse", "bars": 16}]
        plan_weak = planner_weak.build_plan(spec)
        plan_full = planner_full.build_plan(spec)
        # Weak source should have fewer total events
        weak_events = sum(len(s.events) for s in plan_weak.sections)
        full_events = sum(len(s.events) for s in plan_full.sections)
        assert weak_events <= full_events

    def test_weak_source_variation_log_records_failures(self):
        planner = TimelinePlanner(available_roles=["kick"])
        spec = [
            {"name": "verse", "bars": 8},
            {"name": "verse", "bars": 8},  # repeated — will attempt variation
        ]
        plan = planner.build_plan(spec)
        # At least one variation attempt should be recorded (even if it fails)
        assert len(plan.variation_log) >= 1


# ===========================================================================
# State
# ===========================================================================

class TestTimelineState:
    def test_record_section_updates_occurrence_count(self):
        state = TimelineState()
        state.record_section("verse", ["kick", "bass"], 0.5)
        state.record_section("verse", ["kick", "bass", "hats"], 0.55)
        assert state.occurrence_count("verse") == 2

    def test_record_section_tracks_used_roles(self):
        state = TimelineState()
        state.record_section("verse", ["kick", "bass"], 0.5)
        assert "kick" in state.used_roles
        assert "bass" in state.used_roles

    def test_record_section_no_duplicate_roles(self):
        state = TimelineState()
        state.record_section("verse", ["kick", "bass"], 0.5)
        state.record_section("hook", ["kick", "melody"], 0.9)
        assert state.used_roles.count("kick") == 1

    def test_is_flat_false_with_variation(self):
        state = TimelineState()
        state.energy_history = [0.2, 0.5, 0.9, 0.3]
        assert not state.is_flat()

    def test_is_flat_true_with_no_variation(self):
        state = TimelineState()
        state.energy_history = [0.5, 0.52, 0.51, 0.5]
        assert state.is_flat()

    def test_to_dict_is_serialisable(self):
        state = TimelineState()
        state.record_section("intro", ["kick"], 0.2)
        d = state.to_dict()
        import json
        # Should not raise
        json.dumps(d)

    def test_variation_history_logged(self):
        state = TimelineState()
        state.record_variation_attempt("verse", "occurrence_2_variation", True)
        assert len(state.variation_history) == 1
        assert state.variation_history[0]["success"] is True


# ===========================================================================
# Validator
# ===========================================================================

class TestTimelineValidator:
    def _valid_plan(self):
        return _make_plan()

    def test_valid_plan_has_no_errors(self):
        plan = self._valid_plan()
        validator = TimelineValidator()
        issues = validator.validate(plan)
        errors = [i for i in issues if i.severity == "error"]
        assert not errors, f"Expected no errors, got: {errors}"

    def test_empty_plan_returns_error(self):
        validator = TimelineValidator()
        issues = validator.validate(TimelinePlan())
        assert any(i.rule == "empty_plan" for i in issues)

    def test_flat_energy_curve_triggers_error(self):
        plan = TimelinePlan(
            sections=[
                TimelineSection("intro", bars=8, target_energy=0.5, target_density=0.5),
                TimelineSection("verse", bars=16, target_energy=0.5, target_density=0.5),
                TimelineSection("hook", bars=16, target_energy=0.52, target_density=0.8),
            ],
            total_bars=40,
            energy_curve=[0.5, 0.5, 0.52],
        )
        validator = TimelineValidator()
        issues = validator.validate(plan)
        assert any(i.rule == "flat_timeline" for i in issues)

    def test_hook_not_peak_energy_triggers_error(self):
        plan = TimelinePlan(
            sections=[
                TimelineSection("intro", bars=8, target_energy=0.9, target_density=0.5),
                TimelineSection("hook", bars=16, target_energy=0.4, target_density=0.8),
                TimelineSection("outro", bars=8, target_energy=0.1, target_density=0.1),
            ],
            total_bars=32,
            energy_curve=[0.9, 0.4, 0.1],
        )
        validator = TimelineValidator()
        issues = validator.validate(plan)
        assert any(i.rule == "hook_not_peak_energy" for i in issues)

    def test_outro_too_high_energy_triggers_error(self):
        plan = TimelinePlan(
            sections=[
                TimelineSection("intro", bars=8, target_energy=0.3, target_density=0.3),
                TimelineSection("hook", bars=16, target_energy=0.9, target_density=0.9),
                TimelineSection("outro", bars=8, target_energy=0.9, target_density=0.5),
            ],
            total_bars=32,
            energy_curve=[0.3, 0.9, 0.9],
        )
        validator = TimelineValidator()
        issues = validator.validate(plan)
        assert any(i.rule == "outro_not_reduced_energy" for i in issues)

    def test_repeated_section_no_variation_triggers_warning(self):
        # Two identical verse sections with 0 events each
        verse_a = TimelineSection("verse", bars=16, target_energy=0.5, target_density=0.5)
        verse_b = TimelineSection("verse", bars=16, target_energy=0.5, target_density=0.5)
        plan = TimelinePlan(
            sections=[
                TimelineSection("intro", bars=8, target_energy=0.2, target_density=0.2),
                verse_a,
                TimelineSection("hook", bars=16, target_energy=0.9, target_density=0.9),
                verse_b,
                TimelineSection("outro", bars=8, target_energy=0.1, target_density=0.1),
            ],
            total_bars=64,
            energy_curve=[0.2, 0.5, 0.9, 0.5, 0.1],
        )
        validator = TimelineValidator()
        issues = validator.validate(plan)
        assert any(i.rule == "repeated_section_no_variation" for i in issues)

    def test_long_section_with_no_events_triggers_warning(self):
        plan = TimelinePlan(
            sections=[
                TimelineSection(
                    "verse", bars=20, target_energy=0.5, target_density=0.5, events=[]
                ),
                TimelineSection("hook", bars=16, target_energy=0.9, target_density=0.9),
                TimelineSection("outro", bars=8, target_energy=0.1, target_density=0.1),
            ],
            total_bars=44,
            energy_curve=[0.5, 0.9, 0.1],
        )
        validator = TimelineValidator()
        issues = validator.validate(plan)
        assert any(i.rule == "empty_events_long_section" for i in issues)

    def test_validation_issue_has_required_fields(self):
        issue = ValidationIssue(
            rule="test_rule",
            severity="error",
            message="Test message",
            section_name="verse",
        )
        assert issue.rule == "test_rule"
        assert issue.severity == "error"
        assert issue.section_name == "verse"
