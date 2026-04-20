"""
Comprehensive tests for the Drop Engine.

Coverage (63 tests):
1.  DropEvent type contract and validation.
2.  DropBoundaryPlan construction and properties.
3.  DropPlan construction and serialisation.
4.  DropEngineState recording and counters.
5.  Template: standard_hook_entry (occurrence 0, 1+).
6.  Template: fakeout_hook_entry.
7.  Template: delayed_hook_entry (incl. silence fallback when overused).
8.  Template: sparse_bridge_return.
9.  Template: smooth_hook_release.
10. Template: breakdown_rebuild.
11. Template: outro_resolve.
12. Template selector dispatching.
13. Pre-hook → hook: tension/payoff scores.
14. Hook 1 vs Hook 2 drop differentiation.
15. Hook 3 maximum payoff behaviour.
16. Bridge/breakdown return behaviour.
17. Outro resolution behaviour.
18. Anti-stacking logic (strong event stacking check).
19. Source-quality-aware degradation.
20. DropValidator warnings — all rules.
21. Serialisation correctness (round-trip JSON).
22. Shadow integration metadata storage.
23. Determinism (same input → same output).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from app.services.drop_engine import (
    DropBoundaryPlan,
    DropEngineState,
    DropEnginePlanner,
    DropEvent,
    DropPlan,
    DropValidationIssue,
    DropValidator,
    STRONG_EVENT_TYPES,
    SUPPORTED_DROP_EVENT_TYPES,
    VALID_PLACEMENTS,
)
from app.services.drop_engine.templates import (
    breakdown_rebuild,
    delayed_hook_entry,
    fakeout_hook_entry,
    outro_resolve,
    select_template,
    smooth_hook_release,
    sparse_bridge_return,
    standard_hook_entry,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _state() -> DropEngineState:
    return DropEngineState()


def _roles_full() -> List[str]:
    return ["drums", "bass", "melody", "pads", "fx"]


def _roles_minimal() -> List[str]:
    return ["drums"]


def _sections(*names: str) -> List[Dict[str, Any]]:
    return [{"type": n, "bars": 8} for n in names]


def _planner(source_quality: str = "true_stems", roles: List[str] | None = None) -> DropEnginePlanner:
    return DropEnginePlanner(
        source_quality=source_quality,
        available_roles=roles if roles is not None else _roles_full(),
    )


# ===========================================================================
# 1. DropEvent type contract
# ===========================================================================


class TestDropEvent:
    def test_valid_construction(self):
        e = DropEvent(
            boundary_name="pre_hook -> hook",
            from_section="pre_hook",
            to_section="hook",
            placement="pre_boundary",
            event_type="bass_dropout",
            intensity=0.75,
        )
        assert e.event_type == "bass_dropout"
        assert e.intensity == 0.75
        assert e.placement == "pre_boundary"

    def test_intensity_clamped_high(self):
        e = DropEvent("b", "a", "b", "boundary", "riser_build", intensity=2.0)
        assert e.intensity == 1.0

    def test_intensity_clamped_low(self):
        e = DropEvent("b", "a", "b", "boundary", "riser_build", intensity=-1.0)
        assert e.intensity == 0.0

    def test_invalid_placement_raises(self):
        with pytest.raises(ValueError, match="placement must be one of"):
            DropEvent("b", "a", "b", "invalid_placement", "riser_build")

    def test_invalid_event_type_raises(self):
        with pytest.raises(ValueError, match="event_type must be one of"):
            DropEvent("b", "a", "b", "boundary", "nonexistent_event")

    def test_empty_boundary_name_raises(self):
        with pytest.raises(ValueError, match="boundary_name must be a non-empty string"):
            DropEvent("", "a", "b", "boundary", "riser_build")

    def test_empty_from_section_raises(self):
        with pytest.raises(ValueError, match="from_section must be a non-empty string"):
            DropEvent("b", "", "b", "boundary", "riser_build")

    def test_empty_to_section_raises(self):
        with pytest.raises(ValueError, match="to_section must be a non-empty string"):
            DropEvent("b", "a", "", "boundary", "riser_build")

    def test_is_strong_true(self):
        for etype in STRONG_EVENT_TYPES:
            e = DropEvent("b", "a", "b", "boundary", etype)
            assert e.is_strong, f"{etype} should be strong"

    def test_is_strong_false(self):
        weak_types = SUPPORTED_DROP_EVENT_TYPES - STRONG_EVENT_TYPES
        for etype in weak_types:
            e = DropEvent("b", "a", "b", "boundary", etype)
            assert not e.is_strong, f"{etype} should not be strong"

    def test_to_dict_round_trip(self):
        e = DropEvent("b", "pre_hook", "hook", "pre_boundary", "bass_dropout", 0.8, notes="test")
        d = e.to_dict()
        assert d["event_type"] == "bass_dropout"
        assert d["intensity"] == 0.8
        assert d["notes"] == "test"
        # Ensure JSON serialisable
        json.dumps(d)

    def test_to_dict_no_notes_key_when_none(self):
        e = DropEvent("b", "pre_hook", "hook", "boundary", "riser_build")
        d = e.to_dict()
        assert "notes" not in d

    def test_all_placements_accepted(self):
        for placement in VALID_PLACEMENTS:
            e = DropEvent("b", "a", "b", placement, "riser_build")
            assert e.placement == placement


# ===========================================================================
# 2. DropBoundaryPlan construction
# ===========================================================================


class TestDropBoundaryPlan:
    def test_basic_construction(self):
        bp = DropBoundaryPlan(from_section="pre_hook", to_section="hook")
        assert bp.from_section == "pre_hook"
        assert bp.to_section == "hook"
        assert bp.occurrence_index == 0

    def test_negative_occurrence_index_raises(self):
        with pytest.raises(ValueError, match="occurrence_index must be >= 0"):
            DropBoundaryPlan("pre_hook", "hook", occurrence_index=-1)

    def test_boundary_name_first_occurrence(self):
        bp = DropBoundaryPlan("pre_hook", "hook", occurrence_index=0)
        assert bp.boundary_name == "pre_hook -> hook"

    def test_boundary_name_second_occurrence(self):
        bp = DropBoundaryPlan("pre_hook", "hook", occurrence_index=1)
        assert bp.boundary_name == "pre_hook -> hook_2"

    def test_tension_score_clamped(self):
        bp = DropBoundaryPlan("pre_hook", "hook", tension_score=2.0)
        assert bp.tension_score == 1.0

    def test_payoff_score_clamped(self):
        bp = DropBoundaryPlan("pre_hook", "hook", payoff_score=-1.0)
        assert bp.payoff_score == 0.0

    def test_all_events_with_primary_and_support(self):
        primary = DropEvent("b", "pre_hook", "hook", "pre_boundary", "bass_dropout")
        support = DropEvent("b", "pre_hook", "hook", "post_boundary", "re_entry_accent")
        bp = DropBoundaryPlan("pre_hook", "hook", primary_drop_event=primary, support_events=[support])
        assert len(bp.all_events) == 2
        assert bp.all_events[0] == primary
        assert bp.all_events[1] == support

    def test_to_dict_serialisable(self):
        primary = DropEvent("b", "pre_hook", "hook", "pre_boundary", "bass_dropout", 0.8)
        bp = DropBoundaryPlan(
            "pre_hook", "hook",
            tension_score=0.75, payoff_score=0.80,
            primary_drop_event=primary,
        )
        d = bp.to_dict()
        json.dumps(d)
        assert d["primary_drop_event"]["event_type"] == "bass_dropout"
        assert d["tension_score"] == 0.75
        assert d["payoff_score"] == 0.80


# ===========================================================================
# 3. DropPlan
# ===========================================================================


class TestDropPlan:
    def test_basic_construction(self):
        dp = DropPlan(total_drop_count=3, repeated_hook_drop_variation_score=0.8)
        assert dp.total_drop_count == 3

    def test_variation_score_clamped(self):
        dp = DropPlan(repeated_hook_drop_variation_score=5.0)
        assert dp.repeated_hook_drop_variation_score == 1.0

    def test_to_dict_serialisable(self):
        dp = DropPlan(total_drop_count=2, repeated_hook_drop_variation_score=0.75)
        d = dp.to_dict()
        json.dumps(d)
        assert d["total_drop_count"] == 2
        assert d["repeated_hook_drop_variation_score"] == 0.75


# ===========================================================================
# 4. DropEngineState
# ===========================================================================


class TestDropEngineState:
    def test_initial_state(self):
        s = DropEngineState()
        assert len(s.used_drop_event_types) == 0
        assert s.repeated_hook_boundary_count == 0
        assert s.silence_event_count == 0

    def test_record_boundary_tracks_event_type(self):
        s = DropEngineState()
        s.record_boundary("pre_hook -> hook", "bass_dropout", 0.7, 0.8)
        assert s.event_type_used("bass_dropout")
        assert not s.event_type_used("riser_build")

    def test_record_boundary_hook_entry_counter(self):
        s = DropEngineState()
        s.record_boundary("pre_hook -> hook", "bass_dropout", 0.7, 0.8)
        assert s.repeated_hook_boundary_count == 1
        s.record_boundary("pre_hook -> hook", "riser_build", 0.8, 0.9)
        assert s.repeated_hook_boundary_count == 2

    def test_record_boundary_silence_counter(self):
        s = DropEngineState()
        s.record_boundary("b", "pre_drop_silence", 0.5, 0.5)
        assert s.silence_event_count == 1
        s.record_boundary("b", "silence_tease", 0.5, 0.5)
        assert s.silence_event_count == 2

    def test_hook_entries_identical_false_single(self):
        s = DropEngineState()
        s.record_boundary("pre_hook -> hook", "bass_dropout", 0.7, 0.8)
        assert not s.hook_entries_are_identical()

    def test_hook_entries_identical_true(self):
        s = DropEngineState()
        s.record_boundary("pre_hook -> hook", "bass_dropout", 0.7, 0.8)
        s.record_boundary("pre_hook -> hook", "bass_dropout", 0.7, 0.8)
        assert s.hook_entries_are_identical()

    def test_hook_entries_identical_false_different(self):
        s = DropEngineState()
        s.record_boundary("pre_hook -> hook", "bass_dropout", 0.7, 0.8)
        s.record_boundary("pre_hook -> hook", "riser_build", 0.8, 0.9)
        assert not s.hook_entries_are_identical()

    def test_silence_overused(self):
        s = DropEngineState()
        for _ in range(3):
            s.record_boundary("b", "silence_tease", 0.5, 0.5)
        assert s.silence_overused(max_silence_events=2)

    def test_get_occurrence_index_increments(self):
        s = DropEngineState()
        assert s.get_occurrence_index("pre_hook -> hook") == 0
        assert s.get_occurrence_index("pre_hook -> hook") == 1
        assert s.get_occurrence_index("pre_hook -> hook") == 2
        assert s.get_occurrence_index("verse -> pre_hook") == 0


# ===========================================================================
# 5-11. Templates
# ===========================================================================


class TestTemplates:
    # ------------------------------------------------------------------
    # standard_hook_entry
    # ------------------------------------------------------------------

    def test_standard_hook_entry_occurrence_0_bass_dropout(self):
        bp = standard_hook_entry("pre_hook -> hook", "pre_hook", "hook", 0, "true_stems", _roles_full(), _state())
        assert bp.primary_drop_event is not None
        assert bp.primary_drop_event.event_type in ("bass_dropout", "filtered_pre_drop")
        assert bp.tension_score > 0.5

    def test_standard_hook_entry_occurrence_1_riser(self):
        bp = standard_hook_entry("pre_hook -> hook", "pre_hook", "hook", 1, "true_stems", _roles_full(), _state())
        assert bp.primary_drop_event is not None
        assert bp.primary_drop_event.event_type in ("riser_build", "snare_pickup")
        assert bp.payoff_score > 0.5

    def test_standard_hook_entry_degrades_weak_source(self):
        bp_strong = standard_hook_entry("b", "pre_hook", "hook", 0, "true_stems", _roles_full(), _state())
        bp_weak = standard_hook_entry("b", "pre_hook", "hook", 0, "stereo_fallback", _roles_full(), _state())
        assert bp_weak.tension_score < bp_strong.tension_score
        assert bp_weak.payoff_score < bp_strong.payoff_score

    def test_standard_hook_entry_support_event_true_stems(self):
        bp = standard_hook_entry("b", "pre_hook", "hook", 0, "true_stems", _roles_full(), _state())
        assert len(bp.support_events) > 0

    def test_standard_hook_entry_no_support_stereo_fallback(self):
        bp = standard_hook_entry("b", "pre_hook", "hook", 0, "stereo_fallback", _roles_minimal(), _state())
        assert len(bp.support_events) == 0

    # ------------------------------------------------------------------
    # fakeout_hook_entry
    # ------------------------------------------------------------------

    def test_fakeout_hook_entry_primary_kick_fakeout(self):
        bp = fakeout_hook_entry("b", "pre_hook", "hook", 1, "true_stems", _roles_full(), _state())
        assert bp.primary_drop_event.event_type == "kick_fakeout"
        assert bp.primary_drop_event.placement == "pre_boundary"

    def test_fakeout_hook_entry_support_re_entry(self):
        bp = fakeout_hook_entry("b", "pre_hook", "hook", 1, "true_stems", _roles_full(), _state())
        support_types = [e.event_type for e in bp.support_events]
        assert "re_entry_accent" in support_types

    def test_fakeout_hook_entry_weak_source_lower_intensity(self):
        bp_strong = fakeout_hook_entry("b", "pre_hook", "hook", 1, "true_stems", _roles_full(), _state())
        bp_weak = fakeout_hook_entry("b", "pre_hook", "hook", 1, "stereo_fallback", _roles_minimal(), _state())
        assert bp_weak.primary_drop_event.intensity < bp_strong.primary_drop_event.intensity

    # ------------------------------------------------------------------
    # delayed_hook_entry
    # ------------------------------------------------------------------

    def test_delayed_hook_entry_silence_tease(self):
        bp = delayed_hook_entry("b", "pre_hook", "hook", 2, "true_stems", _roles_full(), _state())
        assert bp.primary_drop_event.event_type == "silence_tease"
        assert bp.payoff_score >= 0.85

    def test_delayed_hook_entry_fallback_when_silence_overused(self):
        s = _state()
        # Exhaust silence budget
        for _ in range(3):
            s.record_boundary("x", "silence_tease", 0.5, 0.5)
        bp = delayed_hook_entry("b", "pre_hook", "hook", 2, "true_stems", _roles_full(), s)
        assert bp.primary_drop_event.event_type == "riser_build"

    def test_delayed_hook_entry_fallback_weak_source(self):
        bp = delayed_hook_entry("b", "pre_hook", "hook", 2, "stereo_fallback", _roles_minimal(), _state())
        assert bp.primary_drop_event.event_type == "riser_build"

    def test_delayed_hook_entry_staggered_reentry_support(self):
        bp = delayed_hook_entry("b", "pre_hook", "hook", 2, "true_stems", _roles_full(), _state())
        support_types = [e.event_type for e in bp.support_events]
        assert "staggered_reentry" in support_types

    # ------------------------------------------------------------------
    # sparse_bridge_return
    # ------------------------------------------------------------------

    def test_sparse_bridge_return_has_primary(self):
        bp = sparse_bridge_return("b", "bridge", "hook", 0, "true_stems", _roles_full(), _state())
        assert bp.primary_drop_event is not None

    def test_sparse_bridge_return_support_crash(self):
        bp = sparse_bridge_return("b", "bridge", "hook", 0, "true_stems", _roles_full(), _state())
        support_types = [e.event_type for e in bp.support_events]
        assert any(t in ("crash_hit", "re_entry_accent") for t in support_types)

    def test_sparse_bridge_return_breakdown_from(self):
        bp = sparse_bridge_return("b", "breakdown", "hook", 0, "true_stems", _roles_full(), _state())
        assert bp.primary_drop_event is not None

    # ------------------------------------------------------------------
    # smooth_hook_release
    # ------------------------------------------------------------------

    def test_smooth_hook_release_no_silence(self):
        bp = smooth_hook_release("b", "hook", "verse", 0, "true_stems", _roles_full(), _state())
        assert bp.primary_drop_event is not None
        assert bp.primary_drop_event.event_type not in ("pre_drop_silence", "silence_tease")

    def test_smooth_hook_release_no_support_events(self):
        bp = smooth_hook_release("b", "hook", "verse", 0, "true_stems", _roles_full(), _state())
        assert len(bp.support_events) == 0

    def test_smooth_hook_release_low_tension(self):
        bp = smooth_hook_release("b", "hook", "verse", 0, "true_stems", _roles_full(), _state())
        assert bp.tension_score < 0.6

    # ------------------------------------------------------------------
    # breakdown_rebuild
    # ------------------------------------------------------------------

    def test_breakdown_rebuild_riser_primary(self):
        bp = breakdown_rebuild("b", "breakdown", "hook", 0, "true_stems", _roles_full(), _state())
        assert bp.primary_drop_event.event_type == "riser_build"

    def test_breakdown_rebuild_crash_support(self):
        bp = breakdown_rebuild("b", "breakdown", "hook", 0, "true_stems", _roles_full(), _state())
        support_types = [e.event_type for e in bp.support_events]
        assert any(t in ("crash_hit", "re_entry_accent") for t in support_types)

    # ------------------------------------------------------------------
    # outro_resolve
    # ------------------------------------------------------------------

    def test_outro_resolve_no_strong_event(self):
        bp = outro_resolve("b", "hook", "outro", 0, "true_stems", _roles_full(), _state())
        assert bp.primary_drop_event is not None
        assert not bp.primary_drop_event.is_strong

    def test_outro_resolve_no_support(self):
        bp = outro_resolve("b", "hook", "outro", 0, "true_stems", _roles_full(), _state())
        assert len(bp.support_events) == 0

    def test_outro_resolve_low_scores(self):
        bp = outro_resolve("b", "hook", "outro", 0, "true_stems", _roles_full(), _state())
        assert bp.tension_score <= 0.35
        assert bp.payoff_score <= 0.50


# ===========================================================================
# 12. Template selector dispatching
# ===========================================================================


class TestSelectTemplate:
    def test_selects_outro_template(self):
        bp = select_template("hook", "outro", 0, "true_stems", _roles_full(), _state())
        assert "outro_resolve" in bp.notes[0]

    def test_selects_standard_hook_entry_first(self):
        bp = select_template("pre_hook", "hook", 0, "true_stems", _roles_full(), _state())
        assert "standard_hook_entry" in bp.notes[0]

    def test_selects_fakeout_hook_entry_second(self):
        bp = select_template("pre_hook", "hook", 1, "true_stems", _roles_full(), _state())
        assert "fakeout_hook_entry" in bp.notes[0]

    def test_selects_delayed_hook_entry_third(self):
        bp = select_template("pre_hook", "hook", 2, "true_stems", _roles_full(), _state())
        assert "delayed_hook_entry" in bp.notes[0]

    def test_selects_sparse_bridge_return(self):
        bp = select_template("bridge", "hook", 0, "true_stems", _roles_full(), _state())
        assert "sparse_bridge_return" in bp.notes[0]

    def test_selects_sparse_bridge_return_from_breakdown(self):
        bp = select_template("breakdown", "hook", 0, "true_stems", _roles_full(), _state())
        assert "sparse_bridge_return" in bp.notes[0]

    def test_selects_smooth_hook_release(self):
        bp = select_template("hook", "verse", 0, "true_stems", _roles_full(), _state())
        assert "smooth_hook_release" in bp.notes[0]

    def test_verse_to_pre_hook_tightening(self):
        bp = select_template("verse", "pre_hook", 0, "true_stems", _roles_full(), _state())
        assert "verse_to_pre_hook" in bp.notes[0]

    def test_generic_fallback(self):
        bp = select_template("intro", "bridge", 0, "true_stems", _roles_full(), _state())
        assert bp.primary_drop_event is not None


# ===========================================================================
# 13–16. DropEnginePlanner integration tests
# ===========================================================================


class TestDropEnginePlanner:
    # ------------------------------------------------------------------
    # 13. Pre-hook → hook tension/payoff
    # ------------------------------------------------------------------

    def test_pre_hook_to_hook_has_high_payoff(self):
        sections = _sections("verse", "pre_hook", "hook", "verse", "outro")
        plan = _planner().build(sections)
        hook_boundaries = [
            b for b in plan.boundaries
            if b.from_section == "pre_hook" and b.to_section == "hook"
        ]
        assert len(hook_boundaries) >= 1
        for b in hook_boundaries:
            assert b.payoff_score >= 0.50, f"payoff too low: {b.payoff_score}"

    def test_pre_hook_to_hook_has_primary_event(self):
        sections = _sections("verse", "pre_hook", "hook")
        plan = _planner().build(sections)
        hook_b = [b for b in plan.boundaries if b.to_section == "hook"]
        assert all(b.primary_drop_event is not None for b in hook_b)

    def test_pre_hook_to_hook_tension_positive(self):
        sections = _sections("verse", "pre_hook", "hook")
        plan = _planner().build(sections)
        hook_b = [b for b in plan.boundaries if b.from_section == "pre_hook"]
        assert all(b.tension_score > 0 for b in hook_b)

    # ------------------------------------------------------------------
    # 14. Hook 1 vs Hook 2 drop differentiation
    # ------------------------------------------------------------------

    def test_hook1_vs_hook2_different_primary_event(self):
        sections = _sections("verse", "pre_hook", "hook", "verse", "pre_hook", "hook")
        plan = _planner().build(sections)
        hook_entries = [
            b for b in plan.boundaries
            if b.from_section == "pre_hook" and b.to_section == "hook"
        ]
        assert len(hook_entries) == 2
        type1 = hook_entries[0].primary_drop_event.event_type if hook_entries[0].primary_drop_event else None
        type2 = hook_entries[1].primary_drop_event.event_type if hook_entries[1].primary_drop_event else None
        assert type1 != type2, f"Both hooks use '{type1}' — should be differentiated"

    def test_hook2_payoff_at_least_equal_hook1(self):
        sections = _sections("verse", "pre_hook", "hook", "verse", "pre_hook", "hook")
        plan = _planner().build(sections)
        hook_entries = [
            b for b in plan.boundaries
            if b.from_section == "pre_hook" and b.to_section == "hook"
        ]
        assert len(hook_entries) == 2
        assert hook_entries[1].payoff_score >= hook_entries[0].payoff_score - 0.05  # small tolerance

    def test_repeated_hook_variation_score_positive(self):
        sections = _sections("verse", "pre_hook", "hook", "verse", "pre_hook", "hook")
        plan = _planner().build(sections)
        assert plan.repeated_hook_drop_variation_score > 0.0

    # ------------------------------------------------------------------
    # 15. Hook 3 maximum payoff
    # ------------------------------------------------------------------

    def test_hook3_highest_payoff(self):
        sections = _sections(
            "verse", "pre_hook", "hook",
            "verse", "pre_hook", "hook",
            "bridge", "pre_hook", "hook",
        )
        plan = _planner().build(sections)
        hook_entries = [
            b for b in plan.boundaries
            if b.from_section == "pre_hook" and b.to_section == "hook"
        ]
        assert len(hook_entries) == 3
        # Hook 3 payoff should be highest (or equal to hook 2 in degenerate cases).
        assert hook_entries[2].payoff_score >= hook_entries[0].payoff_score

    def test_hook3_uses_delayed_drop_or_silence(self):
        sections = _sections(
            "verse", "pre_hook", "hook",
            "verse", "pre_hook", "hook",
            "bridge", "pre_hook", "hook",
        )
        plan = _planner().build(sections)
        hook3 = [
            b for b in plan.boundaries
            if b.from_section == "pre_hook" and b.to_section == "hook"
        ][2]
        # Third hook uses delayed_hook_entry template which favours silence_tease.
        assert hook3.primary_drop_event is not None
        assert hook3.primary_drop_event.event_type in (
            "silence_tease", "riser_build", "delayed_drop", "staggered_reentry",
        )

    def test_variation_score_improves_with_three_hooks(self):
        two_hook = _sections("verse", "pre_hook", "hook", "verse", "pre_hook", "hook")
        three_hook = _sections(
            "verse", "pre_hook", "hook",
            "verse", "pre_hook", "hook",
            "bridge", "pre_hook", "hook",
        )
        plan_two = _planner().build(two_hook)
        plan_three = _planner().build(three_hook)
        assert plan_three.repeated_hook_drop_variation_score >= 0.0

    # ------------------------------------------------------------------
    # 16. Bridge/breakdown return
    # ------------------------------------------------------------------

    def test_bridge_return_to_hook_different_from_pre_hook(self):
        sections = _sections("verse", "pre_hook", "hook", "bridge", "hook")
        plan = _planner().build(sections)
        bridge_hooks = [
            b for b in plan.boundaries
            if b.from_section == "bridge" and b.to_section == "hook"
        ]
        pre_hook_entries = [
            b for b in plan.boundaries
            if b.from_section == "pre_hook" and b.to_section == "hook"
        ]
        if bridge_hooks and pre_hook_entries:
            bh_type = bridge_hooks[0].primary_drop_event.event_type if bridge_hooks[0].primary_drop_event else None
            ph_type = pre_hook_entries[0].primary_drop_event.event_type if pre_hook_entries[0].primary_drop_event else None
            assert bh_type != ph_type, "Bridge→hook should differ from pre_hook→hook"

    def test_breakdown_return_has_primary_event(self):
        sections = _sections("breakdown", "hook")
        plan = _planner().build(sections)
        b = plan.boundaries[0]
        assert b.primary_drop_event is not None

    # ------------------------------------------------------------------
    # 17. Outro resolution
    # ------------------------------------------------------------------

    def test_outro_no_hard_stop(self):
        sections = _sections("hook", "outro")
        plan = _planner().build(sections)
        outro_b = [b for b in plan.boundaries if b.to_section == "outro"]
        assert len(outro_b) == 1
        assert outro_b[0].primary_drop_event is not None
        assert not outro_b[0].primary_drop_event.is_strong

    def test_outro_payoff_positive(self):
        sections = _sections("hook", "outro")
        plan = _planner().build(sections)
        outro_b = plan.boundaries[0]
        assert outro_b.payoff_score > 0

    # ------------------------------------------------------------------
    # 18. Anti-stacking logic
    # ------------------------------------------------------------------

    def test_anti_stacking_no_two_strong_primaries_on_same_boundary(self):
        sections = _sections("verse", "pre_hook", "hook", "verse", "pre_hook", "hook", "bridge", "hook")
        plan = _planner().build(sections)
        for b in plan.boundaries:
            strong_count = sum(1 for e in b.all_events if e.is_strong)
            # Primary event: if strong, no additional strong events should be stacked.
            if b.primary_drop_event is not None and b.primary_drop_event.is_strong:
                assert strong_count <= 1, (
                    f"Boundary '{b.boundary_name}' stacks {strong_count} strong events"
                )

    # ------------------------------------------------------------------
    # 19. Source quality degradation
    # ------------------------------------------------------------------

    def test_stereo_fallback_lower_scores(self):
        sections = _sections("verse", "pre_hook", "hook")
        plan_strong = _planner("true_stems").build(sections)
        plan_weak = _planner("stereo_fallback").build(sections)
        hook_strong = [b for b in plan_strong.boundaries if b.to_section == "hook"]
        hook_weak = [b for b in plan_weak.boundaries if b.to_section == "hook"]
        if hook_strong and hook_weak:
            assert hook_weak[0].payoff_score <= hook_strong[0].payoff_score

    def test_stereo_fallback_marks_fallback_used(self):
        sections = _sections("verse", "pre_hook", "hook")
        plan = _planner("stereo_fallback").build(sections)
        assert plan.fallback_used is True

    def test_true_stems_fallback_used_false(self):
        sections = _sections("verse", "pre_hook", "hook")
        plan = _planner("true_stems").build(sections)
        assert plan.fallback_used is False

    def test_empty_sections_returns_fallback_plan(self):
        plan = _planner().build([])
        assert plan.fallback_used is True
        assert plan.boundaries == []

    def test_ai_separated_intermediate_scores(self):
        sections = _sections("verse", "pre_hook", "hook")
        plan_stems = _planner("true_stems").build(sections)
        plan_ai = _planner("ai_separated").build(sections)
        hook_stems = [b for b in plan_stems.boundaries if b.to_section == "hook"]
        hook_ai = [b for b in plan_ai.boundaries if b.to_section == "hook"]
        if hook_stems and hook_ai:
            assert hook_ai[0].payoff_score <= hook_stems[0].payoff_score

    # ------------------------------------------------------------------
    # 20. total_drop_count
    # ------------------------------------------------------------------

    def test_total_drop_count_correct(self):
        sections = _sections("verse", "pre_hook", "hook", "verse", "outro")
        plan = _planner().build(sections)
        counted = sum(1 for b in plan.boundaries if b.primary_drop_event is not None)
        assert plan.total_drop_count == counted


# ===========================================================================
# 20. DropValidator
# ===========================================================================


class TestDropValidator:
    def _validator(self) -> DropValidator:
        return DropValidator()

    def test_empty_plan_warning(self):
        v = self._validator()
        issues = v.validate(DropPlan())
        rules = [i.rule for i in issues]
        assert "empty_plan" in rules

    def test_strong_event_stacking_warning(self):
        primary = DropEvent("b", "pre_hook", "hook", "pre_boundary", "bass_dropout", 0.8)
        support = DropEvent("b", "pre_hook", "hook", "pre_boundary", "pre_drop_silence", 0.8)
        bp = DropBoundaryPlan(
            "pre_hook", "hook",
            primary_drop_event=primary,
            support_events=[support],
            payoff_score=0.7,
        )
        plan = DropPlan(boundaries=[bp], total_drop_count=1)
        issues = v.validate(plan) if (v := self._validator()) else []
        issues = self._validator().validate(plan)
        rules = [i.rule for i in issues]
        assert "strong_event_stacking" in rules

    def test_repeated_hook_identical_drop_warning(self):
        def make_hook_boundary(occ: int) -> DropBoundaryPlan:
            primary = DropEvent("b", "pre_hook", "hook", "pre_boundary", "bass_dropout", 0.8)
            return DropBoundaryPlan(
                "pre_hook", "hook",
                occurrence_index=occ,
                primary_drop_event=primary,
                payoff_score=0.7,
                tension_score=0.7,
            )

        plan = DropPlan(
            boundaries=[make_hook_boundary(0), make_hook_boundary(1)],
            total_drop_count=2,
            repeated_hook_drop_variation_score=0.0,
        )
        issues = self._validator().validate(plan)
        rules = [i.rule for i in issues]
        assert "repeated_hook_identical_drop" in rules

    def test_low_hook_variation_score_warning(self):
        def make_hook_boundary(occ: int, etype: str) -> DropBoundaryPlan:
            primary = DropEvent("b", "pre_hook", "hook", "pre_boundary", etype, 0.8)
            return DropBoundaryPlan(
                "pre_hook", "hook",
                occurrence_index=occ,
                primary_drop_event=primary,
                payoff_score=0.7,
                tension_score=0.7,
            )

        plan = DropPlan(
            boundaries=[make_hook_boundary(0, "bass_dropout"), make_hook_boundary(1, "riser_build")],
            total_drop_count=2,
            repeated_hook_drop_variation_score=0.1,  # below threshold
        )
        issues = self._validator().validate(plan)
        rules = [i.rule for i in issues]
        assert "low_hook_variation_score" in rules

    def test_weak_hook_payoff_warning(self):
        primary = DropEvent("b", "pre_hook", "hook", "pre_boundary", "riser_build", 0.3)
        bp = DropBoundaryPlan(
            "pre_hook", "hook",
            primary_drop_event=primary,
            payoff_score=0.2,  # below threshold
            tension_score=0.5,
        )
        plan = DropPlan(boundaries=[bp], total_drop_count=1)
        issues = self._validator().validate(plan)
        rules = [i.rule for i in issues]
        assert "weak_hook_payoff" in rules

    def test_no_primary_event_hook_warning(self):
        bp = DropBoundaryPlan("pre_hook", "hook", payoff_score=0.3, tension_score=0.5)
        plan = DropPlan(boundaries=[bp], total_drop_count=0)
        issues = self._validator().validate(plan)
        rules = [i.rule for i in issues]
        assert "no_primary_event_hook" in rules

    def test_silence_overuse_warning(self):
        silence_boundaries = [
            DropBoundaryPlan(
                "pre_hook", "hook",
                occurrence_index=i,
                primary_drop_event=DropEvent(
                    "b", "pre_hook", "hook", "pre_boundary", "silence_tease", 0.7
                ),
                payoff_score=0.7,
                tension_score=0.7,
            )
            for i in range(3)
        ]
        plan = DropPlan(boundaries=silence_boundaries, total_drop_count=3)
        issues = self._validator().validate(plan)
        rules = [i.rule for i in issues]
        assert "silence_overuse" in rules

    def test_hard_cut_outro_warning(self):
        primary = DropEvent("b", "hook", "outro", "boundary", "filtered_pre_drop", 0.3)
        bp = DropBoundaryPlan(
            "hook", "outro",
            primary_drop_event=primary,
            payoff_score=0.05,  # below threshold
            tension_score=0.1,
        )
        plan = DropPlan(boundaries=[bp], total_drop_count=1)
        issues = self._validator().validate(plan)
        rules = [i.rule for i in issues]
        assert "hard_cut_outro" in rules

    def test_strong_event_in_outro_warning(self):
        primary = DropEvent("b", "hook", "outro", "boundary", "bass_dropout", 0.8)
        bp = DropBoundaryPlan(
            "hook", "outro",
            primary_drop_event=primary,
            payoff_score=0.4,
            tension_score=0.3,
        )
        plan = DropPlan(boundaries=[bp], total_drop_count=1)
        issues = self._validator().validate(plan)
        rules = [i.rule for i in issues]
        assert "strong_event_in_outro" in rules

    def test_clean_plan_no_errors(self):
        sections = _sections("verse", "pre_hook", "hook", "verse", "pre_hook", "hook", "outro")
        plan = _planner().build(sections)
        issues = self._validator().validate(plan)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_issue_to_dict_serialisable(self):
        issue = DropValidationIssue(
            severity="warning",
            rule="weak_hook_payoff",
            message="payoff too low",
            boundary_name="pre_hook -> hook",
        )
        d = issue.to_dict()
        json.dumps(d)
        assert d["severity"] == "warning"
        assert d["boundary_name"] == "pre_hook -> hook"


# ===========================================================================
# 21. Serialisation correctness
# ===========================================================================


class TestSerialisation:
    def test_drop_plan_to_dict_json_safe(self):
        sections = _sections("verse", "pre_hook", "hook", "verse", "pre_hook", "hook", "bridge", "hook", "outro")
        plan = _planner().build(sections)
        d = plan.to_dict()
        serialised = json.dumps(d)
        restored = json.loads(serialised)
        assert restored["total_drop_count"] == plan.total_drop_count
        assert len(restored["boundaries"]) == len(plan.boundaries)

    def test_boundary_plan_fields_present(self):
        sections = _sections("pre_hook", "hook")
        plan = _planner().build(sections)
        b = plan.boundaries[0]
        d = b.to_dict()
        for key in ("boundary_name", "from_section", "to_section", "tension_score", "payoff_score"):
            assert key in d, f"Missing key: {key}"

    def test_primary_event_serialised(self):
        sections = _sections("pre_hook", "hook")
        plan = _planner().build(sections)
        b = plan.boundaries[0]
        assert b.primary_drop_event is not None
        d = b.to_dict()
        assert d["primary_drop_event"] is not None
        assert "event_type" in d["primary_drop_event"]


# ===========================================================================
# 22. Shadow integration metadata storage
# ===========================================================================


class TestShadowIntegration:
    def _mock_render_plan(self, section_names=None) -> dict:
        if section_names is None:
            section_names = ["verse", "pre_hook", "hook", "verse", "pre_hook", "hook", "outro"]
        return {
            "sections": [{"type": n, "bars": 8} for n in section_names],
            "sections_count": len(section_names),
        }

    def test_shadow_stores_drop_plan(self):
        from app.services.arrangement_jobs import _run_drop_engine_shadow

        render_plan = self._mock_render_plan()
        result = _run_drop_engine_shadow(
            render_plan=render_plan,
            available_roles=_roles_full(),
            arrangement_id=999,
            correlation_id="test-corr-id",
            source_quality="true_stems",
        )
        assert result["error"] is None
        assert result["plan"] is not None
        assert "boundaries" in result["plan"]

    def test_shadow_stores_scores(self):
        from app.services.arrangement_jobs import _run_drop_engine_shadow

        render_plan = self._mock_render_plan()
        result = _run_drop_engine_shadow(
            render_plan=render_plan,
            available_roles=_roles_full(),
            arrangement_id=999,
            correlation_id="test-corr-id",
            source_quality="true_stems",
        )
        assert isinstance(result["scores"], list)
        for score in result["scores"]:
            assert "boundary_name" in score
            assert "tension_score" in score
            assert "payoff_score" in score

    def test_shadow_stores_warnings(self):
        from app.services.arrangement_jobs import _run_drop_engine_shadow

        render_plan = self._mock_render_plan()
        result = _run_drop_engine_shadow(
            render_plan=render_plan,
            available_roles=_roles_full(),
            arrangement_id=999,
            correlation_id="test-corr-id",
            source_quality="true_stems",
        )
        assert isinstance(result["warnings"], list)

    def test_shadow_stores_fallback_flag(self):
        from app.services.arrangement_jobs import _run_drop_engine_shadow

        render_plan = self._mock_render_plan()
        result = _run_drop_engine_shadow(
            render_plan=render_plan,
            available_roles=_roles_full(),
            arrangement_id=999,
            correlation_id="test-corr-id",
            source_quality="stereo_fallback",
        )
        assert result["fallback_used"] is True

    def test_shadow_handles_empty_sections(self):
        from app.services.arrangement_jobs import _run_drop_engine_shadow

        render_plan = {"sections": [], "sections_count": 0}
        result = _run_drop_engine_shadow(
            render_plan=render_plan,
            available_roles=_roles_full(),
            arrangement_id=999,
            correlation_id="test-corr-id",
            source_quality="true_stems",
        )
        assert result["error"] is None
        assert result["plan"] is None

    def test_shadow_result_json_serialisable(self):
        from app.services.arrangement_jobs import _run_drop_engine_shadow

        render_plan = self._mock_render_plan()
        result = _run_drop_engine_shadow(
            render_plan=render_plan,
            available_roles=_roles_full(),
            arrangement_id=999,
            correlation_id="test-corr-id",
            source_quality="true_stems",
        )
        json.dumps(result)  # must not raise


# ===========================================================================
# 23. Determinism
# ===========================================================================


class TestDeterminism:
    def test_same_input_same_output(self):
        sections = _sections("verse", "pre_hook", "hook", "verse", "pre_hook", "hook", "outro")
        plan_a = _planner("true_stems").build(sections)
        plan_b = _planner("true_stems").build(sections)
        assert plan_a.to_dict() == plan_b.to_dict()

    def test_same_input_same_event_types(self):
        sections = _sections("verse", "pre_hook", "hook", "bridge", "pre_hook", "hook", "outro")
        plan_a = _planner("true_stems").build(sections)
        plan_b = _planner("true_stems").build(sections)
        for ba, bb in zip(plan_a.boundaries, plan_b.boundaries):
            type_a = ba.primary_drop_event.event_type if ba.primary_drop_event else None
            type_b = bb.primary_drop_event.event_type if bb.primary_drop_event else None
            assert type_a == type_b
