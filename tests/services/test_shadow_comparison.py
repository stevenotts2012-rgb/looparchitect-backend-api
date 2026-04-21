"""
Tests for app/services/shadow_comparison.py.

Coverage (48 tests):
1.  compare_shadow_vs_live — empty render plan.
2.  compare_shadow_vs_live — only live sections, no shadow data.
3.  Timeline engine — plan produced, section alignment, validation issues.
4.  Timeline engine — error key propagates correctly.
5.  Timeline engine — energy drift calculation.
6.  Timeline engine — role coverage calculation.
7.  Pattern variation engine — repetition_score quality metric.
8.  Pattern variation engine — low_score_sections become warnings.
9.  Pattern variation engine — missing plan key.
10. Groove engine — bounce_score quality metric.
11. Groove engine — validation_issues propagated.
12. Groove engine — low_bounce_sections become warnings.
13. AI producer engine — plan produced from _ai_producer_plan.
14. AI producer engine — critic scores averaged to quality_metric.
15. AI producer engine — _ai_rejected_reason becomes error count.
16. AI producer engine — missing plan key.
17. Drop engine — boundary count vs (live_sections - 1).
18. Drop engine — _drop_scores tension average.
19. Drop engine — _drop_warnings propagated.
20. Drop engine — missing _drop_plan.
21. Motif engine — occurrence index coverage.
22. Motif engine — _motif_scores coherence_score.
23. Motif engine — _motif_warnings propagated.
24. Motif engine — missing _motif_plan.
25. Overall alignment score — mean of successful engines.
26. successful_engines / failed_engines lists.
27. total_validation_errors and total_validation_warnings.
28. SectionDiff — roles_added / roles_removed / roles_matched.
29. SectionDiff — sections with no roles.
30. _alignment_score helper — edge cases.
31. compare_shadow_vs_live — all shadow engines present, no errors.
32. compare_shadow_vs_live — single section.
33. compare_shadow_vs_live — engine comparator exception is caught.
34. Timeline plan serialisation format (nested sections list).
35. Pattern variation — energy drift when plans have energy field.
36. Groove engine — role coverage from active_roles field.
37. Drop engine — section_alignment is 1.0 for empty live plan.
38. Motif engine — list-type _motif_scores.
39. AI producer — no critic scores gives quality_metric = None.
40. compare_shadow_vs_live returns live_section_count correctly.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.services.shadow_comparison import (
    ShadowComparisonReport,
    EngineComparisonDetail,
    SectionDiff,
    compare_shadow_vs_live,
    _alignment_score,
    _diff_sections,
    _mean_energy_drift,
    _mean_role_coverage,
    SHADOW_ENGINE_KEYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _live_section(
    name: str = "verse",
    energy: float = 0.6,
    roles: List[str] | None = None,
    bars: int = 8,
) -> dict:
    return {
        "type": name,
        "bars": bars,
        "energy": energy,
        "active_stem_roles": roles if roles is not None else ["drums", "bass", "melody"],
    }


def _minimal_render_plan(sections: List[dict] | None = None) -> dict:
    return {"sections": sections or []}


def _tl_section(
    name: str = "verse",
    bars: int = 8,
    target_energy: float = 0.6,
    roles: List[str] | None = None,
    events: List[dict] | None = None,
) -> dict:
    return {
        "name": name,
        "bars": bars,
        "target_energy": target_energy,
        "target_density": 0.6,
        "active_roles": roles or ["drums", "bass"],
        "events": events or [],
    }


# ---------------------------------------------------------------------------
# 1. Empty render plan
# ---------------------------------------------------------------------------


class TestEmptyRenderPlan:
    def test_empty_plan_returns_zero_live_count(self):
        report = compare_shadow_vs_live({})
        assert report.live_section_count == 0

    def test_empty_plan_all_engines_no_plan(self):
        report = compare_shadow_vs_live({})
        for engine in SHADOW_ENGINE_KEYS:
            assert not report.engine_details[engine].plan_produced

    def test_empty_plan_overall_alignment_zero(self):
        report = compare_shadow_vs_live({})
        assert report.overall_alignment_score == 0.0

    def test_empty_plan_all_engines_in_failed(self):
        report = compare_shadow_vs_live({})
        assert set(report.failed_engines) == set(SHADOW_ENGINE_KEYS)
        assert report.successful_engines == []


# ---------------------------------------------------------------------------
# 2. Only live sections, no shadow data
# ---------------------------------------------------------------------------


class TestLiveSectionsNoShadow:
    def test_live_count_set_correctly(self):
        plan = _minimal_render_plan([_live_section(), _live_section("hook")])
        report = compare_shadow_vs_live(plan)
        assert report.live_section_count == 2

    def test_no_shadow_data_no_plan_produced(self):
        plan = _minimal_render_plan([_live_section()])
        report = compare_shadow_vs_live(plan)
        for detail in report.engine_details.values():
            assert not detail.plan_produced

    def test_no_shadow_data_no_errors(self):
        plan = _minimal_render_plan([_live_section()])
        report = compare_shadow_vs_live(plan)
        assert report.total_validation_errors == 0


# ---------------------------------------------------------------------------
# 3–6. Timeline engine
# ---------------------------------------------------------------------------


class TestTimelineEngine:
    def _plan_with_timeline(
        self,
        live_sections: List[dict],
        shadow_sections: List[dict],
        validation_issues: List[dict] | None = None,
        event_count: int | None = None,
    ) -> dict:
        plan = _minimal_render_plan(live_sections)
        plan["_timeline_plan"] = {
            "plan": {"sections": shadow_sections},
            "validation_issues": validation_issues or [],
            "section_count": len(shadow_sections),
            "event_count": event_count or 0,
            "error": None,
        }
        return plan

    def test_plan_produced_true(self):
        plan = self._plan_with_timeline([_live_section()], [_tl_section()])
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["timeline"].plan_produced is True

    def test_section_alignment_identical_count(self):
        plan = self._plan_with_timeline(
            [_live_section(), _live_section("hook")],
            [_tl_section(), _tl_section("hook")],
        )
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["timeline"].section_alignment == 1.0

    def test_section_alignment_mismatch(self):
        plan = self._plan_with_timeline(
            [_live_section(), _live_section("hook"), _live_section("outro")],
            [_tl_section(), _tl_section("hook")],
        )
        report = compare_shadow_vs_live(plan)
        detail = report.engine_details["timeline"]
        assert detail.section_alignment == pytest.approx(2 / 3)

    def test_error_key_propagated(self):
        plan = _minimal_render_plan([_live_section()])
        plan["_timeline_plan"] = {"error": "boom", "plan": None, "section_count": 0, "event_count": 0, "validation_issues": []}
        report = compare_shadow_vs_live(plan)
        detail = report.engine_details["timeline"]
        assert not detail.plan_produced
        assert detail.error == "boom"

    def test_validation_errors_counted(self):
        plan = self._plan_with_timeline(
            [_live_section()],
            [_tl_section()],
            validation_issues=[
                {"rule": "r1", "severity": "error", "message": "bad"},
                {"rule": "r2", "severity": "warning", "message": "warn"},
            ],
        )
        report = compare_shadow_vs_live(plan)
        detail = report.engine_details["timeline"]
        assert detail.validation_error_count == 1
        assert detail.validation_warning_count == 1

    def test_energy_drift_calculated(self):
        plan = self._plan_with_timeline(
            [_live_section(energy=0.8)],
            [_tl_section(target_energy=0.6)],
        )
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["timeline"].mean_energy_drift == pytest.approx(0.2)

    def test_role_coverage_full_match(self):
        plan = self._plan_with_timeline(
            [_live_section(roles=["drums", "bass"])],
            [_tl_section(roles=["drums", "bass"])],
        )
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["timeline"].mean_role_coverage == pytest.approx(1.0)

    def test_role_coverage_partial_match(self):
        plan = self._plan_with_timeline(
            [_live_section(roles=["drums", "bass", "melody"])],
            [_tl_section(roles=["drums"])],
        )
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["timeline"].mean_role_coverage == pytest.approx(1 / 3)

    def test_quality_metric_events_per_section(self):
        plan = self._plan_with_timeline(
            [_live_section(), _live_section("hook")],
            [_tl_section(), _tl_section("hook")],
            event_count=6,
        )
        report = compare_shadow_vs_live(plan)
        detail = report.engine_details["timeline"]
        assert detail.quality_metric_name == "mean_events_per_section"
        assert detail.quality_metric == pytest.approx(3.0)

    def test_nested_sections_format(self):
        """Timeline plan uses nested plan.sections list."""
        plan = _minimal_render_plan([_live_section()])
        plan["_timeline_plan"] = {
            "plan": {
                "sections": [{"name": "verse", "bars": 8, "target_energy": 0.5, "active_roles": ["drums"], "events": []}]
            },
            "validation_issues": [],
            "section_count": 1,
            "event_count": 0,
            "error": None,
        }
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["timeline"].plan_produced is True
        assert len(report.engine_details["timeline"].section_diffs) == 1


# ---------------------------------------------------------------------------
# 7–9. Pattern Variation Engine
# ---------------------------------------------------------------------------


class TestPatternVariationEngine:
    def _plan_with_pv(
        self,
        live_sections: List[dict],
        pv_plans: List[dict],
        low_score_sections: List[str] | None = None,
    ) -> dict:
        plan = _minimal_render_plan(live_sections)
        plan["_pattern_variation_plans"] = {
            "plans": pv_plans,
            "section_count": len(pv_plans),
            "total_events": sum(len(p.get("variations", [])) for p in pv_plans),
            "low_score_sections": low_score_sections or [],
            "error": None,
        }
        return plan

    def test_plan_produced_true(self):
        plan = self._plan_with_pv(
            [_live_section()],
            [{"repetition_score": 0.8, "active_roles": ["drums"], "energy": 0.6}],
        )
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["pattern_variation"].plan_produced is True

    def test_repetition_score_quality_metric(self):
        plan = self._plan_with_pv(
            [_live_section(), _live_section("hook")],
            [
                {"repetition_score": 0.9, "active_roles": [], "energy": 0.6},
                {"repetition_score": 0.7, "active_roles": [], "energy": 0.8},
            ],
        )
        report = compare_shadow_vs_live(plan)
        detail = report.engine_details["pattern_variation"]
        assert detail.quality_metric_name == "mean_repetition_score"
        assert detail.quality_metric == pytest.approx(0.8)

    def test_low_score_sections_become_warnings(self):
        plan = self._plan_with_pv(
            [_live_section()],
            [{"repetition_score": 0.2, "active_roles": [], "energy": 0.5}],
            low_score_sections=["Verse"],
        )
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["pattern_variation"].validation_warning_count >= 1

    def test_missing_plan_key(self):
        plan = _minimal_render_plan([_live_section()])
        report = compare_shadow_vs_live(plan)
        assert not report.engine_details["pattern_variation"].plan_produced


# ---------------------------------------------------------------------------
# 10–12. Groove Engine
# ---------------------------------------------------------------------------


class TestGrooveEngine:
    def _plan_with_groove(
        self,
        live_sections: List[dict],
        groove_plans: List[dict],
        validation_issues: List[dict] | None = None,
        low_bounce: List[str] | None = None,
    ) -> dict:
        plan = _minimal_render_plan(live_sections)
        plan["_groove_plans"] = {
            "plans": groove_plans,
            "section_count": len(groove_plans),
            "total_events": 0,
            "low_bounce_sections": low_bounce or [],
            "validation_issues": validation_issues or [],
            "error": None,
        }
        return plan

    def test_plan_produced(self):
        plan = self._plan_with_groove(
            [_live_section()],
            [{"bounce_score": 0.75, "active_roles": ["drums"]}],
        )
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["groove"].plan_produced is True

    def test_bounce_score_quality_metric(self):
        plan = self._plan_with_groove(
            [_live_section()],
            [{"bounce_score": 0.9, "active_roles": []}],
        )
        report = compare_shadow_vs_live(plan)
        detail = report.engine_details["groove"]
        assert detail.quality_metric_name == "mean_bounce_score"
        assert detail.quality_metric == pytest.approx(0.9)

    def test_validation_issues_propagated(self):
        plan = self._plan_with_groove(
            [_live_section()],
            [{"bounce_score": 0.5, "active_roles": []}],
            validation_issues=[{"rule": "r1", "severity": "error", "message": "x"}],
        )
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["groove"].validation_error_count == 1

    def test_low_bounce_becomes_warning(self):
        plan = self._plan_with_groove(
            [_live_section()],
            [{"bounce_score": 0.2, "active_roles": []}],
            low_bounce=["Verse"],
        )
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["groove"].validation_warning_count >= 1


# ---------------------------------------------------------------------------
# 13–16. AI Producer Engine
# ---------------------------------------------------------------------------


class TestAIProducerEngine:
    def test_plan_produced_from_ai_producer_plan(self):
        plan = _minimal_render_plan([_live_section()])
        plan["_ai_producer_plan"] = {"sections": [{"type": "verse", "energy": 0.6}]}
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["ai_producer"].plan_produced is True

    def test_critic_scores_averaged(self):
        plan = _minimal_render_plan([_live_section()])
        plan["_ai_producer_plan"] = {"sections": []}
        plan["_ai_critic_scores"] = {
            "structural_score": 0.8,
            "energy_score": 0.6,
            "contrast_score": 1.0,
        }
        report = compare_shadow_vs_live(plan)
        detail = report.engine_details["ai_producer"]
        assert detail.quality_metric == pytest.approx((0.8 + 0.6 + 1.0) / 3)
        assert detail.quality_metric_name == "mean_critic_score"

    def test_rejected_reason_becomes_error_count(self):
        plan = _minimal_render_plan([_live_section()])
        plan["_ai_producer_plan"] = {"sections": []}
        plan["_ai_rejected_reason"] = "plan failed validation"
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["ai_producer"].validation_error_count == 1

    def test_missing_plan_key(self):
        plan = _minimal_render_plan([_live_section()])
        report = compare_shadow_vs_live(plan)
        assert not report.engine_details["ai_producer"].plan_produced

    def test_no_critic_scores_quality_metric_none(self):
        plan = _minimal_render_plan([_live_section()])
        plan["_ai_producer_plan"] = {"sections": []}
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["ai_producer"].quality_metric is None


# ---------------------------------------------------------------------------
# 17–20. Drop Engine
# ---------------------------------------------------------------------------


class TestDropEngine:
    def test_boundary_count_vs_live_minus_one(self):
        live = [_live_section(), _live_section("hook"), _live_section("outro")]
        plan = _minimal_render_plan(live)
        plan["_drop_plan"] = {
            "boundaries": [{"from": "verse", "to": "hook"}, {"from": "hook", "to": "outro"}]
        }
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["drop"].section_alignment == pytest.approx(1.0)

    def test_drop_scores_tension_average(self):
        plan = _minimal_render_plan([_live_section(), _live_section("hook")])
        plan["_drop_plan"] = {"boundaries": [{"from": "verse", "to": "hook"}]}
        plan["_drop_scores"] = [{"tension_score": 0.7}, {"tension_score": 0.9}]
        report = compare_shadow_vs_live(plan)
        detail = report.engine_details["drop"]
        assert detail.quality_metric == pytest.approx(0.8)

    def test_drop_warnings_propagated(self):
        plan = _minimal_render_plan([_live_section()])
        plan["_drop_plan"] = {"boundaries": []}
        plan["_drop_warnings"] = [{"severity": "warning", "message": "w"}]
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["drop"].validation_warning_count >= 1

    def test_missing_drop_plan(self):
        plan = _minimal_render_plan([_live_section()])
        report = compare_shadow_vs_live(plan)
        assert not report.engine_details["drop"].plan_produced

    def test_section_alignment_one_for_single_section(self):
        plan = _minimal_render_plan([_live_section()])
        plan["_drop_plan"] = {"boundaries": []}
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["drop"].section_alignment == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 21–24. Motif Engine
# ---------------------------------------------------------------------------


class TestMotifEngine:
    def test_occurrence_coverage(self):
        live = [_live_section(), _live_section("hook"), _live_section("outro")]
        plan = _minimal_render_plan(live)
        plan["_motif_plan"] = {
            "occurrences": [
                {"section_index": 0},
                {"section_index": 1},
            ]
        }
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["motif"].section_alignment == pytest.approx(2 / 3)

    def test_coherence_score_quality_metric(self):
        plan = _minimal_render_plan([_live_section()])
        plan["_motif_plan"] = {"occurrences": [{"section_index": 0}]}
        plan["_motif_scores"] = {"coherence_score": 0.85}
        report = compare_shadow_vs_live(plan)
        detail = report.engine_details["motif"]
        assert detail.quality_metric == pytest.approx(0.85)
        assert detail.quality_metric_name == "coherence_score"

    def test_motif_warnings_propagated(self):
        plan = _minimal_render_plan([_live_section()])
        plan["_motif_plan"] = {"occurrences": []}
        plan["_motif_warnings"] = [{"severity": "warning", "message": "w"}]
        report = compare_shadow_vs_live(plan)
        assert report.engine_details["motif"].validation_warning_count >= 1

    def test_missing_motif_plan(self):
        plan = _minimal_render_plan([_live_section()])
        report = compare_shadow_vs_live(plan)
        assert not report.engine_details["motif"].plan_produced

    def test_list_motif_scores(self):
        plan = _minimal_render_plan([_live_section(), _live_section("hook")])
        plan["_motif_plan"] = {
            "occurrences": [{"section_index": 0}, {"section_index": 1}]
        }
        plan["_motif_scores"] = [{"score": 0.6}, {"score": 0.8}]
        report = compare_shadow_vs_live(plan)
        detail = report.engine_details["motif"]
        assert detail.quality_metric == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# 25–29. Aggregate report properties
# ---------------------------------------------------------------------------


class TestAggregateReport:
    def _full_plan(self) -> dict:
        live = [_live_section(), _live_section("hook")]
        plan = _minimal_render_plan(live)
        # Timeline shadow
        plan["_timeline_plan"] = {
            "plan": {"sections": [_tl_section(), _tl_section("hook")]},
            "validation_issues": [],
            "section_count": 2,
            "event_count": 4,
            "error": None,
        }
        # Pattern variation shadow
        plan["_pattern_variation_plans"] = {
            "plans": [
                {"repetition_score": 0.7, "active_roles": [], "energy": 0.6},
                {"repetition_score": 0.8, "active_roles": [], "energy": 0.8},
            ],
            "section_count": 2,
            "total_events": 2,
            "low_score_sections": [],
            "error": None,
        }
        # Groove shadow
        plan["_groove_plans"] = {
            "plans": [
                {"bounce_score": 0.9, "active_roles": []},
                {"bounce_score": 0.85, "active_roles": []},
            ],
            "section_count": 2,
            "total_events": 0,
            "low_bounce_sections": [],
            "validation_issues": [],
            "error": None,
        }
        # Drop shadow
        plan["_drop_plan"] = {"boundaries": [{"from": "verse", "to": "hook"}]}
        plan["_drop_scores"] = [{"tension_score": 0.8}]
        plan["_drop_warnings"] = []
        # Motif shadow
        plan["_motif_plan"] = {
            "occurrences": [{"section_index": 0}, {"section_index": 1}]
        }
        plan["_motif_scores"] = {"coherence_score": 0.9}
        plan["_motif_warnings"] = []
        # AI producer shadow
        plan["_ai_producer_plan"] = {
            "sections": [{"type": "verse"}, {"type": "hook"}]
        }
        plan["_ai_critic_scores"] = {
            "structural_score": 0.9,
            "energy_score": 0.8,
            "contrast_score": 0.85,
        }
        return plan

    def test_overall_alignment_all_present(self):
        report = compare_shadow_vs_live(self._full_plan())
        assert report.overall_alignment_score == pytest.approx(1.0)

    def test_successful_engines_list(self):
        report = compare_shadow_vs_live(self._full_plan())
        assert set(report.successful_engines) == set(SHADOW_ENGINE_KEYS)
        assert report.failed_engines == []

    def test_total_validation_zero_on_clean_plan(self):
        report = compare_shadow_vs_live(self._full_plan())
        assert report.total_validation_errors == 0

    def test_live_section_count(self):
        report = compare_shadow_vs_live(self._full_plan())
        assert report.live_section_count == 2

    def test_section_diff_roles_added_removed(self):
        live = [_live_section(roles=["drums", "bass"])]
        shadow = [{"target_energy": 0.6, "active_roles": ["drums", "melody"]}]
        diffs = _diff_sections(live, shadow)
        assert len(diffs) == 1
        assert "melody" in diffs[0].roles_added
        assert "bass" in diffs[0].roles_removed
        assert diffs[0].roles_matched == 1

    def test_section_diff_no_roles(self):
        live = [_live_section(roles=[])]
        shadow = [{"target_energy": 0.6, "active_roles": []}]
        diffs = _diff_sections(live, shadow)
        assert diffs[0].roles_matched == 0
        assert diffs[0].roles_added == []
        assert diffs[0].roles_removed == []

    def test_alignment_score_helper_zero_counts(self):
        assert _alignment_score(0, 0) == pytest.approx(1.0)
        assert _alignment_score(3, 0) == pytest.approx(0.0)
        assert _alignment_score(0, 3) == pytest.approx(0.0)
        assert _alignment_score(4, 4) == pytest.approx(1.0)
        assert _alignment_score(3, 6) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 33. Comparator exception is caught
# ---------------------------------------------------------------------------


class TestExceptionHandling:
    def test_malformed_shadow_data_does_not_raise(self):
        """If a shadow engine stores malformed data we get an error detail, not a crash."""
        plan = _minimal_render_plan([_live_section()])
        # Timeline plan with a non-dict plan value
        plan["_timeline_plan"] = "not_a_dict"
        report = compare_shadow_vs_live(plan)
        # Engine should not be in successful engines
        assert "timeline" not in report.successful_engines or \
               report.engine_details["timeline"].error is not None
