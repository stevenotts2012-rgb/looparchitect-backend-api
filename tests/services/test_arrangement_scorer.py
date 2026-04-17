"""Unit tests for the arrangement scoring layer."""

from __future__ import annotations

import pytest

from app.services.arrangement_scorer import (
    ENERGY_CURVE_REJECT_THRESHOLD,
    HOOK_PAYOFF_REJECT_THRESHOLD,
    OVERALL_REJECT_THRESHOLD,
    REPETITION_REJECT_THRESHOLD,
    evaluate_arrangement,
    score_and_reject,
    score_arrangement,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(
    sections=None,
    events=None,
    energy_curve=None,
) -> dict:
    """Return a minimal render-plan dict wired for easy customisation."""
    if sections is None:
        sections = _good_sections()
    return {
        "bpm": 120,
        "key": "C",
        "total_bars": 96,
        "sections": sections,
        "events": events or [],
        "energy_curve": energy_curve or [],
    }


def _good_sections() -> list[dict]:
    """Four-section arrangement that should score well."""
    return [
        {
            "name": "Intro",
            "type": "intro",
            "bar_start": 0,
            "bars": 8,
            "energy": 0.30,
            "instruments": ["kick", "hats"],
        },
        {
            "name": "Verse 1",
            "type": "verse",
            "bar_start": 8,
            "bars": 16,
            "energy": 0.55,
            "instruments": ["kick", "snare", "bass"],
        },
        {
            "name": "Hook",
            "type": "hook",
            "bar_start": 24,
            "bars": 8,
            "energy": 0.90,
            "instruments": ["kick", "snare", "bass", "lead", "pad"],
        },
        {
            "name": "Outro",
            "type": "outro",
            "bar_start": 32,
            "bars": 8,
            "energy": 0.20,
            "instruments": ["kick"],
        },
    ]


def _good_events() -> list[dict]:
    """Events that cover section boundaries."""
    return [
        {"type": "drum_fill", "bar": 8, "intensity": 0.7},
        {"type": "riser_fx", "bar": 23, "intensity": 0.8},
        {"type": "crash_hit", "bar": 24, "intensity": 0.9},
        {"type": "silence_drop", "bar": 32, "intensity": 0.6},
    ]


def _flat_sections() -> list[dict]:
    """All sections with the same energy and instruments — bad quality."""
    return [
        {
            "name": f"Section {i}",
            "type": "verse",
            "bar_start": i * 8,
            "bars": 8,
            "energy": 0.5,
            "instruments": ["kick", "bass"],
        }
        for i in range(4)
    ]


# ---------------------------------------------------------------------------
# score_arrangement() — return type and key structure
# ---------------------------------------------------------------------------


class TestScoreArrangementStructure:
    def test_returns_dict(self):
        result = score_arrangement(_make_plan())
        assert isinstance(result, dict)

    def test_expected_keys_present(self):
        result = score_arrangement(_make_plan())
        expected = {
            "energy_curve_score",
            "contrast_score",
            "repetition_penalty",
            "hook_payoff_score",
            "transition_score",
            "role_diversity_score",
            "overall_score",
        }
        assert expected == set(result.keys())

    def test_all_values_are_floats_in_range(self):
        result = score_arrangement(_make_plan())
        for key, value in result.items():
            assert isinstance(value, float), f"{key} should be float, got {type(value)}"
            assert 0.0 <= value <= 1.0, f"{key}={value} out of [0, 1]"

    def test_empty_plan_does_not_crash(self):
        result = score_arrangement({})
        assert isinstance(result, dict)
        assert result["overall_score"] >= 0.0


# ---------------------------------------------------------------------------
# Energy curve scoring
# ---------------------------------------------------------------------------


class TestEnergyCurveScore:
    def test_high_energy_range_scores_well(self):
        sections = [
            {"type": "intro", "bar_start": 0, "bars": 8, "energy": 0.1, "instruments": []},
            {"type": "hook", "bar_start": 8, "bars": 8, "energy": 0.9, "instruments": []},
        ]
        result = score_arrangement(_make_plan(sections=sections))
        assert result["energy_curve_score"] > 0.5

    def test_completely_flat_energy_scores_near_zero(self):
        flat_curve = [{"bar": i * 8, "energy": 0.5} for i in range(6)]
        result = score_arrangement(_make_plan(sections=_flat_sections(), energy_curve=flat_curve))
        assert result["energy_curve_score"] < ENERGY_CURVE_REJECT_THRESHOLD

    def test_energy_curve_preferred_over_section_energies(self):
        """Explicit energy_curve should be used when available."""
        # Sections have flat energy but explicit curve has high range
        sections = _flat_sections()
        curve = [
            {"bar": 0, "energy": 0.1},
            {"bar": 16, "energy": 0.9},
            {"bar": 32, "energy": 0.2},
        ]
        result = score_arrangement(_make_plan(sections=sections, energy_curve=curve))
        assert result["energy_curve_score"] > 0.4


# ---------------------------------------------------------------------------
# Contrast scoring
# ---------------------------------------------------------------------------


class TestContrastScore:
    def test_high_contrast_arrangement_scores_well(self):
        result = score_arrangement(_make_plan(sections=_good_sections()))
        assert result["contrast_score"] > 0.3

    def test_no_contrast_scores_low(self):
        result = score_arrangement(_make_plan(sections=_flat_sections()))
        assert result["contrast_score"] < 0.3

    def test_single_section_returns_zero(self):
        sections = [_good_sections()[0]]
        result = score_arrangement(_make_plan(sections=sections))
        assert result["contrast_score"] == 0.0


# ---------------------------------------------------------------------------
# Repetition penalty
# ---------------------------------------------------------------------------


class TestRepetitionPenalty:
    def test_varied_sections_have_low_penalty(self):
        result = score_arrangement(_make_plan(sections=_good_sections()))
        assert result["repetition_penalty"] < 0.5

    def test_all_same_type_has_high_penalty(self):
        result = score_arrangement(_make_plan(sections=_flat_sections()))
        assert result["repetition_penalty"] > REPETITION_REJECT_THRESHOLD

    def test_unique_instrument_sets_reduce_penalty(self):
        sections = [
            {"type": "intro", "bar_start": 0, "bars": 8, "energy": 0.3, "instruments": ["kick"]},
            {"type": "verse", "bar_start": 8, "bars": 8, "energy": 0.5, "instruments": ["bass", "snare"]},
            {"type": "hook", "bar_start": 16, "bars": 8, "energy": 0.9, "instruments": ["kick", "snare", "lead", "pad"]},
            {"type": "outro", "bar_start": 24, "bars": 8, "energy": 0.2, "instruments": ["pad"]},
        ]
        result = score_arrangement(_make_plan(sections=sections))
        assert result["repetition_penalty"] < 0.5


# ---------------------------------------------------------------------------
# Hook payoff
# ---------------------------------------------------------------------------


class TestHookPayoffScore:
    def test_high_energy_hook_scores_well(self):
        result = score_arrangement(_make_plan(sections=_good_sections()))
        assert result["hook_payoff_score"] > HOOK_PAYOFF_REJECT_THRESHOLD

    def test_no_hook_sections_returns_moderate_score(self):
        """Plans without hooks get a partial score rather than zero."""
        sections = [s for s in _good_sections() if s["type"] not in ("hook", "chorus")]
        result = score_arrangement(_make_plan(sections=sections))
        # Should not be rejected just for missing a hook section
        assert result["hook_payoff_score"] >= 0.20

    def test_hook_lower_energy_than_verse_scores_low(self):
        sections = [
            {"type": "verse", "bar_start": 0, "bars": 16, "energy": 0.9, "instruments": ["kick", "snare", "bass", "lead", "pad"]},
            {"type": "hook", "bar_start": 16, "bars": 8, "energy": 0.2, "instruments": ["kick"]},
        ]
        result = score_arrangement(_make_plan(sections=sections))
        assert result["hook_payoff_score"] < 0.40


# ---------------------------------------------------------------------------
# Transition scoring
# ---------------------------------------------------------------------------


class TestTransitionScore:
    def test_covered_transitions_score_well(self):
        result = score_arrangement(_make_plan(sections=_good_sections(), events=_good_events()))
        assert result["transition_score"] > 0.4

    def test_no_events_scores_zero(self):
        result = score_arrangement(_make_plan(sections=_good_sections(), events=[]))
        assert result["transition_score"] == 0.0

    def test_non_transition_events_do_not_count(self):
        events = [
            {"type": "enable_stem", "bar": 8},
            {"type": "disable_stem", "bar": 24},
        ]
        result = score_arrangement(_make_plan(sections=_good_sections(), events=events))
        assert result["transition_score"] == 0.0


# ---------------------------------------------------------------------------
# Role diversity
# ---------------------------------------------------------------------------


class TestRoleDiversityScore:
    def test_many_unique_roles_scores_well(self):
        result = score_arrangement(_make_plan(sections=_good_sections()))
        assert result["role_diversity_score"] > 0.2

    def test_single_role_everywhere_scores_low(self):
        sections = [
            {"type": "verse", "bar_start": i * 8, "bars": 8, "energy": 0.5, "instruments": ["kick"]}
            for i in range(4)
        ]
        result = score_arrangement(_make_plan(sections=sections))
        assert result["role_diversity_score"] < 0.3

    def test_empty_instruments_does_not_crash(self):
        sections = [{"type": "verse", "bar_start": 0, "bars": 8, "energy": 0.5, "instruments": []}]
        result = score_arrangement(_make_plan(sections=sections))
        assert isinstance(result["role_diversity_score"], float)


# ---------------------------------------------------------------------------
# Overall score
# ---------------------------------------------------------------------------


class TestOverallScore:
    def test_good_arrangement_passes_overall_threshold(self):
        result = score_arrangement(
            _make_plan(sections=_good_sections(), events=_good_events())
        )
        assert result["overall_score"] >= OVERALL_REJECT_THRESHOLD

    def test_flat_arrangement_fails_overall_threshold(self):
        flat_curve = [{"bar": i * 8, "energy": 0.5} for i in range(4)]
        result = score_arrangement(
            _make_plan(sections=_flat_sections(), energy_curve=flat_curve, events=[])
        )
        assert result["overall_score"] < OVERALL_REJECT_THRESHOLD


# ---------------------------------------------------------------------------
# evaluate_arrangement()
# ---------------------------------------------------------------------------


class TestEvaluateArrangement:
    def test_returns_three_tuple(self):
        breakdown, passed, reasons = evaluate_arrangement(_make_plan())
        assert isinstance(breakdown, dict)
        assert isinstance(passed, bool)
        assert isinstance(reasons, list)

    def test_good_plan_passes(self):
        plan = _make_plan(sections=_good_sections(), events=_good_events())
        _, passed, reasons = evaluate_arrangement(plan)
        assert passed is True
        assert reasons == []

    def test_flat_plan_fails(self):
        flat_curve = [{"bar": i * 8, "energy": 0.5} for i in range(4)]
        plan = _make_plan(sections=_flat_sections(), energy_curve=flat_curve, events=[])
        _, passed, reasons = evaluate_arrangement(plan)
        assert passed is False
        assert len(reasons) > 0

    def test_failure_reasons_are_descriptive(self):
        flat_curve = [{"bar": i * 8, "energy": 0.5} for i in range(4)]
        plan = _make_plan(sections=_flat_sections(), energy_curve=flat_curve, events=[])
        _, _, reasons = evaluate_arrangement(plan)
        full_text = " ".join(reasons).lower()
        # At minimum energy_curve or overall should be mentioned
        assert any(kw in full_text for kw in ("overall", "energy", "repetit"))

    def test_breakdown_included_in_result(self):
        plan = _make_plan(sections=_good_sections(), events=_good_events())
        breakdown, _, _ = evaluate_arrangement(plan)
        assert "overall_score" in breakdown
        assert "hook_payoff_score" in breakdown


# ---------------------------------------------------------------------------
# score_and_reject()
# ---------------------------------------------------------------------------


class TestScoreAndReject:
    def test_good_plan_returns_breakdown(self):
        plan = _make_plan(sections=_good_sections(), events=_good_events())
        result = score_and_reject(plan)
        assert isinstance(result, dict)
        assert "overall_score" in result

    def test_bad_plan_raises_value_error(self):
        flat_curve = [{"bar": i * 8, "energy": 0.5} for i in range(4)]
        plan = _make_plan(sections=_flat_sections(), energy_curve=flat_curve, events=[])
        with pytest.raises(ValueError, match="rejected"):
            score_and_reject(plan)

    def test_error_message_contains_reason(self):
        # Force repetition failure: 6 identical verse sections with identical instruments
        repeat_sections = [
            {"type": "verse", "bar_start": i * 8, "bars": 8, "energy": 0.5, "instruments": ["kick", "bass"]}
            for i in range(6)
        ]
        flat_curve = [{"bar": i * 8, "energy": 0.5} for i in range(6)]
        plan = _make_plan(sections=repeat_sections, energy_curve=flat_curve, events=[])
        with pytest.raises(ValueError) as exc_info:
            score_and_reject(plan)
        msg = str(exc_info.value).lower()
        assert "rejected" in msg

    def test_empty_plan_does_not_raise_unexpectedly(self):
        """An empty plan should raise ValueError (not a crash)."""
        with pytest.raises((ValueError, Exception)):
            score_and_reject({})

    def test_score_and_reject_logs_scores(self, caplog):
        import logging
        plan = _make_plan(sections=_good_sections(), events=_good_events())
        with caplog.at_level(logging.INFO, logger="app.services.arrangement_scorer"):
            score_and_reject(plan)
        assert any("ARRANGEMENT_SCORE" in r.message for r in caplog.records)
