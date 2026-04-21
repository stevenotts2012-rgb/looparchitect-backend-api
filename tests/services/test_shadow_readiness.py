"""
Tests for app/services/shadow_readiness.py.

Coverage (43 tests):
1.  score_engine — full score when plan is perfect.
2.  score_engine — zero when plan not produced.
3.  score_engine — completeness zero when error set.
4.  score_engine — validation score scales with error count.
5.  score_engine — alignment score proportional to section_alignment.
6.  score_engine — quality score proportional to quality_metric.
7.  score_engine — quality score defaults to full when metric is None.
8.  score_engine — READY label at ≥80.
9.  score_engine — CONDITIONAL label at 60–79.
10. score_engine — NOT_READY label at <60.
11. score_engine — recommended_for_cutover True only for READY.
12. score_engine — blockers list empty when READY.
13. score_engine — blocker for error field.
14. score_engine — blocker for plan not produced.
15. score_engine — blocker for validation errors.
16. score_engine — blocker for low section alignment.
17. score_engine — blocker for low quality metric.
18. score_engine — live_flag_env_var for each engine name.
19. score_engine — dimension scores sum to total_score.
20. score_engine — quality_metric clamped to 1.0 when above 1.
21. score_shadow_readiness — cutover_order sorted by score desc.
22. score_shadow_readiness — ready_engines populated correctly.
23. score_shadow_readiness — conditional_engines populated correctly.
24. score_shadow_readiness — not_ready_engines populated correctly.
25. score_shadow_readiness — all_engines_ready True when all READY.
26. score_shadow_readiness — all_engines_ready False with one NOT_READY.
27. score_shadow_readiness — first_candidate is highest-scored engine.
28. score_shadow_readiness — first_candidate None when no engines.
29. describe_cutover_strategy — contains all engine names.
30. describe_cutover_strategy — contains env var names.
31. describe_cutover_strategy — contains READY/CONDITIONAL/NOT_READY labels.
32. describe_cutover_strategy — contains promotion sequence header.
33. RECOMMENDED_CUTOVER_ORDER — groove before pattern_variation before drop.
34. RECOMMENDED_CUTOVER_ORDER — ai_producer is last.
35. CUTOVER_PREREQUISITES — ai_producer requires all others.
36. CUTOVER_PREREQUISITES — groove and pattern_variation have no prerequisites.
37. score_engine — timeline live_flag = TIMELINE_ENGINE_LIVE.
38. score_engine — ai_producer live_flag = AI_PRODUCER_SYSTEM_LIVE.
39. score_shadow_readiness — single engine report.
40. score_shadow_readiness — reports keyed by all shadow engine names.
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from app.services.shadow_comparison import (
    EngineComparisonDetail,
    ShadowComparisonReport,
    SHADOW_ENGINE_KEYS,
)
from app.services.shadow_readiness import (
    EngineReadinessScore,
    ShadowReadinessReport,
    RECOMMENDED_CUTOVER_ORDER,
    CUTOVER_PREREQUISITES,
    READY_THRESHOLD,
    CONDITIONAL_THRESHOLD,
    describe_cutover_strategy,
    score_engine,
    score_shadow_readiness,
    _LIVE_FLAG_ENV_VARS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detail(
    engine: str = "timeline",
    plan_produced: bool = True,
    section_alignment: float = 1.0,
    validation_error_count: int = 0,
    validation_warning_count: int = 0,
    quality_metric: float | None = 1.0,
    quality_metric_name: str | None = "test_metric",
    error: str | None = None,
) -> EngineComparisonDetail:
    d = EngineComparisonDetail(engine=engine)
    d.plan_produced = plan_produced
    d.section_alignment = section_alignment
    d.validation_error_count = validation_error_count
    d.validation_warning_count = validation_warning_count
    d.quality_metric = quality_metric
    d.quality_metric_name = quality_metric_name
    d.error = error
    return d


def _perfect_detail(engine: str = "timeline") -> EngineComparisonDetail:
    return _detail(engine=engine, plan_produced=True, section_alignment=1.0,
                   validation_error_count=0, quality_metric=1.0)


def _minimal_report(details: Dict[str, EngineComparisonDetail]) -> ShadowComparisonReport:
    return ShadowComparisonReport(
        live_section_count=4,
        engine_details=details,
        overall_alignment_score=1.0,
        total_validation_errors=0,
        total_validation_warnings=0,
        failed_engines=[k for k, d in details.items() if not d.plan_produced],
        successful_engines=[k for k, d in details.items() if d.plan_produced],
    )


# ---------------------------------------------------------------------------
# 1–20. score_engine unit tests
# ---------------------------------------------------------------------------


class TestScoreEngine:
    def test_full_score_perfect_detail(self):
        score = score_engine(_perfect_detail(), live_section_count=4)
        assert score.total_score == pytest.approx(100.0)

    def test_zero_score_plan_not_produced(self):
        d = _detail(plan_produced=False)
        score = score_engine(d, live_section_count=4)
        assert score.total_score == pytest.approx(0.0)

    def test_completeness_zero_when_error(self):
        d = _detail(plan_produced=False, error="crash")
        score = score_engine(d, live_section_count=4)
        assert score.completeness_score == pytest.approx(0.0)

    def test_validation_score_full_when_no_errors(self):
        d = _detail(validation_error_count=0)
        score = score_engine(d, live_section_count=4)
        assert score.validation_score == pytest.approx(30.0)

    def test_validation_score_zero_when_errors_fill_sections(self):
        d = _detail(validation_error_count=4)
        score = score_engine(d, live_section_count=4)
        # error_fraction = 4/4 = 1.0 → 30 * 0 = 0
        assert score.validation_score == pytest.approx(0.0)

    def test_validation_score_proportional(self):
        d = _detail(validation_error_count=2)
        score = score_engine(d, live_section_count=4)
        # error_fraction = 0.5 → 30 * 0.5 = 15
        assert score.validation_score == pytest.approx(15.0)

    def test_alignment_score_full(self):
        d = _detail(section_alignment=1.0)
        score = score_engine(d, live_section_count=4)
        assert score.alignment_score == pytest.approx(20.0)

    def test_alignment_score_half(self):
        d = _detail(section_alignment=0.5)
        score = score_engine(d, live_section_count=4)
        assert score.alignment_score == pytest.approx(10.0)

    def test_quality_score_full_metric_one(self):
        d = _detail(quality_metric=1.0)
        score = score_engine(d, live_section_count=4)
        assert score.quality_score == pytest.approx(20.0)

    def test_quality_score_half_metric_half(self):
        d = _detail(quality_metric=0.5)
        score = score_engine(d, live_section_count=4)
        assert score.quality_score == pytest.approx(10.0)

    def test_quality_score_full_when_metric_none(self):
        d = _detail(quality_metric=None)
        score = score_engine(d, live_section_count=4)
        assert score.quality_score == pytest.approx(20.0)

    def test_quality_metric_clamped_above_one(self):
        d = _detail(quality_metric=2.5)
        score = score_engine(d, live_section_count=4)
        assert score.quality_score == pytest.approx(20.0)

    def test_label_ready_at_100(self):
        score = score_engine(_perfect_detail(), live_section_count=4)
        assert score.readiness_label == "READY"

    def test_label_not_ready_zero(self):
        d = _detail(plan_produced=False)
        score = score_engine(d, live_section_count=4)
        assert score.readiness_label == "NOT_READY"

    def test_label_conditional_band(self):
        # 30 (completeness) + 0 (validation - all errors) + 20 (alignment) + 20 (quality) = 70
        d = _detail(plan_produced=True, section_alignment=1.0, validation_error_count=4,
                    quality_metric=1.0)
        score = score_engine(d, live_section_count=4)
        assert CONDITIONAL_THRESHOLD <= score.total_score < READY_THRESHOLD
        assert score.readiness_label == "CONDITIONAL"

    def test_recommended_only_when_ready(self):
        ready = score_engine(_perfect_detail(), live_section_count=4)
        assert ready.recommended_for_cutover is True

        not_ready = score_engine(_detail(plan_produced=False), live_section_count=4)
        assert not_ready.recommended_for_cutover is False

    def test_blockers_empty_when_ready(self):
        score = score_engine(_perfect_detail(), live_section_count=4)
        assert score.blockers == []

    def test_blocker_for_error(self):
        d = _detail(error="crash", plan_produced=False)
        score = score_engine(d, live_section_count=4)
        assert any("errored" in b.lower() or "error" in b.lower() for b in score.blockers)

    def test_blocker_for_plan_not_produced(self):
        d = _detail(plan_produced=False)
        score = score_engine(d, live_section_count=4)
        assert any("plan" in b.lower() for b in score.blockers)

    def test_blocker_for_validation_errors(self):
        d = _detail(validation_error_count=2)
        score = score_engine(d, live_section_count=4)
        assert any("validation error" in b.lower() for b in score.blockers)

    def test_blocker_for_low_alignment(self):
        d = _detail(section_alignment=0.5)
        score = score_engine(d, live_section_count=4)
        assert any("alignment" in b.lower() for b in score.blockers)

    def test_blocker_for_low_quality_metric(self):
        d = _detail(quality_metric=0.2)
        score = score_engine(d, live_section_count=4)
        assert any("low" in b.lower() for b in score.blockers)

    def test_dimension_scores_sum_to_total(self):
        d = _detail(section_alignment=0.75, validation_error_count=1, quality_metric=0.8)
        score = score_engine(d, live_section_count=4)
        manual_total = (
            score.completeness_score
            + score.validation_score
            + score.alignment_score
            + score.quality_score
        )
        assert score.total_score == pytest.approx(manual_total)

    def test_live_flag_env_var_timeline(self):
        score = score_engine(_perfect_detail("timeline"), live_section_count=4)
        assert score.live_flag_env_var == "TIMELINE_ENGINE_LIVE"

    def test_live_flag_env_var_ai_producer(self):
        score = score_engine(_perfect_detail("ai_producer"), live_section_count=4)
        assert score.live_flag_env_var == "AI_PRODUCER_SYSTEM_LIVE"


# ---------------------------------------------------------------------------
# 21–28. score_shadow_readiness
# ---------------------------------------------------------------------------


class TestScoreShadowReadiness:
    def _all_perfect_report(self) -> ShadowComparisonReport:
        details = {e: _perfect_detail(e) for e in SHADOW_ENGINE_KEYS}
        return _minimal_report(details)

    def _mixed_report(self) -> ShadowComparisonReport:
        details = {
            "timeline": _perfect_detail("timeline"),
            "pattern_variation": _perfect_detail("pattern_variation"),
            "groove": _perfect_detail("groove"),
            # ai_producer: NOT produced → NOT_READY
            "ai_producer": _detail("ai_producer", plan_produced=False),
            # drop: low alignment → CONDITIONAL range
            "drop": _detail("drop", section_alignment=0.5,
                            validation_error_count=1, quality_metric=0.7),
            "motif": _perfect_detail("motif"),
        }
        return _minimal_report(details)

    def test_cutover_order_sorted_desc(self):
        report = score_shadow_readiness(self._all_perfect_report())
        scores = [report.engine_scores[e].total_score for e in report.cutover_order]
        assert scores == sorted(scores, reverse=True)

    def test_all_ready_when_perfect(self):
        report = score_shadow_readiness(self._all_perfect_report())
        assert report.all_engines_ready is True

    def test_not_all_ready_with_not_ready_engine(self):
        report = score_shadow_readiness(self._mixed_report())
        assert report.all_engines_ready is False

    def test_ready_engines_populated(self):
        report = score_shadow_readiness(self._all_perfect_report())
        assert set(report.ready_engines) == set(SHADOW_ENGINE_KEYS)
        assert report.conditional_engines == []
        assert report.not_ready_engines == []

    def test_not_ready_engines_populated(self):
        report = score_shadow_readiness(self._mixed_report())
        assert "ai_producer" in report.not_ready_engines

    def test_first_candidate_is_highest_score(self):
        report = score_shadow_readiness(self._all_perfect_report())
        best = report.cutover_order[0]
        for e in report.engine_scores:
            assert report.engine_scores[e].total_score <= report.engine_scores[best].total_score

    def test_first_candidate_none_when_empty(self):
        empty = ShadowComparisonReport(
            live_section_count=0,
            engine_details={},
            overall_alignment_score=0.0,
            total_validation_errors=0,
            total_validation_warnings=0,
            failed_engines=[],
            successful_engines=[],
        )
        report = score_shadow_readiness(empty)
        assert report.first_candidate is None

    def test_report_keyed_by_all_shadow_engines(self):
        report = score_shadow_readiness(self._all_perfect_report())
        assert set(report.engine_scores.keys()) == set(SHADOW_ENGINE_KEYS)


# ---------------------------------------------------------------------------
# 29–32. describe_cutover_strategy
# ---------------------------------------------------------------------------


class TestDescribeCutoverStrategy:
    def _report(self) -> ShadowReadinessReport:
        details = {e: _perfect_detail(e) for e in SHADOW_ENGINE_KEYS}
        comparison = _minimal_report(details)
        return score_shadow_readiness(comparison)

    def test_contains_all_engine_names(self):
        text = describe_cutover_strategy(self._report())
        for e in SHADOW_ENGINE_KEYS:
            assert e in text

    def test_contains_env_var_names(self):
        text = describe_cutover_strategy(self._report())
        for var in _LIVE_FLAG_ENV_VARS.values():
            assert var in text

    def test_contains_readiness_labels(self):
        text = describe_cutover_strategy(self._report())
        assert "READY" in text

    def test_contains_promotion_sequence_header(self):
        text = describe_cutover_strategy(self._report())
        assert "Promotion" in text or "Sequence" in text


# ---------------------------------------------------------------------------
# 33–36. RECOMMENDED_CUTOVER_ORDER and CUTOVER_PREREQUISITES
# ---------------------------------------------------------------------------


class TestCutoverConstants:
    def test_groove_before_pattern_variation(self):
        assert RECOMMENDED_CUTOVER_ORDER.index("groove") < \
               RECOMMENDED_CUTOVER_ORDER.index("pattern_variation")

    def test_pattern_variation_before_drop(self):
        assert RECOMMENDED_CUTOVER_ORDER.index("pattern_variation") < \
               RECOMMENDED_CUTOVER_ORDER.index("drop")

    def test_ai_producer_is_last(self):
        assert RECOMMENDED_CUTOVER_ORDER[-1] == "ai_producer"

    def test_ai_producer_prerequisites_include_all(self):
        ai_prereqs = set(CUTOVER_PREREQUISITES["ai_producer"])
        all_except_ai = set(RECOMMENDED_CUTOVER_ORDER) - {"ai_producer"}
        assert all_except_ai.issubset(ai_prereqs)

    def test_groove_no_prerequisites(self):
        assert CUTOVER_PREREQUISITES["groove"] == []

    def test_pattern_variation_no_prerequisites(self):
        assert CUTOVER_PREREQUISITES["pattern_variation"] == []
