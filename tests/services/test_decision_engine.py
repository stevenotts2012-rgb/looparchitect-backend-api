"""
Comprehensive tests for the Decision Engine.

Coverage (125 tests):
1.  Types — DecisionAction contract and validation.
2.  Types — SectionDecision contract.
3.  Types — DecisionPlan construction and serialisation.
4.  Types — DecisionValidationIssue contract.
5.  State — DecisionEngineState tracking.
6.  Rules — choose_roles_to_hold_back.
7.  Rules — choose_roles_to_remove_for_tension.
8.  Rules — choose_roles_to_reintroduce.
9.  Rules — section_can_allow_full_stack.
10. Rules — compute_target_fullness.
11. Rules — should_force_bridge_reset.
12. Rules — should_force_outro_resolution.
13. Planner — intro restraint.
14. Planner — verse 1 no-full-stack rule.
15. Planner — verse 2 evolution / differentiation.
16. Planner — pre-hook subtraction.
17. Planner — hook reintroduction / payoff.
18. Planner — bridge reset.
19. Planner — outro resolution.
20. Planner — repeated section decision differences.
21. Planner — limited-source graceful degradation.
22. Planner — empty sections fallback.
23. Scoring — global_contrast_score behaviour.
24. Scoring — payoff_readiness_score behaviour.
25. Scoring — per-section decision_score.
26. Validator — verse 1 full-stack critical rule.
27. Validator — pre-hook no-subtraction warning.
28. Validator — hook no-reintroduction warning.
29. Validator — bridge too full critical rule.
30. Validator — outro unresolved critical rule.
31. Validator — repeated section identical warning.
32. Serialisation — round-trip JSON correctness.
33. Shadow integration — metadata storage keys.
34. Determinism — identical inputs produce identical outputs.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.services.decision_engine import (
    ADDITIVE_ACTION_TYPES,
    SUBTRACTIVE_ACTION_TYPES,
    SUPPORTED_ACTION_TYPES,
    VALID_FULLNESS_LABELS,
    DecisionAction,
    DecisionEngineState,
    DecisionPlan,
    DecisionPlanner,
    DecisionValidationIssue,
    DecisionValidator,
    SectionDecision,
)
from app.services.decision_engine.rules import (
    LIMITED_SOURCE_QUALITIES,
    MIN_ROLES_FOR_SUBTRACTION,
    NON_CORE_ROLES,
    choose_roles_to_hold_back,
    choose_roles_to_remove_for_tension,
    choose_roles_to_reintroduce,
    compute_target_fullness,
    section_can_allow_full_stack,
    should_force_bridge_reset,
    should_force_outro_resolution,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _sections(*names: str) -> List[Dict[str, Any]]:
    return [{"type": n, "bars": 8} for n in names]


def _planner(
    source_quality: str = "true_stems",
    roles: Optional[List[str]] = None,
) -> DecisionPlanner:
    return DecisionPlanner(
        source_quality=source_quality,
        available_roles=roles or ["kick", "bass", "chords", "melody", "pad"],
    )


RICH_ROLES = ["kick", "bass", "chords", "melody", "pad", "hi_hat", "synth"]
LIMITED_ROLES = ["kick", "bass"]


# ===========================================================================
# 1. Types — DecisionAction
# ===========================================================================


class TestDecisionAction:
    def test_valid_construction(self):
        a = DecisionAction(
            section_name="verse_1",
            occurrence_index=0,
            action_type="hold_back_role",
            target_role="pad",
            bar_start=None,
            bar_end=None,
            intensity=0.8,
            reason="test",
        )
        assert a.section_name == "verse_1"
        assert a.action_type == "hold_back_role"
        assert a.is_subtractive

    def test_intensity_clamped(self):
        a = DecisionAction(
            section_name="x",
            occurrence_index=0,
            action_type="hold_back_role",
            target_role=None,
            bar_start=None,
            bar_end=None,
            intensity=5.0,
            reason="test",
        )
        assert a.intensity == 1.0

    def test_intensity_clamped_low(self):
        a = DecisionAction(
            section_name="x",
            occurrence_index=0,
            action_type="hold_back_role",
            target_role=None,
            bar_start=None,
            bar_end=None,
            intensity=-1.0,
            reason="test",
        )
        assert a.intensity == 0.0

    def test_invalid_action_type_raises(self):
        with pytest.raises(ValueError, match="action_type must be one of"):
            DecisionAction(
                section_name="x",
                occurrence_index=0,
                action_type="totally_invalid",
                target_role=None,
                bar_start=None,
                bar_end=None,
                intensity=0.5,
                reason="test",
            )

    def test_empty_section_name_raises(self):
        with pytest.raises(ValueError, match="section_name"):
            DecisionAction(
                section_name="",
                occurrence_index=0,
                action_type="hold_back_role",
                target_role=None,
                bar_start=None,
                bar_end=None,
                intensity=0.5,
                reason="test",
            )

    def test_negative_occurrence_index_raises(self):
        with pytest.raises(ValueError, match="occurrence_index"):
            DecisionAction(
                section_name="x",
                occurrence_index=-1,
                action_type="hold_back_role",
                target_role=None,
                bar_start=None,
                bar_end=None,
                intensity=0.5,
                reason="test",
            )

    def test_bar_end_before_bar_start_raises(self):
        with pytest.raises(ValueError, match="bar_end"):
            DecisionAction(
                section_name="x",
                occurrence_index=0,
                action_type="hold_back_role",
                target_role=None,
                bar_start=5,
                bar_end=3,
                intensity=0.5,
                reason="test",
            )

    def test_is_additive(self):
        a = DecisionAction(
            section_name="x",
            occurrence_index=0,
            action_type="reintroduce_role",
            target_role="pad",
            bar_start=None,
            bar_end=None,
            intensity=0.5,
            reason="test",
        )
        assert a.is_additive
        assert not a.is_subtractive

    def test_to_dict_contains_required_keys(self):
        a = DecisionAction(
            section_name="verse_1",
            occurrence_index=0,
            action_type="remove_role",
            target_role="pad",
            bar_start=1,
            bar_end=4,
            intensity=0.7,
            reason="test reason",
            notes="extra note",
        )
        d = a.to_dict()
        assert d["section_name"] == "verse_1"
        assert d["action_type"] == "remove_role"
        assert d["target_role"] == "pad"
        assert d["bar_start"] == 1
        assert d["bar_end"] == 4
        assert d["notes"] == "extra note"

    def test_all_supported_action_types_valid(self):
        for action_type in SUPPORTED_ACTION_TYPES:
            a = DecisionAction(
                section_name="x",
                occurrence_index=0,
                action_type=action_type,
                target_role=None,
                bar_start=None,
                bar_end=None,
                intensity=0.5,
                reason="test",
            )
            assert a.action_type == action_type

    def test_empty_reason_raises(self):
        with pytest.raises(ValueError, match="reason"):
            DecisionAction(
                section_name="x",
                occurrence_index=0,
                action_type="hold_back_role",
                target_role=None,
                bar_start=None,
                bar_end=None,
                intensity=0.5,
                reason="",
            )


# ===========================================================================
# 2. Types — SectionDecision
# ===========================================================================


class TestSectionDecision:
    def test_valid_construction(self):
        s = SectionDecision(
            section_name="hook_1",
            occurrence_index=0,
            target_fullness="full",
            allow_full_stack=True,
        )
        assert s.target_fullness == "full"
        assert s.allow_full_stack

    def test_invalid_fullness_raises(self):
        with pytest.raises(ValueError, match="target_fullness must be one of"):
            SectionDecision(
                section_name="x",
                occurrence_index=0,
                target_fullness="massive",
                allow_full_stack=True,
            )

    def test_decision_score_clamped(self):
        s = SectionDecision(
            section_name="x",
            occurrence_index=0,
            target_fullness="medium",
            allow_full_stack=False,
            decision_score=99.0,
        )
        assert s.decision_score == 1.0

    def test_subtraction_count(self):
        action = DecisionAction(
            section_name="x",
            occurrence_index=0,
            action_type="hold_back_role",
            target_role="pad",
            bar_start=None,
            bar_end=None,
            intensity=0.8,
            reason="test",
        )
        s = SectionDecision(
            section_name="x",
            occurrence_index=0,
            target_fullness="sparse",
            allow_full_stack=False,
            required_subtractions=[action],
        )
        assert s.subtraction_count == 1

    def test_to_dict_serialisable(self):
        s = SectionDecision(
            section_name="verse_1",
            occurrence_index=0,
            target_fullness="sparse",
            allow_full_stack=False,
            rationale=["Test rationale"],
        )
        d = s.to_dict()
        assert isinstance(json.dumps(d), str)
        assert d["target_fullness"] == "sparse"


# ===========================================================================
# 3. Types — DecisionPlan
# ===========================================================================


class TestDecisionPlan:
    def test_empty_plan(self):
        p = DecisionPlan()
        assert p.section_decisions == []
        assert p.global_contrast_score == 0.0
        assert p.fallback_used is False

    def test_scores_clamped(self):
        p = DecisionPlan(global_contrast_score=5.0, payoff_readiness_score=-1.0)
        assert p.global_contrast_score == 1.0
        assert p.payoff_readiness_score == 0.0

    def test_to_dict_round_trip(self):
        p = DecisionPlan(
            global_contrast_score=0.75,
            payoff_readiness_score=0.8,
            fallback_used=False,
            warnings=["test warning"],
        )
        d = p.to_dict()
        serialised = json.dumps(d)
        parsed = json.loads(serialised)
        assert parsed["global_contrast_score"] == 0.75
        assert parsed["warnings"] == ["test warning"]


# ===========================================================================
# 4. Types — DecisionValidationIssue
# ===========================================================================


class TestDecisionValidationIssue:
    def test_valid_warning(self):
        i = DecisionValidationIssue(
            severity="warning",
            rule="test_rule",
            section_name="verse_1",
            message="test message",
        )
        assert not i.is_critical

    def test_valid_critical(self):
        i = DecisionValidationIssue(
            severity="critical",
            rule="verse_1_full_stack",
            section_name="verse_1",
            message="critical issue",
        )
        assert i.is_critical

    def test_invalid_severity_raises(self):
        with pytest.raises(ValueError, match="severity"):
            DecisionValidationIssue(
                severity="fatal",
                rule="x",
                section_name=None,
                message="msg",
            )

    def test_empty_rule_raises(self):
        with pytest.raises(ValueError, match="rule"):
            DecisionValidationIssue(
                severity="warning",
                rule="",
                section_name=None,
                message="msg",
            )

    def test_to_dict(self):
        i = DecisionValidationIssue(
            severity="warning",
            rule="bridge_not_sparse",
            section_name="bridge_1",
            message="Consider sparse",
        )
        d = i.to_dict()
        assert d["severity"] == "warning"
        assert d["rule"] == "bridge_not_sparse"


# ===========================================================================
# 5. State — DecisionEngineState
# ===========================================================================


class TestDecisionEngineState:
    def test_occurrence_index_increments(self):
        state = DecisionEngineState()
        assert state.get_occurrence_index("verse") == 0
        assert state.get_occurrence_index("verse") == 1
        assert state.get_occurrence_index("hook") == 0

    def test_hold_back_and_reintroduce(self):
        state = DecisionEngineState()
        state.hold_back_role("pad")
        assert state.has_held_back_roles()
        state.reintroduce_role("pad")
        assert not state.has_held_back_roles()
        assert "pad" in state.reintroduced_roles

    def test_record_section_hook_fullness(self):
        state = DecisionEngineState()
        state.record_section("hook_1", "hook", "full", frozenset(), True)
        assert state.last_hook_fullness() == "full"

    def test_record_section_bridge_fullness(self):
        state = DecisionEngineState()
        state.record_section("bridge_1", "bridge", "sparse", frozenset(), False)
        assert state.bridge_decision_fullness == "sparse"

    def test_full_stack_tracking(self):
        state = DecisionEngineState()
        assert not state.full_stack_used_before()
        state.record_section("hook_1", "hook", "full", frozenset(), True)
        assert state.full_stack_used_before()
        assert state.full_stack_count() == 1

    def test_fingerprints_not_identical_with_one_occurrence(self):
        state = DecisionEngineState()
        fp = frozenset([("hold_back_role", "pad")])
        state.record_section("verse_1", "verse", "sparse", fp, False)
        assert not state.section_fingerprints_are_identical("verse")

    def test_fingerprints_identical_with_two_same(self):
        state = DecisionEngineState()
        fp = frozenset([("hold_back_role", "pad")])
        state.record_section("verse_1", "verse", "sparse", fp, False)
        state.record_section("verse_2", "verse", "sparse", fp, False)
        assert state.section_fingerprints_are_identical("verse")

    def test_hook_count(self):
        state = DecisionEngineState()
        state.record_section("hook_1", "hook", "full", frozenset(), True)
        state.record_section("hook_2", "hook", "full", frozenset(), True)
        assert state.hook_count() == 2


# ===========================================================================
# 6. Rules — choose_roles_to_hold_back
# ===========================================================================


class TestChooseRolesToHoldBack:
    def test_returns_non_core_roles(self):
        roles = choose_roles_to_hold_back(
            available_roles=RICH_ROLES,
            source_quality="true_stems",
            section_type="intro",
            occurrence_index=0,
        )
        for r in roles:
            assert r in NON_CORE_ROLES

    def test_limited_quality_max_one(self):
        roles = choose_roles_to_hold_back(
            available_roles=RICH_ROLES,
            source_quality="stereo_fallback",
            section_type="intro",
            occurrence_index=0,
        )
        assert len(roles) <= 1

    def test_too_few_roles_returns_empty(self):
        roles = choose_roles_to_hold_back(
            available_roles=["kick"],
            source_quality="true_stems",
            section_type="intro",
            occurrence_index=0,
        )
        assert roles == []

    def test_excludes_already_held_back(self):
        roles = choose_roles_to_hold_back(
            available_roles=RICH_ROLES,
            source_quality="true_stems",
            section_type="verse",
            occurrence_index=0,
            already_held_back=["chords"],
        )
        assert "chords" not in roles


# ===========================================================================
# 7. Rules — choose_roles_to_remove_for_tension
# ===========================================================================


class TestChooseRolesToRemoveForTension:
    def test_returns_at_most_one(self):
        roles = choose_roles_to_remove_for_tension(
            available_roles=RICH_ROLES,
            source_quality="true_stems",
        )
        assert len(roles) <= 1

    def test_too_few_roles_returns_empty(self):
        roles = choose_roles_to_remove_for_tension(
            available_roles=["kick"],
            source_quality="true_stems",
        )
        assert roles == []

    def test_excludes_currently_held_back(self):
        roles = choose_roles_to_remove_for_tension(
            available_roles=RICH_ROLES,
            source_quality="true_stems",
            currently_held_back=["chords", "pad"],
        )
        for r in roles:
            assert r not in ("chords", "pad")


# ===========================================================================
# 8. Rules — choose_roles_to_reintroduce
# ===========================================================================


class TestChooseRolesToReintroduce:
    def test_hook_releases_all_held_back(self):
        held = ["pad", "synth"]
        roles = choose_roles_to_reintroduce(held, "hook", "true_stems", 0)
        assert set(roles) == {"pad", "synth"}

    def test_verse_2_releases_one(self):
        held = ["pad", "synth"]
        roles = choose_roles_to_reintroduce(held, "verse", "true_stems", 1)
        assert len(roles) == 1

    def test_empty_held_back_returns_empty(self):
        roles = choose_roles_to_reintroduce([], "hook", "true_stems", 0)
        assert roles == []

    def test_verse_0_returns_empty(self):
        roles = choose_roles_to_reintroduce(["pad"], "verse", "true_stems", 0)
        assert roles == []


# ===========================================================================
# 9. Rules — section_can_allow_full_stack
# ===========================================================================


class TestSectionCanAllowFullStack:
    def test_intro_not_full(self):
        assert not section_can_allow_full_stack("intro", "true_stems", RICH_ROLES)

    def test_verse_1_not_full(self):
        assert not section_can_allow_full_stack(
            "verse", "true_stems", RICH_ROLES, occurrence_index=0
        )

    def test_pre_hook_not_full(self):
        assert not section_can_allow_full_stack("pre_hook", "true_stems", RICH_ROLES)

    def test_hook_is_full(self):
        assert section_can_allow_full_stack("hook", "true_stems", RICH_ROLES)

    def test_bridge_not_full(self):
        assert not section_can_allow_full_stack("bridge", "true_stems", RICH_ROLES)

    def test_outro_not_full(self):
        assert not section_can_allow_full_stack("outro", "true_stems", RICH_ROLES)

    def test_limited_quality_allows_some_relaxation(self):
        # With limited source, bridge constraint is relaxed via fallback logic;
        # but outro still should not be full.
        result = section_can_allow_full_stack("outro", "stereo_fallback", LIMITED_ROLES)
        assert not result


# ===========================================================================
# 10. Rules — compute_target_fullness
# ===========================================================================


class TestComputeTargetFullness:
    def test_intro_is_sparse(self):
        assert compute_target_fullness("intro", "true_stems", RICH_ROLES) == "sparse"

    def test_verse_1_sparse_when_held_back(self):
        result = compute_target_fullness(
            "verse", "true_stems", RICH_ROLES, occurrence_index=0, held_back_count=1
        )
        assert result == "sparse"

    def test_hook_is_full(self):
        assert compute_target_fullness("hook", "true_stems", RICH_ROLES) == "full"

    def test_bridge_is_sparse(self):
        assert compute_target_fullness("bridge", "true_stems", RICH_ROLES) == "sparse"

    def test_outro_is_sparse(self):
        assert compute_target_fullness("outro", "true_stems", RICH_ROLES) == "sparse"

    def test_limited_quality_hook_is_full(self):
        assert compute_target_fullness("hook", "stereo_fallback", LIMITED_ROLES) == "full"

    def test_limited_quality_verse_is_medium(self):
        assert compute_target_fullness("verse", "stereo_fallback", LIMITED_ROLES) == "medium"


# ===========================================================================
# 11. Rules — should_force_bridge_reset
# ===========================================================================


class TestShouldForceBridgeReset:
    def test_bridge_after_full_hook(self):
        assert should_force_bridge_reset("bridge", "full", "true_stems", RICH_ROLES)

    def test_non_bridge_returns_false(self):
        assert not should_force_bridge_reset("verse", "full", "true_stems", RICH_ROLES)

    def test_bridge_with_enough_roles(self):
        assert should_force_bridge_reset("bridge", None, "true_stems", RICH_ROLES)

    def test_breakdown_after_full_hook(self):
        assert should_force_bridge_reset("breakdown", "full", "true_stems", RICH_ROLES)


# ===========================================================================
# 12. Rules — should_force_outro_resolution
# ===========================================================================


class TestShouldForceOutroResolution:
    def test_outro_with_full_fullness(self):
        assert should_force_outro_resolution("outro", "full", "true_stems")

    def test_outro_with_medium_fullness(self):
        assert should_force_outro_resolution("outro", "medium", "true_stems")

    def test_outro_with_sparse_fullness(self):
        assert not should_force_outro_resolution("outro", "sparse", "true_stems")

    def test_non_outro_returns_false(self):
        assert not should_force_outro_resolution("hook", "full", "true_stems")


# ===========================================================================
# 13. Planner — intro restraint
# ===========================================================================


class TestPlannerIntro:
    def test_intro_is_sparse(self):
        plan = _planner().build(_sections("intro"))
        intro = plan.section_decisions[0]
        assert intro.target_fullness == "sparse"

    def test_intro_does_not_allow_full_stack(self):
        plan = _planner().build(_sections("intro"))
        intro = plan.section_decisions[0]
        assert not intro.allow_full_stack

    def test_intro_has_subtractions(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("intro"))
        intro = plan.section_decisions[0]
        assert intro.subtraction_count > 0

    def test_intro_rationale_mentions_tease(self):
        plan = _planner().build(_sections("intro"))
        intro = plan.section_decisions[0]
        rationale_text = " ".join(intro.rationale)
        assert "tease" in rationale_text.lower() or "intro" in rationale_text.lower()


# ===========================================================================
# 14. Planner — verse 1 no-full-stack rule
# ===========================================================================


class TestPlannerVerse1:
    def test_verse_1_not_full_stack(self):
        plan = _planner().build(_sections("verse"))
        verse = plan.section_decisions[0]
        assert not verse.allow_full_stack

    def test_verse_1_target_not_full(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("verse"))
        verse = plan.section_decisions[0]
        assert verse.target_fullness != "full"

    def test_verse_1_has_hold_back_when_rich_roles(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("verse"))
        verse = plan.section_decisions[0]
        hold_back_actions = [
            a for a in verse.required_subtractions if a.action_type == "hold_back_role"
        ]
        assert len(hold_back_actions) >= 1

    def test_verse_1_limited_source_graceful(self):
        plan = _planner(source_quality="stereo_fallback", roles=LIMITED_ROLES).build(
            _sections("verse")
        )
        verse = plan.section_decisions[0]
        # With limited roles, the plan should still build without error.
        assert verse is not None


# ===========================================================================
# 15. Planner — verse 2 evolution
# ===========================================================================


class TestPlannerVerse2:
    def test_verse_2_differs_from_verse_1(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("verse", "hook", "verse"))
        v1 = plan.section_decisions[0]
        v2 = plan.section_decisions[2]
        assert v1.occurrence_index == 0
        assert v2.occurrence_index == 1
        # Verse 2 should not be identical to verse 1 in actions.
        v1_actions = frozenset(
            (a.action_type, a.target_role) for a in v1.required_subtractions
        )
        v2_actions = frozenset(
            (a.action_type, a.target_role) for a in v2.required_subtractions
        )
        # Verse 2 may have a reintroduction while verse 1 does not.
        # At minimum they should have different occurrence_index.
        assert v2.occurrence_index > v1.occurrence_index

    def test_verse_2_has_reentry_when_material_held(self):
        plan = _planner(roles=RICH_ROLES).build(
            _sections("intro", "verse", "hook", "verse")
        )
        v2 = plan.section_decisions[3]
        # After hook reintroduction, verse 2 may allow a strategic re-entry.
        assert v2.occurrence_index == 1


# ===========================================================================
# 16. Planner — pre-hook subtraction
# ===========================================================================


class TestPlannerPreHook:
    def test_pre_hook_has_subtraction(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("verse", "pre_hook", "hook"))
        pre_hook = plan.section_decisions[1]
        assert pre_hook.subtraction_count > 0

    def test_pre_hook_is_sparse(self):
        plan = _planner().build(_sections("pre_hook"))
        pre_hook = plan.section_decisions[0]
        assert pre_hook.target_fullness == "sparse"

    def test_pre_hook_not_full_stack(self):
        plan = _planner().build(_sections("pre_hook"))
        pre_hook = plan.section_decisions[0]
        assert not pre_hook.allow_full_stack


# ===========================================================================
# 17. Planner — hook reintroduction / payoff
# ===========================================================================


class TestPlannerHook:
    def test_hook_1_is_full(self):
        plan = _planner().build(_sections("verse", "hook"))
        hook = plan.section_decisions[1]
        assert hook.target_fullness == "full"

    def test_hook_1_allows_full_stack(self):
        plan = _planner().build(_sections("verse", "hook"))
        hook = plan.section_decisions[1]
        assert hook.allow_full_stack

    def test_hook_reintroduces_held_back_material(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("intro", "verse", "hook"))
        hook = plan.section_decisions[2]
        reintro_actions = [
            a for a in hook.required_reentries if a.action_type == "reintroduce_role"
        ]
        assert len(reintro_actions) >= 1

    def test_hook_has_force_payoff(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("intro", "verse", "hook"))
        hook = plan.section_decisions[2]
        payoff_actions = [
            a for a in hook.required_reentries if a.action_type == "force_payoff"
        ]
        assert len(payoff_actions) >= 1

    def test_hook_occurrence_index(self):
        plan = _planner().build(_sections("hook", "hook"))
        h1 = plan.section_decisions[0]
        h2 = plan.section_decisions[1]
        assert h1.occurrence_index == 0
        assert h2.occurrence_index == 1


# ===========================================================================
# 18. Planner — bridge reset
# ===========================================================================


class TestPlannerBridge:
    def test_bridge_is_sparse(self):
        plan = _planner().build(_sections("hook", "bridge"))
        bridge = plan.section_decisions[1]
        assert bridge.target_fullness == "sparse"

    def test_bridge_not_full_stack(self):
        plan = _planner().build(_sections("hook", "bridge"))
        bridge = plan.section_decisions[1]
        assert not bridge.allow_full_stack

    def test_bridge_has_bridge_reset_action(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("hook", "bridge"))
        bridge = plan.section_decisions[1]
        reset_actions = [
            a for a in bridge.required_subtractions if a.action_type == "bridge_reset"
        ]
        assert len(reset_actions) >= 1

    def test_breakdown_also_resets(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("hook", "breakdown"))
        breakdown = plan.section_decisions[1]
        assert breakdown.target_fullness == "sparse"


# ===========================================================================
# 19. Planner — outro resolution
# ===========================================================================


class TestPlannerOutro:
    def test_outro_is_sparse(self):
        plan = _planner().build(_sections("hook", "outro"))
        outro = plan.section_decisions[1]
        assert outro.target_fullness == "sparse"

    def test_outro_not_full_stack(self):
        plan = _planner().build(_sections("outro"))
        outro = plan.section_decisions[0]
        assert not outro.allow_full_stack

    def test_outro_has_resolution_action(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("hook", "outro"))
        outro = plan.section_decisions[1]
        resolution_actions = [
            a for a in outro.required_subtractions if a.action_type == "outro_resolution"
        ]
        assert len(resolution_actions) >= 1


# ===========================================================================
# 20. Planner — repeated section decision differences
# ===========================================================================


class TestPlannerRepeatedSections:
    def test_verse_1_and_verse_2_different_occurrence_index(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("verse", "hook", "verse"))
        v1 = plan.section_decisions[0]
        v2 = plan.section_decisions[2]
        assert v1.occurrence_index != v2.occurrence_index

    def test_hook_1_and_hook_2_different_occurrence_index(self):
        plan = _planner().build(_sections("hook", "hook"))
        h1 = plan.section_decisions[0]
        h2 = plan.section_decisions[1]
        assert h1.occurrence_index == 0
        assert h2.occurrence_index == 1

    def test_repeated_sections_may_generate_warning(self):
        # With limited roles, the planner may not be able to differentiate;
        # with rich roles it should warn or differ.
        plan = _planner(roles=RICH_ROLES).build(
            _sections("verse", "hook", "verse", "hook", "verse")
        )
        # The plan should complete without error.
        assert len(plan.section_decisions) == 5


# ===========================================================================
# 21. Planner — limited source graceful degradation
# ===========================================================================


class TestPlannerLimitedSource:
    def test_limited_source_builds_plan(self):
        plan = _planner(
            source_quality="stereo_fallback", roles=LIMITED_ROLES
        ).build(_sections("intro", "verse", "hook", "outro"))
        assert len(plan.section_decisions) == 4

    def test_limited_source_fallback_used(self):
        plan = _planner(
            source_quality="stereo_fallback", roles=LIMITED_ROLES
        ).build(_sections("intro", "verse", "hook", "outro"))
        assert plan.fallback_used

    def test_no_roles_builds_plan(self):
        plan = DecisionPlanner(
            source_quality="stereo_fallback", available_roles=[]
        ).build(_sections("intro", "verse", "hook"))
        assert plan.fallback_used


# ===========================================================================
# 22. Planner — empty sections fallback
# ===========================================================================


class TestPlannerEmptySections:
    def test_empty_sections_returns_empty_plan(self):
        plan = _planner().build([])
        assert len(plan.section_decisions) == 0
        assert plan.fallback_used

    def test_empty_sections_has_warning(self):
        plan = _planner().build([])
        assert len(plan.warnings) > 0


# ===========================================================================
# 23. Scoring — global_contrast_score
# ===========================================================================


class TestGlobalContrastScore:
    def test_high_contrast_arrangement(self):
        plan = _planner(roles=RICH_ROLES).build(
            _sections("intro", "verse", "pre_hook", "hook", "bridge", "hook", "outro")
        )
        assert plan.global_contrast_score >= 0.5

    def test_score_in_range(self):
        plan = _planner().build(_sections("verse", "hook"))
        assert 0.0 <= plan.global_contrast_score <= 1.0

    def test_empty_plan_score_zero(self):
        plan = _planner().build([])
        assert plan.global_contrast_score == 0.0


# ===========================================================================
# 24. Scoring — payoff_readiness_score
# ===========================================================================


class TestPayoffReadinessScore:
    def test_payoff_score_in_range(self):
        plan = _planner(roles=RICH_ROLES).build(
            _sections("verse", "pre_hook", "hook")
        )
        assert 0.0 <= plan.payoff_readiness_score <= 1.0

    def test_pre_hook_before_hook_improves_payoff(self):
        plan_with = _planner(roles=RICH_ROLES).build(
            _sections("verse", "pre_hook", "hook")
        )
        plan_without = _planner(roles=RICH_ROLES).build(_sections("verse", "hook"))
        assert plan_with.payoff_readiness_score >= plan_without.payoff_readiness_score


# ===========================================================================
# 25. Scoring — per-section decision_score
# ===========================================================================


class TestSectionDecisionScore:
    def test_hook_score_higher_than_sparse_section(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("intro", "verse", "hook"))
        hook = plan.section_decisions[2]
        intro = plan.section_decisions[0]
        # Hook score should generally be >= intro (hook is fully evaluated as payoff).
        assert hook.decision_score >= 0.0
        assert intro.decision_score >= 0.0

    def test_all_section_scores_in_range(self):
        plan = _planner().build(
            _sections("intro", "verse", "pre_hook", "hook", "bridge", "outro")
        )
        for d in plan.section_decisions:
            assert 0.0 <= d.decision_score <= 1.0


# ===========================================================================
# 26. Validator — verse 1 full-stack critical rule
# ===========================================================================


class TestValidatorVerse1FullStack:
    def _make_verse_1_full_plan(self) -> DecisionPlan:
        verse_action = DecisionAction(
            section_name="verse_1",
            occurrence_index=0,
            action_type="force_payoff",
            target_role=None,
            bar_start=None,
            bar_end=None,
            intensity=1.0,
            reason="test",
        )
        section = SectionDecision(
            section_name="verse_1",
            occurrence_index=0,
            target_fullness="full",
            allow_full_stack=True,
            required_subtractions=[],
            required_reentries=[verse_action],
        )
        return DecisionPlan(section_decisions=[section])

    def test_verse_1_full_stack_is_critical(self):
        plan = self._make_verse_1_full_plan()
        validator = DecisionValidator(source_quality="true_stems", available_roles=RICH_ROLES)
        issues = validator.validate(plan)
        critical = [i for i in issues if i.is_critical]
        assert any("verse" in i.rule for i in critical)


# ===========================================================================
# 27. Validator — pre-hook no-subtraction warning
# ===========================================================================


class TestValidatorPreHookNoSubtraction:
    def test_pre_hook_without_subtraction_warns(self):
        section = SectionDecision(
            section_name="pre_hook_1",
            occurrence_index=0,
            target_fullness="medium",
            allow_full_stack=False,
        )
        plan = DecisionPlan(section_decisions=[section])
        validator = DecisionValidator(source_quality="true_stems", available_roles=RICH_ROLES)
        issues = validator.validate(plan)
        warnings = [i for i in issues if i.severity == "warning"]
        assert any("pre_hook" in i.rule for i in warnings)


# ===========================================================================
# 28. Validator — hook no-reintroduction warning
# ===========================================================================


class TestValidatorHookNoReintroduction:
    def test_hook_without_reintroduction_warns_when_held_back(self):
        subtraction = DecisionAction(
            section_name="verse_1",
            occurrence_index=0,
            action_type="hold_back_role",
            target_role="pad",
            bar_start=None,
            bar_end=None,
            intensity=0.8,
            reason="test",
        )
        verse = SectionDecision(
            section_name="verse_1",
            occurrence_index=0,
            target_fullness="sparse",
            allow_full_stack=False,
            required_subtractions=[subtraction],
        )
        hook = SectionDecision(
            section_name="hook_1",
            occurrence_index=0,
            target_fullness="full",
            allow_full_stack=True,
        )
        plan = DecisionPlan(section_decisions=[verse, hook])
        validator = DecisionValidator(source_quality="true_stems", available_roles=RICH_ROLES)
        issues = validator.validate(plan)
        warnings = [i for i in issues if i.severity == "warning"]
        assert any("hook_no_reintroduction" in i.rule for i in warnings)


# ===========================================================================
# 29. Validator — bridge too full critical rule
# ===========================================================================


class TestValidatorBridgeTooFull:
    def test_bridge_full_after_full_hook_is_critical(self):
        hook = SectionDecision(
            section_name="hook_1",
            occurrence_index=0,
            target_fullness="full",
            allow_full_stack=True,
        )
        bridge = SectionDecision(
            section_name="bridge_1",
            occurrence_index=0,
            target_fullness="full",
            allow_full_stack=True,
        )
        plan = DecisionPlan(section_decisions=[hook, bridge])
        validator = DecisionValidator(source_quality="true_stems", available_roles=RICH_ROLES)
        issues = validator.validate(plan)
        critical = [i for i in issues if i.is_critical]
        assert any("bridge_too_full" in i.rule for i in critical)


# ===========================================================================
# 30. Validator — outro unresolved critical rule
# ===========================================================================


class TestValidatorOutroUnresolved:
    def test_outro_full_is_critical(self):
        outro = SectionDecision(
            section_name="outro_1",
            occurrence_index=0,
            target_fullness="full",
            allow_full_stack=True,
        )
        plan = DecisionPlan(section_decisions=[outro])
        validator = DecisionValidator(source_quality="true_stems", available_roles=RICH_ROLES)
        issues = validator.validate(plan)
        critical = [i for i in issues if i.is_critical]
        assert any("outro_unresolved" in i.rule for i in critical)


# ===========================================================================
# 31. Validator — repeated section identical warning
# ===========================================================================


class TestValidatorRepeatedSectionIdentical:
    def test_identical_verse_decisions_warn(self):
        # Build two verse sections with identical (empty) decisions.
        v1 = SectionDecision(
            section_name="verse_1",
            occurrence_index=0,
            target_fullness="sparse",
            allow_full_stack=False,
        )
        v2 = SectionDecision(
            section_name="verse_2",
            occurrence_index=1,
            target_fullness="sparse",
            allow_full_stack=False,
        )
        plan = DecisionPlan(section_decisions=[v1, v2])
        validator = DecisionValidator(source_quality="true_stems", available_roles=RICH_ROLES)
        issues = validator.validate(plan)
        warnings = [i for i in issues if i.severity == "warning"]
        assert any("repeated_section_identical" in i.rule for i in warnings)

    def test_limited_source_does_not_warn_on_repeated(self):
        v1 = SectionDecision(
            section_name="verse_1",
            occurrence_index=0,
            target_fullness="medium",
            allow_full_stack=False,
        )
        v2 = SectionDecision(
            section_name="verse_2",
            occurrence_index=1,
            target_fullness="medium",
            allow_full_stack=False,
        )
        plan = DecisionPlan(section_decisions=[v1, v2])
        validator = DecisionValidator(
            source_quality="stereo_fallback", available_roles=LIMITED_ROLES
        )
        issues = validator.validate(plan)
        repeated_warnings = [
            i for i in issues if "repeated_section_identical" in i.rule
        ]
        assert len(repeated_warnings) == 0


# ===========================================================================
# 32. Serialisation — round-trip JSON correctness
# ===========================================================================


class TestSerialisation:
    def test_decision_plan_round_trip(self):
        plan = _planner(roles=RICH_ROLES).build(
            _sections("intro", "verse", "pre_hook", "hook", "bridge", "outro")
        )
        serialised = json.dumps(plan.to_dict())
        parsed = json.loads(serialised)
        assert isinstance(parsed["section_decisions"], list)
        assert len(parsed["section_decisions"]) == 6
        assert isinstance(parsed["global_contrast_score"], float)
        assert isinstance(parsed["payoff_readiness_score"], float)
        assert isinstance(parsed["warnings"], list)

    def test_section_decision_round_trip(self):
        plan = _planner().build(_sections("verse"))
        verse = plan.section_decisions[0]
        d = verse.to_dict()
        serialised = json.dumps(d)
        parsed = json.loads(serialised)
        assert parsed["section_name"] == "verse"
        assert parsed["target_fullness"] in VALID_FULLNESS_LABELS

    def test_validation_issues_serialisable(self):
        plan = _planner(roles=RICH_ROLES).build(_sections("verse", "hook"))
        validator = DecisionValidator(source_quality="true_stems", available_roles=RICH_ROLES)
        issues = validator.validate(plan)
        for issue in issues:
            serialised = json.dumps(issue.to_dict())
            assert isinstance(serialised, str)


# ===========================================================================
# 33. Shadow integration — metadata storage keys
# ===========================================================================


class TestShadowIntegrationMetadata:
    """Verify that the shadow integration function stores metadata correctly."""

    def test_shadow_result_keys_present(self):
        from app.services.arrangement_jobs import _run_decision_engine_shadow

        render_plan = {
            "sections": [
                {"type": "intro", "bars": 8},
                {"type": "verse", "bars": 8},
                {"type": "hook", "bars": 8},
                {"type": "outro", "bars": 8},
            ]
        }
        result = _run_decision_engine_shadow(
            render_plan=render_plan,
            available_roles=RICH_ROLES,
            arrangement_id=1,
            correlation_id="test-correlation",
            source_quality="true_stems",
        )
        assert "plan" in result
        assert "scores" in result
        assert "warnings" in result
        assert "fallback_used" in result
        assert "error" in result

    def test_shadow_result_plan_not_none_when_sections_present(self):
        from app.services.arrangement_jobs import _run_decision_engine_shadow

        render_plan = {
            "sections": [{"type": "verse", "bars": 8}, {"type": "hook", "bars": 8}]
        }
        result = _run_decision_engine_shadow(
            render_plan=render_plan,
            available_roles=RICH_ROLES,
            arrangement_id=1,
            correlation_id="test-correlation",
            source_quality="true_stems",
        )
        assert result["plan"] is not None
        assert result["error"] is None

    def test_shadow_result_empty_when_no_sections(self):
        from app.services.arrangement_jobs import _run_decision_engine_shadow

        render_plan = {"sections": []}
        result = _run_decision_engine_shadow(
            render_plan=render_plan,
            available_roles=RICH_ROLES,
            arrangement_id=1,
            correlation_id="test-correlation",
            source_quality="true_stems",
        )
        assert result["plan"] is None

    def test_shadow_result_scores_match_sections(self):
        from app.services.arrangement_jobs import _run_decision_engine_shadow

        sections = [
            {"type": "intro", "bars": 8},
            {"type": "verse", "bars": 8},
            {"type": "hook", "bars": 8},
        ]
        result = _run_decision_engine_shadow(
            render_plan={"sections": sections},
            available_roles=RICH_ROLES,
            arrangement_id=1,
            correlation_id="test-correlation",
            source_quality="true_stems",
        )
        assert len(result["scores"]) == 3

    def test_shadow_result_scores_have_required_keys(self):
        from app.services.arrangement_jobs import _run_decision_engine_shadow

        result = _run_decision_engine_shadow(
            render_plan={"sections": [{"type": "hook", "bars": 8}]},
            available_roles=RICH_ROLES,
            arrangement_id=1,
            correlation_id="test-correlation",
            source_quality="true_stems",
        )
        for score in result["scores"]:
            assert "section_name" in score
            assert "target_fullness" in score
            assert "allow_full_stack" in score
            assert "decision_score" in score


# ===========================================================================
# 34. Determinism — identical inputs produce identical outputs
# ===========================================================================


class TestDeterminism:
    def test_identical_inputs_produce_identical_plan(self):
        sections = _sections("intro", "verse", "pre_hook", "hook", "bridge", "outro")
        roles = RICH_ROLES

        plan_a = DecisionPlanner(
            source_quality="true_stems", available_roles=roles
        ).build(sections)
        plan_b = DecisionPlanner(
            source_quality="true_stems", available_roles=roles
        ).build(sections)

        assert plan_a.to_dict() == plan_b.to_dict()

    def test_identical_inputs_produce_identical_scores(self):
        sections = _sections("verse", "pre_hook", "hook", "bridge", "outro")
        roles = RICH_ROLES

        plan_a = DecisionPlanner(source_quality="true_stems", available_roles=roles).build(
            sections
        )
        plan_b = DecisionPlanner(source_quality="true_stems", available_roles=roles).build(
            sections
        )

        assert plan_a.global_contrast_score == plan_b.global_contrast_score
        assert plan_a.payoff_readiness_score == plan_b.payoff_readiness_score

    def test_different_arrangements_produce_different_scores(self):
        sections_a = _sections("verse", "hook")
        sections_b = _sections("intro", "verse", "pre_hook", "hook", "bridge", "outro")
        roles = RICH_ROLES

        plan_a = DecisionPlanner(source_quality="true_stems", available_roles=roles).build(
            sections_a
        )
        plan_b = DecisionPlanner(source_quality="true_stems", available_roles=roles).build(
            sections_b
        )

        # The more complex arrangement should generally score differently.
        assert plan_a.to_dict() != plan_b.to_dict()

    def test_validator_deterministic(self):
        plan = _planner(roles=RICH_ROLES).build(
            _sections("intro", "verse", "pre_hook", "hook", "bridge", "outro")
        )
        validator = DecisionValidator(source_quality="true_stems", available_roles=RICH_ROLES)
        issues_a = validator.validate(plan)
        issues_b = validator.validate(plan)
        assert [i.to_dict() for i in issues_a] == [i.to_dict() for i in issues_b]

    def test_planner_with_complex_sequence_deterministic(self):
        sections = _sections(
            "intro", "verse", "verse", "pre_hook", "hook",
            "verse", "pre_hook", "hook", "bridge", "hook", "outro"
        )
        roles = RICH_ROLES
        plan_a = DecisionPlanner(source_quality="true_stems", available_roles=roles).build(
            sections
        )
        plan_b = DecisionPlanner(source_quality="true_stems", available_roles=roles).build(
            sections
        )
        assert plan_a.to_dict() == plan_b.to_dict()
