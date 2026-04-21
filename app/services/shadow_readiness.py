"""
Shadow Readiness Scoring — production cutover eligibility for shadow engines.

Each shadow engine is scored 0–100 based on four weighted dimensions:

=================  ======  =============================================
Dimension          Weight  Description
=================  ======  =============================================
Completeness       30 pts  Plan produced without error; no null result.
Validation health  30 pts  Fraction of sections that are error-free.
Section alignment  20 pts  Shadow section count matches the live plan.
Quality metric     20 pts  Engine-specific scalar (bounce, repetition,
                           tension …); falls back to 1.0 if not
                           available.
=================  ======  =============================================

Promotion thresholds::

    READY        ≥ 80  — safe to promote to live rendering.
    CONDITIONAL  60–79 — promote with monitoring and feature flag.
    NOT_READY    < 60  — keep in shadow; investigate issues.

Usage::

    from app.services.shadow_comparison import compare_shadow_vs_live
    from app.services.shadow_readiness import score_shadow_readiness

    comparison = compare_shadow_vs_live(render_plan)
    report = score_shadow_readiness(comparison)

    for engine, score in report.engine_scores.items():
        print(engine, score.readiness_label, score.total_score)

    print(report.cutover_order)      # engines ordered by score desc
    print(report.all_engines_ready)  # True only when all score >= 80
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.services.shadow_comparison import (
    EngineComparisonDetail,
    ShadowComparisonReport,
)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

READY_THRESHOLD = 80
CONDITIONAL_THRESHOLD = 60

# Minimum quality metric value that earns full quality_metric points.
# A metric value of 0.0 earns 0 points; 1.0 earns full points linearly.
_QUALITY_METRIC_FULL = 1.0

# Dimension weights (must sum to 100).
_W_COMPLETENESS = 30
_W_VALIDATION = 30
_W_ALIGNMENT = 20
_W_QUALITY = 20


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class EngineReadinessScore:
    """Readiness score for a single shadow engine."""

    engine: str

    # 0–100 composite score.
    total_score: float

    # Individual dimension scores (each 0–their maximum weight).
    completeness_score: float  # 0–30
    validation_score: float    # 0–30
    alignment_score: float     # 0–20
    quality_score: float       # 0–20

    # Human-readable readiness tier.
    readiness_label: str  # "READY" | "CONDITIONAL" | "NOT_READY"

    # Whether this engine is recommended for cutover.
    recommended_for_cutover: bool

    # Specific issues that prevent promotion (empty when READY).
    blockers: List[str]

    # The environment variable name that gates live-mode for this engine.
    live_flag_env_var: str


@dataclass
class ShadowReadinessReport:
    """Full readiness report for all shadow engines."""

    engine_scores: Dict[str, EngineReadinessScore]

    # Engines ordered by total_score descending (best candidates first).
    cutover_order: List[str]

    # True only when every scored engine reaches READY (≥80).
    all_engines_ready: bool

    # Engines at READY threshold.
    ready_engines: List[str]

    # Engines in CONDITIONAL band.
    conditional_engines: List[str]

    # Engines below CONDITIONAL threshold.
    not_ready_engines: List[str]

    # Recommended first cutover candidate (highest score).
    first_candidate: Optional[str]


# ---------------------------------------------------------------------------
# Env-var names for each engine's live-mode flag (defined in config.py)
# ---------------------------------------------------------------------------

_LIVE_FLAG_ENV_VARS: dict[str, str] = {
    "timeline":          "TIMELINE_ENGINE_LIVE",
    "pattern_variation": "PATTERN_VARIATION_LIVE",
    "groove":            "GROOVE_ENGINE_LIVE",
    "drop":              "DROP_ENGINE_LIVE",
    "motif":             "MOTIF_ENGINE_LIVE",
    "ai_producer":       "AI_PRODUCER_SYSTEM_LIVE",
}


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _score_completeness(detail: EngineComparisonDetail) -> float:
    """30 pts if plan produced without error; 0 otherwise."""
    if detail.plan_produced and not detail.error:
        return float(_W_COMPLETENESS)
    return 0.0


def _score_validation(detail: EngineComparisonDetail, live_count: int) -> float:
    """30 pts scaled by fraction of sections that are error-free.

    If the engine produced no validation errors the score is full.
    Each error removes a proportional slice of the 30 pts.
    """
    if not detail.plan_produced:
        return 0.0
    if live_count <= 0:
        return float(_W_VALIDATION) if detail.validation_error_count == 0 else 0.0
    error_fraction = min(1.0, detail.validation_error_count / live_count)
    return _W_VALIDATION * (1.0 - error_fraction)


def _score_alignment(detail: EngineComparisonDetail) -> float:
    """20 pts scaled by section_alignment (0.0–1.0)."""
    if not detail.plan_produced:
        return 0.0
    return _W_ALIGNMENT * detail.section_alignment


def _score_quality(detail: EngineComparisonDetail) -> float:
    """20 pts scaled by engine's quality metric (0.0–1.0).

    If no quality metric is available we assume 1.0 (no evidence of poor
    quality — benefit of the doubt).
    """
    if not detail.plan_produced:
        return 0.0
    metric = detail.quality_metric
    if metric is None:
        return float(_W_QUALITY)
    # Quality metrics are typically 0–1 scores.
    clamped = max(0.0, min(1.0, metric))
    return _W_QUALITY * clamped


def _build_blockers(
    detail: EngineComparisonDetail,
    live_count: int,
    total_score: float,
) -> List[str]:
    blockers: List[str] = []
    if detail.error:
        blockers.append(f"Engine errored: {detail.error}")
    if not detail.plan_produced:
        blockers.append("No plan produced (shadow output missing or null).")
    if detail.validation_error_count > 0:
        blockers.append(
            f"{detail.validation_error_count} validation error(s) reported by the engine."
        )
    if detail.section_alignment < 0.8:
        blockers.append(
            f"Section-count alignment low ({detail.section_alignment:.0%}) — "
            "shadow plan covers a different number of sections than the live plan."
        )
    if (
        detail.quality_metric is not None
        and detail.quality_metric < 0.4
    ):
        name = detail.quality_metric_name or "quality_metric"
        blockers.append(
            f"{name} is low ({detail.quality_metric:.3f} < 0.4) — "
            "engine output quality needs investigation."
        )
    return blockers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_engine(
    detail: EngineComparisonDetail, live_section_count: int
) -> EngineReadinessScore:
    """Score a single engine detail against the live plan.

    Parameters
    ----------
    detail:
        :class:`EngineComparisonDetail` from ``compare_shadow_vs_live``.
    live_section_count:
        Number of sections in the live render plan.
    """
    c = _score_completeness(detail)
    v = _score_validation(detail, live_section_count)
    a = _score_alignment(detail)
    q = _score_quality(detail)

    total = round(c + v + a + q, 2)

    if total >= READY_THRESHOLD:
        label = "READY"
        recommended = True
    elif total >= CONDITIONAL_THRESHOLD:
        label = "CONDITIONAL"
        recommended = False
    else:
        label = "NOT_READY"
        recommended = False

    blockers = _build_blockers(detail, live_section_count, total)
    live_flag = _LIVE_FLAG_ENV_VARS.get(detail.engine, f"{detail.engine.upper()}_LIVE")

    return EngineReadinessScore(
        engine=detail.engine,
        total_score=total,
        completeness_score=c,
        validation_score=v,
        alignment_score=a,
        quality_score=q,
        readiness_label=label,
        recommended_for_cutover=recommended,
        blockers=blockers,
        live_flag_env_var=live_flag,
    )


def score_shadow_readiness(comparison: ShadowComparisonReport) -> ShadowReadinessReport:
    """Score all shadow engines in *comparison* for production readiness.

    Parameters
    ----------
    comparison:
        :class:`ShadowComparisonReport` from ``compare_shadow_vs_live``.

    Returns
    -------
    :class:`ShadowReadinessReport`
        Full readiness analysis; never raises.
    """
    live_count = comparison.live_section_count
    engine_scores: Dict[str, EngineReadinessScore] = {}

    for engine_name, detail in comparison.engine_details.items():
        engine_scores[engine_name] = score_engine(detail, live_count)

    cutover_order = sorted(
        engine_scores.keys(),
        key=lambda e: engine_scores[e].total_score,
        reverse=True,
    )

    ready = [e for e in cutover_order if engine_scores[e].readiness_label == "READY"]
    conditional = [
        e for e in cutover_order if engine_scores[e].readiness_label == "CONDITIONAL"
    ]
    not_ready = [
        e for e in cutover_order if engine_scores[e].readiness_label == "NOT_READY"
    ]

    all_ready = len(engine_scores) > 0 and len(not_ready) == 0 and len(conditional) == 0
    first_candidate = cutover_order[0] if cutover_order else None

    return ShadowReadinessReport(
        engine_scores=engine_scores,
        cutover_order=cutover_order,
        all_engines_ready=all_ready,
        ready_engines=ready,
        conditional_engines=conditional,
        not_ready_engines=not_ready,
        first_candidate=first_candidate,
    )


# ---------------------------------------------------------------------------
# Cutover strategy description
# ---------------------------------------------------------------------------

#: Recommended promotion order based on impact surface and rollback safety.
#: Lower-risk engines that enhance existing audio (groove, pattern variation)
#: precede structural engines (drop, motif, timeline) which alter section
#: layout, and finally the AI producer which replaces the top-level planner.
RECOMMENDED_CUTOVER_ORDER: List[str] = [
    "groove",            # Phase 1 — microtiming & accent, no structural change
    "pattern_variation", # Phase 2 — intra-section drum/melodic variation
    "drop",              # Phase 3 — section-boundary tension & payoff events
    "motif",             # Phase 4 — cross-section identity & motif reuse
    "timeline",          # Phase 5 — full section energy/density target system
    "ai_producer",       # Phase 6 — multi-agent top-level planner (highest risk)
]

CUTOVER_PREREQUISITES: dict[str, List[str]] = {
    "groove":            [],
    "pattern_variation": [],
    "drop":              ["groove", "pattern_variation"],
    "motif":             ["pattern_variation"],
    "timeline":          ["groove", "pattern_variation", "drop", "motif"],
    "ai_producer":       RECOMMENDED_CUTOVER_ORDER[:-1],  # all others first
}


def describe_cutover_strategy(report: ShadowReadinessReport) -> str:
    """Return a human-readable cutover strategy summary for *report*.

    The summary covers:
    - Which engines are ready to promote right now.
    - Which require further observation.
    - The recommended promotion sequence with prerequisite checks.
    - The environment variable to flip for each promotion.
    """
    lines: List[str] = [
        "# Shadow Stack Cutover Strategy",
        "",
        f"Live-plan section count: {report.engine_scores[next(iter(report.engine_scores))].engine if report.engine_scores else 'n/a'}",
        "",
        "## Per-Engine Readiness",
        "",
    ]

    for engine in RECOMMENDED_CUTOVER_ORDER:
        score = report.engine_scores.get(engine)
        if not score:
            continue
        status = f"[{score.readiness_label}]"
        lines.append(
            f"  {engine:<20} {status:<15} score={score.total_score:>5.1f}/100  "
            f"flag={score.live_flag_env_var}"
        )
        for b in score.blockers:
            lines.append(f"      ⚠  {b}")

    lines += [
        "",
        "## Recommended Promotion Sequence",
        "",
    ]

    for step, engine in enumerate(RECOMMENDED_CUTOVER_ORDER, start=1):
        score = report.engine_scores.get(engine)
        if not score:
            continue
        prereqs = CUTOVER_PREREQUISITES.get(engine, [])
        prereq_str = ", ".join(prereqs) if prereqs else "none"
        lines.append(
            f"  {step}. {engine}  (prerequisites: {prereq_str})"
        )
        lines.append(
            f"     Set {score.live_flag_env_var}=true to activate."
        )
        lines.append(
            f"     Rollback: set {score.live_flag_env_var}=false to revert to shadow."
        )
        lines.append("")

    lines += [
        "## Summary",
        "",
        f"  READY engines        : {', '.join(report.ready_engines) or 'none'}",
        f"  CONDITIONAL engines  : {', '.join(report.conditional_engines) or 'none'}",
        f"  NOT_READY engines    : {', '.join(report.not_ready_engines) or 'none'}",
        f"  First candidate      : {report.first_candidate or 'none'}",
        f"  All engines ready    : {report.all_engines_ready}",
    ]

    return "\n".join(lines)
