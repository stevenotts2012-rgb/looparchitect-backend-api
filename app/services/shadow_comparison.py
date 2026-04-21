"""
Shadow Stack Comparison — live plan vs shadow engine outputs.

This module reads a ``render_plan`` dict (the in-memory representation of the
JSON stored in ``arrangements.render_plan_json``) and produces a structured
comparison between what the live arranger_v2 decided and what each shadow
engine independently planned.

Usage::

    from app.services.shadow_comparison import compare_shadow_vs_live

    report = compare_shadow_vs_live(render_plan)
    print(report.overall_alignment_score)   # 0.0–1.0
    for engine_name, detail in report.engine_details.items():
        print(engine_name, detail.section_alignment, detail.energy_drift)

None of the inputs are mutated.  The function is pure — same render_plan
always yields the same report.  It never raises; any per-engine error is
captured in :attr:`EngineComparisonDetail.error`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

SHADOW_ENGINE_KEYS: tuple[str, ...] = (
    "timeline",
    "pattern_variation",
    "groove",
    "ai_producer",
    "drop",
    "motif",
)

# render_plan dict keys where each shadow engine stores its output.
_ENGINE_PLAN_KEYS: dict[str, str] = {
    "timeline": "_timeline_plan",
    "pattern_variation": "_pattern_variation_plans",
    "groove": "_groove_plans",
    "ai_producer": "_ai_producer_plan",
    "drop": "_drop_plan",
    "motif": "_motif_plan",
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class SectionDiff:
    """Difference for a single section between live and one shadow engine."""

    section_index: int
    section_name: str
    # Energy targets: live value vs shadow value (None if not available).
    live_energy: float
    shadow_energy: Optional[float]
    energy_drift: float  # abs(live - shadow); 0.0 when shadow_energy is None.
    # Role sets.
    live_roles: List[str]
    shadow_roles: List[str]
    roles_added: List[str]   # in shadow but not in live
    roles_removed: List[str] # in live but not in shadow
    roles_matched: int       # intersection size


@dataclass
class EngineComparisonDetail:
    """Comparison result for a single shadow engine."""

    engine: str

    # Whether the engine produced a plan at all (no error key / non-null plan).
    plan_produced: bool = False

    # Section-level alignment: fraction of sections whose section_count
    # matches.  1.0 = identical count; 0.0 = completely mismatched or
    # no shadow plan available.
    section_alignment: float = 0.0

    # Mean absolute energy drift across all comparable sections.
    mean_energy_drift: float = 0.0

    # Fraction of live roles present in the shadow plan per section (mean).
    mean_role_coverage: float = 0.0

    # Validation issues reported by the engine itself.
    validation_error_count: int = 0
    validation_warning_count: int = 0

    # Per-section diffs (empty list if plan not produced).
    section_diffs: List[SectionDiff] = field(default_factory=list)

    # Engine-specific quality metric (e.g. mean bounce_score, repetition_score).
    # None if the engine does not expose a scalar quality metric.
    quality_metric: Optional[float] = None
    quality_metric_name: Optional[str] = None

    # Error message if the engine failed entirely (error key set in shadow
    # output).
    error: Optional[str] = None


@dataclass
class ShadowComparisonReport:
    """Full comparison of live plan vs all shadow engine outputs."""

    # Number of sections in the live render plan.
    live_section_count: int

    # Per-engine comparison details, keyed by engine name.
    engine_details: Dict[str, EngineComparisonDetail]

    # Overall alignment score: mean of per-engine section_alignment values
    # for engines that produced a plan.
    overall_alignment_score: float

    # Total validation errors across all shadow engines.
    total_validation_errors: int

    # Total validation warnings across all shadow engines.
    total_validation_warnings: int

    # Names of engines that failed to produce a plan.
    failed_engines: List[str]

    # Names of engines that produced a plan successfully.
    successful_engines: List[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _live_sections(render_plan: dict) -> List[dict]:
    return list(render_plan.get("sections") or [])


def _section_roles(section: dict) -> List[str]:
    roles = section.get("active_stem_roles") or section.get("instruments") or []
    return [str(r).strip().lower() for r in roles]


def _section_energy(section: dict) -> float:
    return _safe_float(section.get("energy"), 0.0)


def _section_name(section: dict, idx: int) -> str:
    name = section.get("section_name") or section.get("name") or section.get("type")
    return str(name) if name else f"section_{idx}"


# ---------------------------------------------------------------------------
# Per-engine comparators
# ---------------------------------------------------------------------------


def _diff_sections(
    live_sections: List[dict],
    shadow_sections: List[dict],
) -> List[SectionDiff]:
    """Build per-section diffs for comparable (index-matched) sections."""
    diffs: List[SectionDiff] = []
    for idx in range(min(len(live_sections), len(shadow_sections))):
        ls = live_sections[idx]
        ss = shadow_sections[idx]

        live_energy = _section_energy(ls)
        raw_shadow_energy = ss.get("target_energy") or ss.get("energy")
        shadow_energy = _safe_float(raw_shadow_energy) if raw_shadow_energy is not None else None
        energy_drift = abs(live_energy - shadow_energy) if shadow_energy is not None else 0.0

        live_roles = set(_section_roles(ls))
        shadow_roles_raw = (
            ss.get("active_roles")
            or ss.get("active_stem_roles")
            or ss.get("instruments")
            or []
        )
        shadow_roles_set = {str(r).strip().lower() for r in shadow_roles_raw}

        roles_added = sorted(shadow_roles_set - live_roles)
        roles_removed = sorted(live_roles - shadow_roles_set)
        roles_matched = len(live_roles & shadow_roles_set)

        diffs.append(SectionDiff(
            section_index=idx,
            section_name=_section_name(ls, idx),
            live_energy=live_energy,
            shadow_energy=shadow_energy,
            energy_drift=energy_drift,
            live_roles=sorted(live_roles),
            shadow_roles=sorted(shadow_roles_set),
            roles_added=roles_added,
            roles_removed=roles_removed,
            roles_matched=roles_matched,
        ))
    return diffs


def _alignment_score(live_count: int, shadow_count: int) -> float:
    """Section-count alignment: 1.0 if identical, scales linearly to 0."""
    if live_count == 0 and shadow_count == 0:
        return 1.0
    if live_count == 0 or shadow_count == 0:
        return 0.0
    bigger = max(live_count, shadow_count)
    smaller = min(live_count, shadow_count)
    return smaller / bigger


def _mean_role_coverage(diffs: List[SectionDiff]) -> float:
    if not diffs:
        return 0.0
    coverages: List[float] = []
    for d in diffs:
        live_count = len(d.live_roles)
        if live_count == 0:
            coverages.append(1.0)
        else:
            coverages.append(d.roles_matched / live_count)
    return sum(coverages) / len(coverages)


def _mean_energy_drift(diffs: List[SectionDiff]) -> float:
    if not diffs:
        return 0.0
    return sum(d.energy_drift for d in diffs) / len(diffs)


# ---------------------------------------------------------------------------
# Timeline Engine
# ---------------------------------------------------------------------------


def _compare_timeline(
    live_sections: List[dict], render_plan: dict
) -> EngineComparisonDetail:
    detail = EngineComparisonDetail(engine="timeline")
    raw = render_plan.get("_timeline_plan")
    if not raw:
        return detail

    if raw.get("error"):
        detail.error = raw["error"]
        return detail

    detail.plan_produced = True

    shadow_sections_raw = (raw.get("plan") or {}).get("sections") or []
    shadow_count = int(raw.get("section_count") or len(shadow_sections_raw))
    live_count = len(live_sections)

    detail.section_alignment = _alignment_score(live_count, shadow_count)

    issues = raw.get("validation_issues") or []
    detail.validation_error_count = sum(
        1 for i in issues if i.get("severity") == "error"
    )
    detail.validation_warning_count = sum(
        1 for i in issues if i.get("severity") == "warning"
    )

    diffs = _diff_sections(live_sections, shadow_sections_raw)
    detail.section_diffs = diffs
    detail.mean_energy_drift = _mean_energy_drift(diffs)
    detail.mean_role_coverage = _mean_role_coverage(diffs)

    event_count = int(raw.get("event_count") or 0)
    if shadow_count:
        detail.quality_metric = event_count / shadow_count
        detail.quality_metric_name = "mean_events_per_section"

    return detail


# ---------------------------------------------------------------------------
# Pattern Variation Engine
# ---------------------------------------------------------------------------


def _compare_pattern_variation(
    live_sections: List[dict], render_plan: dict
) -> EngineComparisonDetail:
    detail = EngineComparisonDetail(engine="pattern_variation")
    raw = render_plan.get("_pattern_variation_plans")
    if not raw:
        return detail

    if raw.get("error"):
        detail.error = raw["error"]
        return detail

    detail.plan_produced = True

    plans: List[dict] = raw.get("plans") or []
    shadow_count = int(raw.get("section_count") or len(plans))
    live_count = len(live_sections)

    detail.section_alignment = _alignment_score(live_count, shadow_count)

    # Build shadow_sections proxy from plans for diff (no energy target in PV engine,
    # but it does store energy in the context).
    shadow_sections: List[dict] = []
    repetition_scores: List[float] = []
    for p in plans:
        shadow_sections.append({
            "energy": p.get("energy"),
            "active_roles": p.get("active_roles") or [],
        })
        score = p.get("repetition_score")
        if score is not None:
            repetition_scores.append(_safe_float(score))

    diffs = _diff_sections(live_sections, shadow_sections)
    detail.section_diffs = diffs
    detail.mean_energy_drift = _mean_energy_drift(diffs)
    detail.mean_role_coverage = _mean_role_coverage(diffs)

    low_score_sections = raw.get("low_score_sections") or []
    detail.validation_warning_count = len(low_score_sections)

    if repetition_scores:
        detail.quality_metric = sum(repetition_scores) / len(repetition_scores)
        detail.quality_metric_name = "mean_repetition_score"

    return detail


# ---------------------------------------------------------------------------
# Groove Engine
# ---------------------------------------------------------------------------


def _compare_groove(
    live_sections: List[dict], render_plan: dict
) -> EngineComparisonDetail:
    detail = EngineComparisonDetail(engine="groove")
    raw = render_plan.get("_groove_plans")
    if not raw:
        return detail

    if raw.get("error"):
        detail.error = raw["error"]
        return detail

    detail.plan_produced = True

    plans: List[dict] = raw.get("plans") or []
    shadow_count = int(raw.get("section_count") or len(plans))
    live_count = len(live_sections)

    detail.section_alignment = _alignment_score(live_count, shadow_count)

    issues = raw.get("validation_issues") or []
    detail.validation_error_count = sum(
        1 for i in issues if i.get("severity") == "error"
    )
    detail.validation_warning_count = sum(
        1 for i in issues if i.get("severity") == "warning"
    )

    shadow_sections: List[dict] = []
    bounce_scores: List[float] = []
    for p in plans:
        shadow_sections.append({
            "energy": p.get("energy"),
            "active_roles": p.get("active_roles") or [],
        })
        score = p.get("bounce_score")
        if score is not None:
            bounce_scores.append(_safe_float(score))

    diffs = _diff_sections(live_sections, shadow_sections)
    detail.section_diffs = diffs
    detail.mean_energy_drift = _mean_energy_drift(diffs)
    detail.mean_role_coverage = _mean_role_coverage(diffs)

    low_bounce = raw.get("low_bounce_sections") or []
    detail.validation_warning_count = max(
        detail.validation_warning_count, len(low_bounce)
    )

    if bounce_scores:
        detail.quality_metric = sum(bounce_scores) / len(bounce_scores)
        detail.quality_metric_name = "mean_bounce_score"

    return detail


# ---------------------------------------------------------------------------
# AI Producer System
# ---------------------------------------------------------------------------


def _compare_ai_producer(
    live_sections: List[dict], render_plan: dict
) -> EngineComparisonDetail:
    detail = EngineComparisonDetail(engine="ai_producer")
    ai_plan = render_plan.get("_ai_producer_plan")
    if not ai_plan:
        return detail

    detail.plan_produced = True

    ai_sections: List[dict] = []
    if isinstance(ai_plan, dict):
        ai_sections = list(ai_plan.get("sections") or [])

    live_count = len(live_sections)
    shadow_count = len(ai_sections)

    detail.section_alignment = _alignment_score(live_count, shadow_count)

    # Critic scores: structural_score, energy_score, contrast_score
    critic = render_plan.get("_ai_critic_scores") or {}
    if isinstance(critic, dict):
        scores = []
        for k in ("structural_score", "energy_score", "contrast_score"):
            v = critic.get(k)
            if v is not None:
                scores.append(_safe_float(v))
        if scores:
            detail.quality_metric = sum(scores) / len(scores)
            detail.quality_metric_name = "mean_critic_score"

    rejected = render_plan.get("_ai_rejected_reason") or ""
    if rejected:
        detail.validation_error_count = 1

    diffs = _diff_sections(live_sections, ai_sections)
    detail.section_diffs = diffs
    detail.mean_energy_drift = _mean_energy_drift(diffs)
    detail.mean_role_coverage = _mean_role_coverage(diffs)

    return detail


# ---------------------------------------------------------------------------
# Drop Engine
# ---------------------------------------------------------------------------


def _compare_drop(
    live_sections: List[dict], render_plan: dict
) -> EngineComparisonDetail:
    detail = EngineComparisonDetail(engine="drop")
    raw = render_plan.get("_drop_plan")
    if not raw:
        return detail

    if isinstance(raw, dict) and raw.get("error"):
        detail.error = raw["error"]
        return detail

    detail.plan_produced = True

    # Drop engine plans per boundary, not per section — section_alignment
    # is derived from the number of boundaries vs (live_sections - 1).
    boundaries: List[dict] = []
    if isinstance(raw, dict):
        boundaries = list(raw.get("boundaries") or [])

    live_count = len(live_sections)
    expected_boundaries = max(0, live_count - 1)
    actual_boundaries = len(boundaries)
    detail.section_alignment = _alignment_score(
        expected_boundaries, actual_boundaries
    ) if expected_boundaries else 1.0

    warnings = list(render_plan.get("_drop_warnings") or [])
    detail.validation_warning_count = sum(
        1 for w in warnings if isinstance(w, dict) and w.get("severity") == "warning"
    )
    detail.validation_error_count = sum(
        1 for w in warnings if isinstance(w, dict) and w.get("severity") == "error"
    )

    scores: List[dict] = []
    if isinstance(render_plan.get("_drop_scores"), list):
        scores = render_plan["_drop_scores"]
    elif isinstance(render_plan.get("_drop_scores"), dict):
        scores = [render_plan["_drop_scores"]]

    tension_scores: List[float] = []
    for s in scores:
        if isinstance(s, dict):
            t = s.get("tension_score") or s.get("payoff_score")
            if t is not None:
                tension_scores.append(_safe_float(t))
    if tension_scores:
        detail.quality_metric = sum(tension_scores) / len(tension_scores)
        detail.quality_metric_name = "mean_tension_score"

    return detail


# ---------------------------------------------------------------------------
# Motif Engine
# ---------------------------------------------------------------------------


def _compare_motif(
    live_sections: List[dict], render_plan: dict
) -> EngineComparisonDetail:
    detail = EngineComparisonDetail(engine="motif")
    raw = render_plan.get("_motif_plan")
    if not raw:
        return detail

    if isinstance(raw, dict) and raw.get("error"):
        detail.error = raw["error"]
        return detail

    detail.plan_produced = True

    occurrences: List[dict] = []
    if isinstance(raw, dict):
        occurrences = list(raw.get("occurrences") or [])

    live_count = len(live_sections)
    # Each occurrence maps to a section; alignment = coverage of sections.
    covered_indices: set[int] = set()
    for occ in occurrences:
        if isinstance(occ, dict):
            idx = occ.get("section_index")
            if idx is not None:
                covered_indices.add(int(idx))

    if live_count:
        detail.section_alignment = len(covered_indices) / live_count
    else:
        detail.section_alignment = 1.0

    warnings = list(render_plan.get("_motif_warnings") or [])
    detail.validation_warning_count = sum(
        1 for w in warnings
        if isinstance(w, dict) and w.get("severity") in ("warning", "warn")
    )
    detail.validation_error_count = sum(
        1 for w in warnings
        if isinstance(w, dict) and w.get("severity") == "error"
    )

    scores = render_plan.get("_motif_scores")
    if isinstance(scores, dict):
        coherence = scores.get("coherence_score") or scores.get("overall_score")
        if coherence is not None:
            detail.quality_metric = _safe_float(coherence)
            detail.quality_metric_name = "coherence_score"
    elif isinstance(scores, list) and scores:
        vals = [_safe_float(s.get("score", 0)) for s in scores if isinstance(s, dict)]
        if vals:
            detail.quality_metric = sum(vals) / len(vals)
            detail.quality_metric_name = "mean_occurrence_score"

    return detail


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_COMPARATORS = {
    "timeline": _compare_timeline,
    "pattern_variation": _compare_pattern_variation,
    "groove": _compare_groove,
    "ai_producer": _compare_ai_producer,
    "drop": _compare_drop,
    "motif": _compare_motif,
}


def compare_shadow_vs_live(render_plan: dict) -> ShadowComparisonReport:
    """Compare the live render plan sections against all shadow engine outputs.

    Parameters
    ----------
    render_plan:
        The in-memory render plan dict.  Expected to be the parsed JSON from
        ``arrangements.render_plan_json``.  Shadow engine results are stored
        under the ``_*`` keys written by ``arrangement_jobs.py``.

    Returns
    -------
    :class:`ShadowComparisonReport`
        Pure-data result; never raises.
    """
    live_sections = _live_sections(render_plan)
    live_count = len(live_sections)

    engine_details: Dict[str, EngineComparisonDetail] = {}

    for name, comparator in _COMPARATORS.items():
        try:
            detail = comparator(live_sections, render_plan)
        except Exception as exc:  # noqa: BLE001
            detail = EngineComparisonDetail(engine=name, error=str(exc))
        engine_details[name] = detail

    successful = [e for e, d in engine_details.items() if d.plan_produced]
    failed = [e for e, d in engine_details.items() if not d.plan_produced]

    alignment_scores = [
        d.section_alignment for d in engine_details.values() if d.plan_produced
    ]
    overall_alignment = (
        sum(alignment_scores) / len(alignment_scores) if alignment_scores else 0.0
    )

    total_errors = sum(d.validation_error_count for d in engine_details.values())
    total_warnings = sum(d.validation_warning_count for d in engine_details.values())

    return ShadowComparisonReport(
        live_section_count=live_count,
        engine_details=engine_details,
        overall_alignment_score=overall_alignment,
        total_validation_errors=total_errors,
        total_validation_warnings=total_warnings,
        failed_engines=failed,
        successful_engines=successful,
    )
