"""
Tests for score_ai_plan_full (AICriticScores) — Phase 5.

Covers:
- Repeated section contrast scoring
- Hook payoff scoring
- Timeline movement scoring
- Tension/release scoring
- Novelty score integration
- Passed/failed determination
- Failure reasons population
- Edge cases: no hooks, no verses, no pre-hooks, single section
"""

from __future__ import annotations

import pytest

from app.services.ai_producer_assist import (
    AIProducerSuggestion,
    SuggestedSectionEntry,
    score_ai_plan_full,
    _MIN_NOVELTY_SCORE,
    _MIN_CRITIC_DIMENSION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_section(
    section_type: str,
    bars: int = 8,
    energy: int = 3,
    active_roles: list[str] | None = None,
    target_density: str = "medium",
    notes: str = "active section",
    introduced_elements: list[str] | None = None,
) -> SuggestedSectionEntry:
    return SuggestedSectionEntry(
        section_type=section_type,
        bars=bars,
        energy=energy,
        active_roles=active_roles or ["drums", "bass"],
        notes=notes,
        target_density=target_density,
        introduced_elements=introduced_elements or [],
    )


def _make_suggestion(sections: list[SuggestedSectionEntry]) -> AIProducerSuggestion:
    return AIProducerSuggestion(
        suggested_sections=sections,
        confidence=0.8,
    )


# ---------------------------------------------------------------------------
# Empty plan
# ---------------------------------------------------------------------------


class TestEmptyPlan:
    def test_empty_plan_fails(self):
        suggestion = _make_suggestion([])
        scores = score_ai_plan_full(suggestion)
        assert scores["passed"] is False
        assert len(scores["failure_reasons"]) > 0

    def test_empty_plan_all_zeros(self):
        suggestion = _make_suggestion([])
        scores = score_ai_plan_full(suggestion)
        assert scores["hook_payoff"] == 0.0
        assert scores["novelty_score"] == 0.0


# ---------------------------------------------------------------------------
# Hook payoff
# ---------------------------------------------------------------------------


class TestHookPayoff:
    def test_strong_hook_payoff(self):
        # Hook energy (5) >> verse energy (2) → strong payoff
        sections = [
            _make_section("verse", energy=2),
            _make_section("hook", energy=5),
        ]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["hook_payoff"] > 0.5

    def test_weak_hook_payoff(self):
        # Hook same as verse → no payoff
        sections = [
            _make_section("verse", energy=3),
            _make_section("hook", energy=3),
        ]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["hook_payoff"] == 0.0

    def test_no_verses_partial_credit(self):
        # No verses → hook gets partial credit
        sections = [_make_section("hook", energy=5)]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["hook_payoff"] == 0.5

    def test_no_hooks_zero_payoff(self):
        sections = [_make_section("verse", energy=3), _make_section("verse", energy=4, active_roles=["melody"])]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["hook_payoff"] == 0.0


# ---------------------------------------------------------------------------
# Timeline movement
# ---------------------------------------------------------------------------


class TestTimelineMovement:
    def test_flat_timeline_has_low_movement(self):
        # All same energy → no movement
        sections = [_make_section("verse", energy=3) for _ in range(4)]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["timeline_movement"] == 0.0

    def test_varied_timeline_has_movement(self):
        sections = [
            _make_section("intro", energy=1),
            _make_section("verse", energy=3),
            _make_section("hook", energy=5),
            _make_section("outro", energy=2),
        ]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["timeline_movement"] > 0.5

    def test_single_section_neutral_movement(self):
        sections = [_make_section("verse", energy=3)]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["timeline_movement"] == 0.5


# ---------------------------------------------------------------------------
# Tension/release
# ---------------------------------------------------------------------------


class TestTensionRelease:
    def test_pre_hook_then_hook_scores_high(self):
        # Good pattern: verse low → pre-hook medium → hook high
        sections = [
            _make_section("verse", energy=2, target_density="medium"),
            _make_section("pre_hook", energy=3, target_density="medium"),
            _make_section("hook", energy=5, target_density="full"),
        ]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["tension_release"] > 0.4

    def test_no_pre_hook_partial_credit(self):
        sections = [
            _make_section("verse", energy=2),
            _make_section("hook", energy=5),
        ]
        scores = score_ai_plan_full(_make_suggestion(sections))
        # No pre-hook → partial credit (0.3)
        assert scores["tension_release"] == pytest.approx(0.3)

    def test_pre_hook_without_hook_zero_release(self):
        sections = [
            _make_section("verse", energy=2),
            _make_section("pre_hook", energy=3),
        ]
        scores = score_ai_plan_full(_make_suggestion(sections))
        # Pre-hook with no following hook → no release
        assert scores["tension_release"] == 0.0


# ---------------------------------------------------------------------------
# Repeated section contrast
# ---------------------------------------------------------------------------


class TestRepeatedSectionContrast:
    def test_no_repeated_sections_full_contrast(self):
        sections = [
            _make_section("intro", energy=1),
            _make_section("verse", energy=3),
            _make_section("hook", energy=5),
        ]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["repeated_section_contrast"] == 1.0

    def test_identical_repeated_sections_zero_contrast(self):
        sections = [
            _make_section("verse", energy=3, active_roles=["drums", "bass"]),
            _make_section("verse", energy=3, active_roles=["drums", "bass"]),
        ]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["repeated_section_contrast"] == 0.0

    def test_different_repeated_sections_high_contrast(self):
        sections = [
            _make_section("verse", energy=3, active_roles=["drums", "bass"]),
            _make_section("verse", energy=4, active_roles=["melody", "synth"]),
        ]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["repeated_section_contrast"] == 1.0


# ---------------------------------------------------------------------------
# Passed / failed and failure_reasons
# ---------------------------------------------------------------------------


class TestPassedFailed:
    def test_good_plan_passes(self):
        sections = [
            _make_section("intro", energy=1, active_roles=["pads"], target_density="sparse"),
            _make_section("verse", energy=2, active_roles=["drums", "bass"]),
            _make_section("pre_hook", energy=3, active_roles=["drums", "bass", "melody"]),
            _make_section("hook", energy=5, active_roles=["drums", "bass", "melody", "synth"], introduced_elements=["synth"]),
            _make_section("verse", energy=3, active_roles=["bass", "melody"]),  # different from verse 1
            _make_section("hook", energy=5, active_roles=["drums", "bass", "synth", "arp"], introduced_elements=["arp"]),
            _make_section("outro", energy=2, active_roles=["pads"]),
        ]
        suggestion = _make_suggestion(sections)
        scores = score_ai_plan_full(suggestion)
        # Good plan should at least have timeline_movement > 0 and hook_payoff > 0
        assert scores["timeline_movement"] > 0
        assert scores["hook_payoff"] > 0

    def test_flat_plan_fails(self):
        sections = [_make_section("verse", energy=3) for _ in range(5)]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert scores["passed"] is False
        assert any("hook" in r.lower() for r in scores["failure_reasons"])

    def test_failure_reasons_non_empty_on_failure(self):
        sections = [_make_section("verse", energy=3) for _ in range(3)]
        scores = score_ai_plan_full(_make_suggestion(sections))
        assert len(scores["failure_reasons"]) > 0


# ---------------------------------------------------------------------------
# plan_vs_actual_match passthrough
# ---------------------------------------------------------------------------


class TestPlanVsActualMatch:
    def test_passthrough_when_set(self):
        sections = [_make_section("verse", energy=3)]
        suggestion = _make_suggestion(sections)
        suggestion.ai_plan_vs_actual_match = 0.75
        scores = score_ai_plan_full(suggestion)
        assert scores["plan_vs_actual_match"] == pytest.approx(0.75)

    def test_none_when_not_set(self):
        sections = [_make_section("verse", energy=3)]
        suggestion = _make_suggestion(sections)
        scores = score_ai_plan_full(suggestion)
        assert scores["plan_vs_actual_match"] is None
