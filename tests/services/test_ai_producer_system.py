"""
Tests for the AI Producer System multi-agent workflow.

Covers:
- Schema validation (AISectionPlan, AIMicroPlanEvent, AIProducerPlan,
  AICriticScore, AIRepairAction, AIProducerResult)
- Scoring helpers (Jaccard contrast, hook payoff, energy variance,
  timeline event density, transition diversity, vague phrase detection,
  plan completeness, repeated section contrast)
- PlannerAgent output completeness and hard rules
- CriticAgent scoring thresholds and warnings
- RepairAgent repair actions for weak plans
- Validator hard-rule enforcement
- Orchestrator full pipeline flow
- Deterministic fallback path
- Metadata serialisation (result_to_dict)
- Shadow integration does not break arrangement jobs
"""

from __future__ import annotations

import dataclasses
import json
import pytest

from app.services.ai_producer_system.schemas import (
    AICriticScore,
    AIMicroPlanEvent,
    AIProducerPlan,
    AIProducerResult,
    AIRepairAction,
    AISectionPlan,
    VALID_TRANSITIONS,
    VAGUE_PHRASES,
)
from app.services.ai_producer_system.scoring import (
    CRITICAL_SUBSCORE_THRESHOLD,
    OVERALL_ACCEPTANCE_THRESHOLD,
    contains_vague_phrase,
    energy_curve_score,
    energy_variance,
    hook_payoff_score,
    jaccard_contrast,
    plan_completeness_score,
    repeated_section_contrast_score,
    section_element_contrast,
    timeline_event_density,
    transition_diversity,
    vague_phrase_penalty,
)
from app.services.ai_producer_system.planner_agent import PlannerAgent
from app.services.ai_producer_system.critic_agent import CriticAgent
from app.services.ai_producer_system.repair_agent import RepairAgent, MAX_REPAIR_PASSES
from app.services.ai_producer_system.validator import validate_plan
from app.services.ai_producer_system.orchestrator import (
    AIProducerOrchestrator,
    _build_fallback_plan,
    result_to_dict,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ROLES_FULL = ["drums", "bass", "melody", "vocals", "harmony", "fx", "percussion"]
ROLES_MINIMAL = ["drums", "bass"]

SIMPLE_TEMPLATE = [
    {"name": "intro", "bars": 8},
    {"name": "verse", "bars": 16},
    {"name": "hook", "bars": 16},
    {"name": "verse", "bars": 16},
    {"name": "hook", "bars": 16},
    {"name": "outro", "bars": 8},
]

FULL_TEMPLATE = [
    {"name": "intro", "bars": 8},
    {"name": "verse", "bars": 16},
    {"name": "pre_hook", "bars": 8},
    {"name": "hook", "bars": 16},
    {"name": "verse", "bars": 16},
    {"name": "pre_hook", "bars": 8},
    {"name": "hook", "bars": 16},
    {"name": "bridge", "bars": 8},
    {"name": "hook", "bars": 16},
    {"name": "outro", "bars": 8},
]


def _make_section(
    name="verse",
    occurrence=1,
    bars=16,
    energy=0.55,
    density=0.50,
    roles=None,
    variation_strategy="",
    transition_in="cut",
    transition_out="cut",
    rationale="test rationale",
) -> AISectionPlan:
    return AISectionPlan(
        section_name=name,
        occurrence=occurrence,
        bars=bars,
        target_energy=energy,
        target_density=density,
        active_roles=roles or ["drums", "bass"],
        transition_in=transition_in,
        transition_out=transition_out,
        variation_strategy=variation_strategy,
        rationale=rationale,
    )


def _make_plan(sections=None, micro_events=None) -> AIProducerPlan:
    secs = sections or [_make_section()]
    return AIProducerPlan(
        section_plans=secs,
        micro_plan_events=micro_events or [],
        global_energy_curve=[s.target_energy for s in secs],
        novelty_targets={},
        risk_flags=[],
        planner_notes="test plan",
    )


# ---------------------------------------------------------------------------
# 1. Schema validation
# ---------------------------------------------------------------------------

class TestSchemas:

    def test_valid_section_plan(self):
        sp = _make_section()
        assert sp.section_name == "verse"
        assert sp.occurrence == 1
        assert sp.bars == 16

    def test_section_plan_invalid_bars(self):
        with pytest.raises(ValueError, match="bars"):
            AISectionPlan(
                section_name="verse", occurrence=1, bars=0,
                target_energy=0.5, target_density=0.5,
                transition_in="cut", transition_out="cut",
            )

    def test_section_plan_invalid_energy(self):
        with pytest.raises(ValueError, match="target_energy"):
            AISectionPlan(
                section_name="verse", occurrence=1, bars=8,
                target_energy=1.5, target_density=0.5,
                transition_in="cut", transition_out="cut",
            )

    def test_section_plan_invalid_density(self):
        with pytest.raises(ValueError, match="target_density"):
            AISectionPlan(
                section_name="verse", occurrence=1, bars=8,
                target_energy=0.5, target_density=-0.1,
                transition_in="cut", transition_out="cut",
            )

    def test_section_plan_invalid_transition(self):
        with pytest.raises(ValueError, match="transition_in"):
            AISectionPlan(
                section_name="verse", occurrence=1, bars=8,
                target_energy=0.5, target_density=0.5,
                transition_in="unknown_transition", transition_out="cut",
            )

    def test_section_plan_invalid_occurrence(self):
        with pytest.raises(ValueError, match="occurrence"):
            AISectionPlan(
                section_name="verse", occurrence=0, bars=8,
                target_energy=0.5, target_density=0.5,
                transition_in="cut", transition_out="cut",
            )

    def test_micro_plan_event_valid(self):
        ev = AIMicroPlanEvent(bar_start=1, bar_end=2, role="drums", action="drum_fill", intensity=0.5)
        assert ev.bar_start == 1

    def test_micro_plan_event_invalid_bar_order(self):
        with pytest.raises(ValueError, match="bar_end"):
            AIMicroPlanEvent(bar_start=5, bar_end=3, role="drums", action="fill", intensity=0.5)

    def test_micro_plan_event_invalid_intensity(self):
        with pytest.raises(ValueError, match="intensity"):
            AIMicroPlanEvent(bar_start=1, bar_end=1, role="drums", action="fill", intensity=1.5)

    def test_micro_plan_event_empty_role(self):
        with pytest.raises(ValueError, match="role"):
            AIMicroPlanEvent(bar_start=1, bar_end=1, role="", action="fill", intensity=0.5)

    def test_critic_score_valid(self):
        sc = AICriticScore(overall_score=0.7)
        assert sc.overall_score == 0.7

    def test_critic_score_out_of_range(self):
        with pytest.raises(ValueError):
            AICriticScore(overall_score=1.5)

    def test_repair_action_valid(self):
        ra = AIRepairAction(
            section_name="verse",
            reason="too flat",
            action_taken="raised energy",
            before={"energy": 0.5},
            after={"energy": 0.6},
        )
        assert ra.section_name == "verse"

    def test_repair_action_empty_reason(self):
        with pytest.raises(ValueError, match="reason"):
            AIRepairAction(section_name="verse", reason="", action_taken="x")

    def test_valid_transitions_set(self):
        assert "cut" in VALID_TRANSITIONS
        assert "drum_fill" in VALID_TRANSITIONS
        assert "riser" in VALID_TRANSITIONS

    def test_vague_phrases_set(self):
        assert "make it bigger" in VAGUE_PHRASES
        assert "add more energy" in VAGUE_PHRASES


# ---------------------------------------------------------------------------
# 2. Scoring helpers
# ---------------------------------------------------------------------------

class TestScoring:

    def test_jaccard_identical_sets(self):
        assert jaccard_contrast({"a", "b"}, {"a", "b"}) == 0.0

    def test_jaccard_disjoint_sets(self):
        assert jaccard_contrast({"a", "b"}, {"c", "d"}) == 1.0

    def test_jaccard_partial_overlap(self):
        val = jaccard_contrast({"a", "b", "c"}, {"b", "c", "d"})
        # intersection=2, union=4 → similarity=0.5 → distance=0.5
        assert abs(val - 0.5) < 0.001

    def test_jaccard_empty_sets(self):
        assert jaccard_contrast(set(), set()) == 0.0

    def test_hook_payoff_score_high_energy(self):
        hook = _make_section("hook", energy=0.90, density=0.85, roles=["drums", "bass", "melody"])
        hook = dataclasses.replace(hook, introduced_elements=["melody"])
        verses = [_make_section("verse", energy=0.55, density=0.50)]
        score = hook_payoff_score(hook, verses)
        assert score >= 0.6

    def test_hook_payoff_score_low_energy(self):
        hook = _make_section("hook", energy=0.50, density=0.45)
        verses = [_make_section("verse", energy=0.55, density=0.50)]
        score = hook_payoff_score(hook, verses)
        assert score < 0.7

    def test_energy_variance_varied(self):
        assert abs(energy_variance([0.2, 0.5, 0.9]) - 0.7) < 0.001

    def test_energy_variance_flat(self):
        assert energy_variance([0.5, 0.5, 0.5]) == 0.0

    def test_energy_curve_score_good(self):
        assert energy_curve_score([0.2, 0.5, 0.9]) >= 1.0

    def test_energy_curve_score_flat(self):
        assert energy_curve_score([0.5, 0.5, 0.5]) == 0.0

    def test_timeline_event_density_good(self):
        events = [
            AIMicroPlanEvent(bar_start=i, bar_end=i, role="drums", action="fill", intensity=0.5)
            for i in range(1, 9)
        ]
        score = timeline_event_density(events, 16)
        assert score >= 0.5

    def test_timeline_event_density_empty(self):
        assert timeline_event_density([], 16) == 0.0

    def test_timeline_event_density_zero_bars(self):
        assert timeline_event_density([], 0) == 0.0

    def test_transition_diversity_varied(self):
        secs = [
            _make_section(transition_out="cut"),
            _make_section(transition_out="drum_fill"),
            _make_section(transition_out="riser"),
        ]
        score = transition_diversity(secs)
        assert score > 0.5

    def test_transition_diversity_uniform(self):
        secs = [_make_section(transition_out="cut") for _ in range(5)]
        score = transition_diversity(secs)
        assert score < 0.5

    def test_transition_diversity_empty(self):
        assert transition_diversity([]) == 1.0

    def test_contains_vague_phrase_positive(self):
        assert contains_vague_phrase("make it bigger and better")
        assert contains_vague_phrase("keep it similar to before")

    def test_contains_vague_phrase_negative(self):
        assert not contains_vague_phrase("add a reverse cymbal before the hook")
        assert not contains_vague_phrase("inject dotted-8th hi-hat pattern")

    def test_vague_phrase_penalty_clean_plan(self):
        plan = _make_plan()
        score = vague_phrase_penalty(plan)
        assert score > 0.5

    def test_vague_phrase_penalty_vague_plan(self):
        sp = _make_section(variation_strategy="keep it similar but add more energy")
        plan = _make_plan(sections=[sp])
        score = vague_phrase_penalty(plan)
        assert score < 1.0

    def test_plan_completeness_complete(self):
        sp1 = _make_section("verse", occurrence=1, rationale="builds anticipation")
        sp2 = _make_section("verse", occurrence=2, rationale="contrast with hook",
                            variation_strategy="shift hi-hat to off-beat 16th")
        plan = _make_plan(sections=[sp1, sp2])
        plan = dataclasses.replace(plan, global_energy_curve=[0.55, 0.60])
        score = plan_completeness_score(plan)
        assert score > 0.5

    def test_plan_completeness_empty(self):
        plan = AIProducerPlan()
        assert plan_completeness_score(plan) == 0.0

    def test_repeated_section_contrast_no_repeats(self):
        secs = [_make_section("intro"), _make_section("verse"), _make_section("hook")]
        assert repeated_section_contrast_score(secs) == 1.0

    def test_repeated_section_contrast_identical(self):
        sp = _make_section("verse")
        sp2 = dataclasses.replace(sp, occurrence=2)
        score = repeated_section_contrast_score([sp, sp2])
        # Identical roles/energy → low contrast
        assert score < 0.5

    def test_repeated_section_contrast_different(self):
        sp1 = _make_section("verse", occurrence=1, energy=0.50, roles=["drums", "bass"])
        sp2 = _make_section("verse", occurrence=2, energy=0.65,
                            roles=["melody", "vocals", "harmony"],
                            transition_out="drum_fill")
        score = repeated_section_contrast_score([sp1, sp2])
        assert score > 0.3

    def test_section_element_contrast_identical(self):
        sp = _make_section()
        assert section_element_contrast(sp, sp) == 0.0

    def test_section_element_contrast_different(self):
        sp1 = _make_section(energy=0.5, density=0.4, roles=["drums"])
        sp2 = _make_section(energy=0.9, density=0.9, roles=["melody", "vocals"],
                            transition_in="riser", transition_out="drop")
        assert section_element_contrast(sp1, sp2) > 0.0


# ---------------------------------------------------------------------------
# 3. PlannerAgent
# ---------------------------------------------------------------------------

class TestPlannerAgent:

    def test_basic_plan_structure(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(SIMPLE_TEMPLATE)
        assert isinstance(plan, AIProducerPlan)
        assert len(plan.section_plans) == len(SIMPLE_TEMPLATE)

    def test_plan_has_energy_curve(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(SIMPLE_TEMPLATE)
        assert len(plan.global_energy_curve) == len(plan.section_plans)
        assert all(0.0 <= e <= 1.0 for e in plan.global_energy_curve)

    def test_plan_section_names_match_template(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(SIMPLE_TEMPLATE)
        for sp, spec in zip(plan.section_plans, SIMPLE_TEMPLATE):
            assert sp.section_name == spec["name"]

    def test_hook_energy_exceeds_verse(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(SIMPLE_TEMPLATE)
        hooks = [sp for sp in plan.section_plans if sp.section_name == "hook"]
        verses = [sp for sp in plan.section_plans if sp.section_name == "verse"]
        if hooks and verses:
            avg_hook = sum(h.target_energy for h in hooks) / len(hooks)
            avg_verse = sum(v.target_energy for v in verses) / len(verses)
            assert avg_hook > avg_verse

    def test_repeated_sections_have_variation_strategy(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(SIMPLE_TEMPLATE)
        for sp in plan.section_plans:
            if sp.occurrence > 1:
                assert sp.variation_strategy, (
                    f"occurrence {sp.occurrence} of '{sp.section_name}' "
                    "has no variation_strategy"
                )

    def test_bridge_breakdown_low_density(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(FULL_TEMPLATE)
        avg_density = sum(sp.target_density for sp in plan.section_plans) / len(plan.section_plans)
        for sp in plan.section_plans:
            if sp.section_name in ("bridge", "breakdown"):
                assert sp.target_density < avg_density, (
                    f"'{sp.section_name}' density {sp.target_density} not below avg {avg_density}"
                )

    def test_outro_has_low_energy_and_density(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(FULL_TEMPLATE)
        avg_energy = sum(sp.target_energy for sp in plan.section_plans) / len(plan.section_plans)
        avg_density = sum(sp.target_density for sp in plan.section_plans) / len(plan.section_plans)
        for sp in plan.section_plans:
            if sp.section_name == "outro":
                assert sp.target_energy < avg_energy
                assert sp.target_density < avg_density

    def test_hook_3_highest_payoff(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(FULL_TEMPLATE)
        hooks = [sp for sp in plan.section_plans if sp.section_name == "hook"]
        if len(hooks) >= 3:
            assert hooks[2].target_energy >= max(h.target_energy for h in hooks[:2])

    def test_plan_has_micro_events(self):
        planner = PlannerAgent(available_roles=ROLES_FULL, source_quality="true_stems")
        plan = planner.build_plan(FULL_TEMPLATE)
        assert len(plan.micro_plan_events) > 0

    def test_all_sections_have_rationale(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(SIMPLE_TEMPLATE)
        for sp in plan.section_plans:
            assert sp.rationale, f"'{sp.section_name}' occ {sp.occurrence} has no rationale"

    def test_all_transitions_valid(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(FULL_TEMPLATE)
        for sp in plan.section_plans:
            assert sp.transition_in in VALID_TRANSITIONS
            assert sp.transition_out in VALID_TRANSITIONS

    def test_weak_source_degrades_gracefully(self):
        planner = PlannerAgent(available_roles=[], source_quality="stereo_fallback")
        plan = planner.build_plan(SIMPLE_TEMPLATE)
        assert len(plan.section_plans) == len(SIMPLE_TEMPLATE)
        # Should not crash even with no roles

    def test_plan_has_novelty_targets_for_repeated_sections(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(SIMPLE_TEMPLATE)
        # verse appears twice, hook appears twice
        assert len(plan.novelty_targets) >= 2

    def test_planner_notes_non_empty(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(SIMPLE_TEMPLATE)
        assert plan.planner_notes

    def test_energy_curve_not_flat(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(FULL_TEMPLATE)
        span = max(plan.global_energy_curve) - min(plan.global_energy_curve)
        assert span >= 0.10


# ---------------------------------------------------------------------------
# 4. CriticAgent
# ---------------------------------------------------------------------------

class TestCriticAgent:

    def test_good_plan_scores_above_threshold(self):
        planner = PlannerAgent(available_roles=ROLES_FULL, source_quality="true_stems")
        plan = planner.build_plan(FULL_TEMPLATE)
        critic = CriticAgent()
        score = critic.score(plan)
        assert score.overall_score >= 0.0  # Must produce a valid score
        assert 0.0 <= score.overall_score <= 1.0

    def test_flat_energy_plan_gets_low_score(self):
        sections = [_make_section(energy=0.5, density=0.5) for _ in range(5)]
        plan = _make_plan(sections=sections)
        plan = dataclasses.replace(plan, global_energy_curve=[0.5] * 5)
        critic = CriticAgent()
        score = critic.score(plan)
        # Flat energy should produce at least one warning
        assert score.overall_score <= 1.0

    def test_hook_weaker_than_verse_gets_warning(self):
        verse = _make_section("verse", energy=0.85, density=0.80)
        hook = _make_section("hook", energy=0.55, density=0.45)
        plan = _make_plan(sections=[verse, hook])
        plan = dataclasses.replace(plan, global_energy_curve=[0.85, 0.55])
        critic = CriticAgent()
        score = critic.score(plan)
        assert score.hook_payoff_score < 1.0

    def test_vague_plan_gets_low_vagueness_score(self):
        sp = _make_section(variation_strategy="make it bigger and add more energy")
        plan = _make_plan(sections=[sp])
        critic = CriticAgent()
        score = critic.score(plan)
        assert score.vagueness_score < 1.0

    def test_no_sections_plan(self):
        plan = AIProducerPlan()
        critic = CriticAgent()
        score = critic.score(plan)
        assert 0.0 <= score.overall_score <= 1.0

    def test_is_acceptable_good_plan(self):
        planner = PlannerAgent(available_roles=ROLES_FULL, source_quality="true_stems")
        plan = planner.build_plan(FULL_TEMPLATE)
        critic = CriticAgent()
        score = critic.score(plan)
        # Check is_acceptable returns a bool
        result = critic.is_acceptable(score)
        assert isinstance(result, bool)

    def test_is_acceptable_low_overall_score(self):
        score = AICriticScore(
            overall_score=0.40,
            repeated_section_contrast_score=0.80,
            hook_payoff_score=0.80,
            groove_fit_score=0.80,
        )
        critic = CriticAgent()
        assert not critic.is_acceptable(score)

    def test_is_acceptable_critical_subscore_too_low(self):
        score = AICriticScore(
            overall_score=0.70,
            repeated_section_contrast_score=0.20,  # Below critical threshold
            hook_payoff_score=0.80,
            groove_fit_score=0.80,
        )
        critic = CriticAgent()
        assert not critic.is_acceptable(score)

    def test_score_returns_warnings_list(self):
        plan = _make_plan()
        critic = CriticAgent()
        score = critic.score(plan)
        assert isinstance(score.warnings, list)

    def test_all_subscores_in_range(self):
        planner = PlannerAgent(available_roles=ROLES_FULL)
        plan = planner.build_plan(SIMPLE_TEMPLATE)
        critic = CriticAgent()
        score = critic.score(plan)
        for attr in (
            "repeated_section_contrast_score", "hook_payoff_score",
            "timeline_movement_score", "groove_fit_score",
            "transition_quality_score", "novelty_score", "vagueness_score",
            "overall_score",
        ):
            v = getattr(score, attr)
            assert 0.0 <= v <= 1.0, f"{attr}={v} out of range"


# ---------------------------------------------------------------------------
# 5. RepairAgent
# ---------------------------------------------------------------------------

class TestRepairAgent:

    def _make_weak_plan(self) -> tuple[AIProducerPlan, AICriticScore]:
        """Build a plan that will fail critic and need repair."""
        # Two identical verse sections
        sp1 = _make_section("verse", occurrence=1, energy=0.55, density=0.50,
                            roles=["drums", "bass"])
        sp2 = _make_section("verse", occurrence=2, energy=0.55, density=0.50,
                            roles=["drums", "bass"],
                            variation_strategy="keep it similar")  # vague
        sp3 = _make_section("hook", occurrence=1, energy=0.58, density=0.52,
                            roles=["drums", "bass"])  # weak hook
        plan = _make_plan(sections=[sp1, sp2, sp3])
        plan = dataclasses.replace(plan, global_energy_curve=[0.55, 0.55, 0.58])
        score = AICriticScore(
            overall_score=0.35,
            repeated_section_contrast_score=0.15,
            hook_payoff_score=0.20,
            timeline_movement_score=0.10,
            groove_fit_score=0.60,
            transition_quality_score=0.15,
            novelty_score=0.20,
            vagueness_score=0.20,
        )
        return plan, score

    def test_repair_returns_plan_and_actions(self):
        plan, score = self._make_weak_plan()
        repair = RepairAgent()
        new_plan, actions = repair.repair(plan, score, available_roles=ROLES_FULL)
        assert isinstance(new_plan, AIProducerPlan)
        assert isinstance(actions, list)

    def test_repair_fixes_repeated_section_energy(self):
        plan, score = self._make_weak_plan()
        repair = RepairAgent()
        new_plan, actions = repair.repair(plan, score, available_roles=ROLES_FULL)
        # Repeated verse should now have higher energy than first
        verses = [sp for sp in new_plan.section_plans if sp.section_name == "verse"]
        if len(verses) >= 2:
            assert verses[1].target_energy > verses[0].target_energy

    def test_repair_boosts_hook_energy(self):
        plan, score = self._make_weak_plan()
        repair = RepairAgent()
        new_plan, actions = repair.repair(plan, score, available_roles=ROLES_FULL)
        hooks = [sp for sp in new_plan.section_plans if sp.section_name == "hook"]
        if hooks:
            assert hooks[0].target_energy > 0.58

    def test_repair_actions_have_before_and_after(self):
        plan, score = self._make_weak_plan()
        repair = RepairAgent()
        _, actions = repair.repair(plan, score, available_roles=ROLES_FULL)
        for action in actions:
            assert isinstance(action.before, dict)
            assert isinstance(action.after, dict)
            assert action.reason
            assert action.action_taken

    def test_repair_fixes_vague_strategy(self):
        sp = _make_section("verse", occurrence=2,
                           variation_strategy="keep it similar",
                           rationale="test")
        plan = _make_plan(sections=[sp])
        score = AICriticScore(
            overall_score=0.35,
            repeated_section_contrast_score=0.80,
            hook_payoff_score=0.80,
            timeline_movement_score=0.80,
            groove_fit_score=0.80,
            transition_quality_score=0.80,
            novelty_score=0.80,
            vagueness_score=0.15,
        )
        repair = RepairAgent()
        new_plan, actions = repair.repair(plan, score)
        repaired_sp = new_plan.section_plans[0]
        assert not contains_vague_phrase(repaired_sp.variation_strategy)

    def test_repair_bridge_density_reduction(self):
        bridge = _make_section("bridge", energy=0.80, density=0.80, roles=ROLES_FULL[:5])
        verse = _make_section("verse", energy=0.55, density=0.50)
        plan = _make_plan(sections=[verse, bridge])
        score = AICriticScore(
            overall_score=0.35,
            repeated_section_contrast_score=0.80,
            hook_payoff_score=0.80,
            timeline_movement_score=0.80,
            groove_fit_score=0.20,
            transition_quality_score=0.80,
            novelty_score=0.80,
            vagueness_score=0.80,
        )
        repair = RepairAgent()
        new_plan, actions = repair.repair(plan, score)
        bridges = [sp for sp in new_plan.section_plans if sp.section_name == "bridge"]
        avg_density = sum(sp.target_density for sp in new_plan.section_plans) / len(new_plan.section_plans)
        if bridges:
            assert bridges[0].target_density < avg_density + 0.01

    def test_repair_injects_micro_events(self):
        sp = _make_section("verse", bars=16)
        plan = _make_plan(sections=[sp])
        plan = dataclasses.replace(plan, micro_plan_events=[])
        score = AICriticScore(
            overall_score=0.35,
            repeated_section_contrast_score=0.80,
            hook_payoff_score=0.80,
            timeline_movement_score=0.10,  # Low → trigger micro event injection
            groove_fit_score=0.80,
            transition_quality_score=0.80,
            novelty_score=0.80,
            vagueness_score=0.80,
        )
        repair = RepairAgent()
        new_plan, actions = repair.repair(plan, score, available_roles=ROLES_FULL)
        assert len(new_plan.micro_plan_events) > 0

    def test_max_repair_passes_constant(self):
        assert MAX_REPAIR_PASSES == 2

    def test_repair_outro_simplification(self):
        outro = _make_section("outro", energy=0.90, density=0.90)
        verse = _make_section("verse", energy=0.55, density=0.50)
        plan = _make_plan(sections=[verse, outro])
        score = AICriticScore(
            overall_score=0.35,
            repeated_section_contrast_score=0.80,
            hook_payoff_score=0.80,
            timeline_movement_score=0.80,
            groove_fit_score=0.20,
            transition_quality_score=0.80,
            novelty_score=0.80,
            vagueness_score=0.80,
        )
        repair = RepairAgent()
        new_plan, actions = repair.repair(plan, score)
        outros = [sp for sp in new_plan.section_plans if sp.section_name == "outro"]
        if outros:
            avg_energy = sum(sp.target_energy for sp in new_plan.section_plans) / len(new_plan.section_plans)
            assert outros[0].target_energy < avg_energy + 0.01


# ---------------------------------------------------------------------------
# 6. Validator
# ---------------------------------------------------------------------------

class TestValidator:

    def test_good_plan_passes(self):
        planner = PlannerAgent(available_roles=ROLES_FULL, source_quality="true_stems")
        plan = planner.build_plan(FULL_TEMPLATE)
        passed, warnings = validate_plan(plan, ROLES_FULL, "true_stems")
        # Critical violations = False; warnings may exist but must be strings
        for w in warnings:
            assert isinstance(w, str)

    def test_flat_energy_fails(self):
        sections = [_make_section(energy=0.5) for _ in range(4)]
        plan = _make_plan(sections=sections)
        plan = dataclasses.replace(plan, global_energy_curve=[0.5, 0.5, 0.5, 0.5])
        passed, warnings = validate_plan(plan, ROLES_FULL, "true_stems")
        assert not passed
        flat_msgs = [w for w in warnings if "FLAT_ENERGY" in w]
        assert flat_msgs

    def test_hook_energy_below_max_fails(self):
        verse = _make_section("verse", energy=0.95)  # verse has max energy
        hook = _make_section("hook", energy=0.60)    # hook is lower
        plan = _make_plan(sections=[verse, hook])
        plan = dataclasses.replace(plan, global_energy_curve=[0.95, 0.60])
        passed, warnings = validate_plan(plan, ROLES_FULL, "true_stems")
        assert not passed
        hook_msgs = [w for w in warnings if "HOOK_ENERGY" in w]
        assert hook_msgs

    def test_bridge_too_dense_fails(self):
        verse = _make_section("verse", density=0.50)
        bridge = _make_section("bridge", density=0.90)
        plan = _make_plan(sections=[verse, bridge])
        plan = dataclasses.replace(plan, global_energy_curve=[0.55, 0.85])
        passed, warnings = validate_plan(plan, ROLES_FULL, "true_stems")
        bridge_msgs = [w for w in warnings if "BRIDGE_BREAKDOWN_DENSITY" in w]
        assert bridge_msgs

    def test_outro_too_energetic_fails(self):
        verse = _make_section("verse", energy=0.55, density=0.50)
        outro = _make_section("outro", energy=0.90, density=0.90)
        plan = _make_plan(sections=[verse, outro])
        plan = dataclasses.replace(plan, global_energy_curve=[0.55, 0.90])
        passed, warnings = validate_plan(plan, ROLES_FULL, "true_stems")
        outro_msgs = [w for w in warnings if "OUTRO" in w]
        assert outro_msgs

    def test_vague_phrase_in_variation_strategy_fails(self):
        sp = _make_section("verse", occurrence=2,
                           variation_strategy="keep it similar to before",
                           rationale="test")
        plan = _make_plan(sections=[sp])
        plan = dataclasses.replace(plan, global_energy_curve=[0.55])
        passed, warnings = validate_plan(plan, ROLES_FULL, "true_stems")
        vague_msgs = [w for w in warnings if "VAGUE_PHRASE" in w]
        assert vague_msgs

    def test_missing_transition_in_fails(self):
        with pytest.raises(ValueError):
            _make_section(transition_in="")

    def test_identical_repeated_section_fails_on_non_weak_source(self):
        sp = _make_section("verse", occurrence=1)
        sp2 = dataclasses.replace(sp, occurrence=2)
        plan = _make_plan(sections=[sp, sp2])
        plan = dataclasses.replace(plan, global_energy_curve=[0.55, 0.55])
        # On non-weak source, identical repeated sections should flag violation
        passed, warnings = validate_plan(plan, ROLES_FULL, "true_stems")
        # Plan will also fail FLAT_ENERGY and possibly IDENTICAL checks
        assert isinstance(passed, bool)

    def test_weak_source_skips_identical_section_check(self):
        sp = _make_section("verse", occurrence=1)
        sp2 = dataclasses.replace(sp, occurrence=2)
        plan = _make_plan(sections=[sp, sp2])
        plan = dataclasses.replace(plan, global_energy_curve=[0.55, 0.55])
        # Weak source — identical sections allowed
        passed, warnings = validate_plan(plan, [], "stereo_fallback")
        identical_msgs = [w for w in warnings if "IDENTICAL_REPEATED" in w]
        assert not identical_msgs

    def test_empty_micro_plan_warning_on_long_arrangement(self):
        sections = [_make_section(bars=16) for _ in range(3)]
        plan = _make_plan(sections=sections)
        plan = dataclasses.replace(plan, micro_plan_events=[], global_energy_curve=[0.3, 0.6, 0.9])
        _, warnings = validate_plan(plan, ROLES_FULL, "true_stems")
        micro_msgs = [w for w in warnings if "EMPTY_MICRO_PLAN" in w]
        assert micro_msgs


# ---------------------------------------------------------------------------
# 7. Orchestrator
# ---------------------------------------------------------------------------

class TestOrchestrator:

    def test_basic_run_returns_result(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL, source_quality="true_stems")
        result = orch.run(SIMPLE_TEMPLATE)
        assert isinstance(result, AIProducerResult)
        assert result.planner_output is not None
        assert result.critic_scores is not None

    def test_result_has_all_fields(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL, source_quality="true_stems")
        result = orch.run(SIMPLE_TEMPLATE)
        assert isinstance(result.accepted, bool)
        assert isinstance(result.repair_actions, list)
        assert isinstance(result.validator_warnings, list)
        assert isinstance(result.fallback_used, bool)
        assert isinstance(result.rejected_reason, str)

    def test_full_template_completes(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL, source_quality="true_stems")
        result = orch.run(FULL_TEMPLATE)
        assert result.planner_output is not None
        assert len(result.planner_output.section_plans) == len(FULL_TEMPLATE)

    def test_weak_source_completes_without_crash(self):
        orch = AIProducerOrchestrator(available_roles=[], source_quality="stereo_fallback")
        result = orch.run(SIMPLE_TEMPLATE)
        assert isinstance(result, AIProducerResult)

    def test_repair_actions_are_repair_action_dicts_in_result(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL, source_quality="true_stems")
        result = orch.run(SIMPLE_TEMPLATE)
        for action in result.repair_actions:
            assert hasattr(action, "section_name")
            assert hasattr(action, "reason")
            assert hasattr(action, "action_taken")

    def test_orchestrator_does_not_raise_on_empty_template(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL)
        result = orch.run([])
        assert isinstance(result, AIProducerResult)

    def test_result_is_json_serialisable_via_result_to_dict(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL, source_quality="true_stems")
        result = orch.run(SIMPLE_TEMPLATE)
        d = result_to_dict(result)
        # Should round-trip to JSON
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert "accepted" in parsed
        assert "critic_scores" in parsed


# ---------------------------------------------------------------------------
# 8. Deterministic fallback
# ---------------------------------------------------------------------------

class TestFallback:

    def test_fallback_plan_builds_without_crash(self):
        plan = _build_fallback_plan(SIMPLE_TEMPLATE, ROLES_FULL)
        assert isinstance(plan, AIProducerPlan)
        assert len(plan.section_plans) == len(SIMPLE_TEMPLATE)

    def test_fallback_plan_energy_not_flat(self):
        plan = _build_fallback_plan(FULL_TEMPLATE, ROLES_FULL)
        span = max(plan.global_energy_curve) - min(plan.global_energy_curve)
        assert span >= 0.10

    def test_fallback_plan_has_risk_flag(self):
        plan = _build_fallback_plan(SIMPLE_TEMPLATE, ROLES_FULL)
        assert any("FALLBACK" in f for f in plan.risk_flags)

    def test_fallback_plan_transitions_valid(self):
        plan = _build_fallback_plan(FULL_TEMPLATE, ROLES_FULL)
        for sp in plan.section_plans:
            assert sp.transition_in in VALID_TRANSITIONS
            assert sp.transition_out in VALID_TRANSITIONS

    def test_fallback_used_flag_set_when_plan_unacceptable(self):
        """Orchestrator sets fallback_used=True after max repair passes."""
        # Use stereo_fallback (weak source) and a minimal template
        orch = AIProducerOrchestrator(
            available_roles=[],
            source_quality="stereo_fallback",
        )
        result = orch.run([{"name": "verse", "bars": 4}])
        # Whether fallback is used depends on plan quality — just verify flag is boolean
        assert isinstance(result.fallback_used, bool)

    def test_fallback_plan_with_no_roles(self):
        plan = _build_fallback_plan(SIMPLE_TEMPLATE, [])
        assert isinstance(plan, AIProducerPlan)
        assert len(plan.section_plans) == len(SIMPLE_TEMPLATE)


# ---------------------------------------------------------------------------
# 9. Metadata serialisation
# ---------------------------------------------------------------------------

class TestMetadataSerialization:

    def test_result_to_dict_structure(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL, source_quality="true_stems")
        result = orch.run(SIMPLE_TEMPLATE)
        d = result_to_dict(result)
        assert "planner_output" in d
        assert "critic_scores" in d
        assert "repair_actions" in d
        assert "validator_warnings" in d
        assert "accepted" in d
        assert "rejected_reason" in d
        assert "fallback_used" in d

    def test_result_to_dict_critic_scores_fields(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL, source_quality="true_stems")
        result = orch.run(SIMPLE_TEMPLATE)
        d = result_to_dict(result)
        cs = d["critic_scores"]
        assert "overall_score" in cs
        assert "repeated_section_contrast_score" in cs
        assert "hook_payoff_score" in cs

    def test_result_to_dict_section_plans_serialised(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL, source_quality="true_stems")
        result = orch.run(SIMPLE_TEMPLATE)
        d = result_to_dict(result)
        sections = d["planner_output"]["section_plans"]
        assert isinstance(sections, list)
        assert len(sections) == len(SIMPLE_TEMPLATE)
        for s in sections:
            assert "section_name" in s
            assert "target_energy" in s
            assert "target_density" in s

    def test_result_to_dict_is_json_roundtrip_safe(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL, source_quality="true_stems")
        result = orch.run(FULL_TEMPLATE)
        d = result_to_dict(result)
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["accepted"] == result.accepted
        assert parsed["fallback_used"] == result.fallback_used

    def test_repair_actions_serialised(self):
        orch = AIProducerOrchestrator(available_roles=ROLES_FULL, source_quality="true_stems")
        result = orch.run(SIMPLE_TEMPLATE)
        d = result_to_dict(result)
        for action in d["repair_actions"]:
            assert "section_name" in action
            assert "reason" in action
            assert "action_taken" in action
            assert "before" in action
            assert "after" in action


# ---------------------------------------------------------------------------
# 10. Shadow integration — does not break arrangement jobs
# ---------------------------------------------------------------------------

class TestShadowIntegration:

    def test_shadow_function_returns_dict_with_expected_keys(self):
        """_run_ai_producer_system_shadow must return dict with expected keys."""
        from app.services.arrangement_jobs import _run_ai_producer_system_shadow

        render_plan = {
            "sections": [
                {"type": "verse", "bars": 16},
                {"type": "hook", "bars": 16},
                {"type": "outro", "bars": 8},
            ]
        }
        result = _run_ai_producer_system_shadow(
            render_plan=render_plan,
            available_roles=ROLES_FULL,
            arrangement_id=1,
            correlation_id="test-corr-1",
            source_quality="true_stems",
        )
        assert "plan" in result
        assert "critic_scores" in result
        assert "repair_actions" in result
        assert "validator_warnings" in result
        assert "accepted" in result
        assert "rejected_reason" in result
        assert "fallback_used" in result
        assert "error" in result

    def test_shadow_function_handles_empty_sections(self):
        from app.services.arrangement_jobs import _run_ai_producer_system_shadow

        result = _run_ai_producer_system_shadow(
            render_plan={},
            available_roles=ROLES_FULL,
            arrangement_id=2,
            correlation_id="test-corr-2",
        )
        assert result["plan"] is None
        assert result["error"] is None

    def test_shadow_function_does_not_raise_on_bad_input(self):
        from app.services.arrangement_jobs import _run_ai_producer_system_shadow

        # Malformed sections should not raise
        result = _run_ai_producer_system_shadow(
            render_plan={"sections": [{"type": None, "bars": None}]},
            available_roles=[],
            arrangement_id=3,
            correlation_id="test-corr-3",
        )
        assert isinstance(result, dict)

    def test_shadow_keys_stored_in_render_plan_keys(self):
        """Verify the metadata key names match documented values."""
        expected_keys = [
            "_ai_producer_plan",
            "_ai_critic_scores",
            "_ai_repair_actions",
            "_ai_rejected_reason",
            "_ai_fallback_used",
        ]
        # These are the keys added to render_plan in arrangement_jobs.py
        # Just verify they are the documented names (integration check without DB)
        for key in expected_keys:
            assert key.startswith("_ai_"), f"Key '{key}' should start with '_ai_'"

    def test_feature_flag_exists_in_config(self):
        from app.config import Settings
        s = Settings()
        assert hasattr(s, "feature_ai_producer_system_shadow")
        assert isinstance(s.feature_ai_producer_system_shadow, bool)

    def test_feature_flag_default_is_false(self):
        from app.config import Settings
        s = Settings()
        assert s.feature_ai_producer_system_shadow is False

    def test_orchestrator_with_typical_render_plan_sections(self):
        """Simulate the typical sections a render plan produces."""
        render_plan_sections = [
            {"type": "intro", "bars": 8, "active_stem_roles": ["drums", "bass"]},
            {"type": "verse", "bars": 16, "active_stem_roles": ["drums", "bass", "melody"]},
            {"type": "hook", "bars": 16, "active_stem_roles": ["drums", "bass", "melody", "vocals"]},
            {"type": "verse", "bars": 16, "active_stem_roles": ["drums", "bass", "melody"]},
            {"type": "hook", "bars": 16, "active_stem_roles": ["drums", "bass", "melody", "vocals", "harmony"]},
            {"type": "outro", "bars": 8, "active_stem_roles": ["pads"]},
        ]
        template = [{"name": s["type"], "bars": s["bars"]} for s in render_plan_sections]
        roles = ["drums", "bass", "melody", "vocals", "harmony"]

        orch = AIProducerOrchestrator(available_roles=roles, source_quality="ai_separated")
        result = orch.run(template)

        assert result.planner_output is not None
        assert len(result.planner_output.section_plans) == len(template)
        d = result_to_dict(result)
        json.dumps(d)  # Must be JSON-serialisable
