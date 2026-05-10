"""Phase 3 render observability helpers.

Assembles the ``render_metadata`` dict that is persisted on every ``RenderJob``
record so every job can answer:

  1. What render path was actually used
  2. What stems/roles were rendered per section
  3. Did fallback occur, and why
  4. Was mastering applied
  5. Was the job truly successful or degraded

All values reflect REAL execution — nothing is fabricated.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_PHRASE_MUTATION_EVENTS = {
    "call_response_variation", "chop_stutter", "reverse_slice", "rhythmic_gate",
    "dropout_bar", "chop", "chop_role",
}
_HOOK_ESCALATION_EVENTS = {
    "final_hook_expansion", "stereo_widen", "transient_boost", "octave_layer",
    "hook_drum_density", "re_entry_accent", "add_impact", "widen_role",
}
_TRANSITION_OVERLAP_EVENTS = {
    "crossfade", "reverse_fx", "transition_delay_tail", "transition_riser_overlap",
    "transition_reverb_tail", "reverb_tail", "delay_role",
}


def recompute_producer_metrics_from_execution_report(
    section_execution_report: list[dict],
    actual_stem_map_by_section: list[dict],
    render_signatures: list[str],
) -> dict[str, Any]:
    logger.info("METRIC_RECOMPUTE_STARTED sections=%d", len(section_execution_report or []))
    role_by_index = {
        int(sec.get("section_index", idx)): list(sec.get("roles") or [])
        for idx, sec in enumerate(actual_stem_map_by_section or [])
    }
    phrase_mutation_count = 0
    transition_overlap_count = 0
    hook_stages: list[str] = []
    transition_styles: list[str] = []
    role_sets: set[tuple[str, ...]] = set()
    section_types: list[str] = []
    energy_curve: list[float] = []
    all_event_types: set[str] = set()
    personality_values: set[str] = set()

    evidence_found = {"mutation": False, "hook": False, "overlap": False}
    for idx, sec in enumerate(section_execution_report or []):
        sec_type = str(sec.get("section_type") or sec.get("type") or "unknown")
        section_types.append(sec_type)
        events = [str(e).strip().lower() for e in (sec.get("applied_events") or [])]
        event_set = set(events)
        all_event_types.update(event_set)
        personality = str(sec.get("variation_personality") or "").strip().lower()
        if personality:
            personality_values.add(personality)

        mutation_hit = bool(event_set & _PHRASE_MUTATION_EVENTS)
        if mutation_hit or bool(sec.get("phrase_split_used")) or bool(sec.get("phrase_plan_used")):
            phrase_mutation_count += 1
            evidence_found["mutation"] = True
            logger.info("PHRASE_MUTATION_EVIDENCE_FOUND section_index=%d section_type=%s", idx, sec_type)

        overlap_hit = event_set & _TRANSITION_OVERLAP_EVENTS
        if overlap_hit:
            transition_overlap_count += len(overlap_hit)
            transition_styles.extend(sorted(overlap_hit))
            evidence_found["overlap"] = True
            logger.info("TRANSITION_OVERLAP_EVIDENCE_FOUND section_index=%d events=%s", idx, sorted(overlap_hit))

        if sec_type in {"hook", "hook_2", "final_hook"} or (event_set & _HOOK_ESCALATION_EVENTS):
            hook_stages.append(sec_type)
            evidence_found["hook"] = True
            if event_set & _HOOK_ESCALATION_EVENTS:
                logger.info("HOOK_ESCALATION_EVIDENCE_FOUND section_index=%d events=%s", idx, sorted(event_set & _HOOK_ESCALATION_EVENTS))

        roles = sorted(role_by_index.get(idx) or sec.get("actual_roles") or sec.get("runtime_active_stems") or sec.get("active_stem_roles") or [])
        role_sets.add(tuple(roles))
        stem_density = len(roles)
        event_intensity = len(event_set & (_PHRASE_MUTATION_EVENTS | _HOOK_ESCALATION_EVENTS | _TRANSITION_OVERLAP_EVENTS))
        section_boost = 0.35 if sec_type.startswith("hook") else (0.2 if sec_type == "bridge" else 0.1)
        energy_curve.append(round(stem_density + (event_intensity * 0.4) + section_boost, 3))

    logger.info("OBSERVABILITY_EVENT_EVIDENCE_EXTRACTED sections=%d events=%d", len(section_execution_report or []), len(all_event_types))
    logger.info("METRIC_RECOMPUTE_EVIDENCE_FOUND mutation=%s hook=%s overlap=%s", evidence_found["mutation"], evidence_found["hook"], evidence_found["overlap"])
    logger.info("ENERGY_CURVE_RECOMPUTED values=%s", energy_curve)

    uniq_signatures = len(set(render_signatures))
    role_change_ratio = len(role_sets) / max(1, len(section_execution_report or []))
    transition_diversity = len(set(transition_styles)) / 7.0
    uniqueness_score = round(min(1.0, (uniq_signatures / max(1, len(section_execution_report or []))) * 0.4 + min(1.0, len(all_event_types) / 10.0) * 0.25 + role_change_ratio * 0.15 + min(1.0, len(personality_values) / 3.0) * 0.1 + min(1.0, transition_diversity) * 0.1), 3)
    logger.info("VARIATION_UNIQUENESS_RECOMPUTED score=%.3f", uniqueness_score)

    energy_span = (max(energy_curve) - min(energy_curve)) if energy_curve else 0.0
    bridge_contrast = 1.0 if ("bridge" in section_types and any(s.startswith("hook") for s in section_types)) else 0.0
    final_score = round(min(1.0, min(1.0, phrase_mutation_count / max(1, len(section_execution_report or []))) * 0.2 + (0.2 if hook_stages else 0.0) + (0.15 if transition_overlap_count > 0 else 0.0) + min(1.0, energy_span / 3.0) * 0.2 + uniqueness_score * 0.2 + bridge_contrast * 0.05), 3)
    logger.info("FINAL_PRODUCER_SCORE_RECOMPUTED score=%.3f", final_score)
    result = {
        "phrase_split_count": phrase_mutation_count,
        "hook_stages_rendered": sorted(set(hook_stages)),
        "transition_overlap_rendered": transition_overlap_count > 0,
        "transition_overlap_rendered_count": transition_overlap_count,
        "variation_energy_curve": energy_curve or [0.0],
        "variation_uniqueness_score": uniqueness_score,
        "hook_escalation_applied": bool(hook_stages and any(s in {"hook", "hook_2", "final_hook"} for s in hook_stages)),
        "final_producer_score": final_score,
        "variation_transition_style": sorted(set(transition_styles)),
    }
    logger.info("METRIC_RECOMPUTE_APPLIED phrase_split_count=%d hook_escalation=%s overlap_count=%d uniqueness=%.3f final_score=%.3f", result["phrase_split_count"], result["hook_escalation_applied"], result["transition_overlap_rendered_count"], result["variation_uniqueness_score"], result["final_producer_score"])
    return result


def _recompute_producer_metrics(timeline_sections: list[dict], render_signatures: list[str]) -> dict[str, Any]:
    """Compatibility wrapper: delegates to recompute_producer_metrics_from_execution_report."""
    return recompute_producer_metrics_from_execution_report(timeline_sections, [], render_signatures)

# ---------------------------------------------------------------------------
# Terminal state determination
# ---------------------------------------------------------------------------

def determine_job_terminal_state(
    success: bool,
    fallback_triggered_count: int,
    failure_stage: Optional[str],
    error_message: Optional[str],
) -> str:
    """Map execution outcome to a typed terminal state.

    Returns one of:
      success_truthful         — completed with no fallbacks
      success_with_fallbacks   — completed but some sections used fallback paths
      failed_timeout           — job exceeded wall-clock timeout
      failed_executor          — exception during audio rendering/execution
      failed_storage           — exception during upload/storage
      failed_mastering         — exception during mastering stage
      failed_plan_validation   — render plan failed quality validation
      failed_unknown           — any other failure
    """
    if not success:
        if failure_stage == "storage":
            return "failed_storage"
        if failure_stage == "mastering":
            return "failed_mastering"
        if failure_stage == "render_plan":
            return "failed_plan_validation"
        if failure_stage == "execution":
            return "failed_executor"
        # Try to infer from error message text
        err = str(error_message or "").lower()
        if "timeout" in err:
            return "failed_timeout"
        if "storage" in err or "s3" in err or "upload" in err:
            return "failed_storage"
        if "mastering" in err:
            return "failed_mastering"
        if "render_plan" in err or "plan" in err:
            return "failed_plan_validation"
        if failure_stage:
            return f"failed_{failure_stage}"
        return "failed_unknown"

    if fallback_triggered_count > 0:
        return "success_with_fallbacks"
    return "success_truthful"


# ---------------------------------------------------------------------------
# Worker mode detection
# ---------------------------------------------------------------------------

def get_worker_mode() -> str:
    """Return the worker topology for this process.

    embedded — RQ worker threads are embedded in the same web process
                (ENABLE_EMBEDDED_RQ_WORKER=true)
    external — a dedicated ``python -m app.workers.main`` process
    unknown  — cannot determine
    """
    try:
        if settings.enable_embedded_rq_worker:
            return "embedded"
        return "external"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Feature flags snapshot
# ---------------------------------------------------------------------------

def resolve_feature_flags_snapshot() -> dict[str, Any]:
    """Return a compact snapshot of all render-relevant feature flags.

    This is written once per job so post-incident debugging can reconstruct
    exactly which flags were active when the job ran.
    """
    flag_attrs = [
        "feature_producer_engine",
        "feature_producer_engine_v2",
        "feature_producer_section_identity_v2",
        "feature_section_choreography_v2",
        "feature_source_quality_modes",
        "feature_arrangement_quality_gates",
        "feature_arrangement_plan_v2",
        "feature_arrangement_memory_v2",
        "feature_arrangement_transitions_v2",
        "feature_arrangement_truth_observability_v2",
        "feature_stem_separation",
        "feature_advanced_stem_separation_v2",
        "feature_mastering_stage",
        "enable_embedded_rq_worker",
        "feature_ai_producer_assist",
        "feature_ai_style_interpretation",
        "feature_llm_style_parsing",
        "feature_reference_guided_arrangement",
        "feature_reference_section_analysis",
        "dev_fallback_loop_only",
    ]
    snapshot: dict[str, Any] = {}
    for attr in flag_attrs:
        try:
            snapshot[attr] = getattr(settings, attr)
        except Exception:
            snapshot[attr] = None
    return snapshot


# ---------------------------------------------------------------------------
# Observability extraction from arrangement timeline
# ---------------------------------------------------------------------------

def extract_observability_from_arrangement(arrangement_row: Any) -> dict[str, Any]:
    """Extract Phase 3 observability fields from a completed arrangement row.

    Reads ``arrangement_json`` (which contains the ``render_spec_summary`` and
    per-section ``runtime_active_stems`` written by ``_render_producer_arrangement``)
    and ``render_plan_json`` (which contains the planned stem maps).

    Returns a partial render_observability dict.  Fields that require runtime
    data from ``render_executor.render_from_plan`` (mastering, render_path_used)
    are not populated here — they must be merged in by the caller.
    """
    import hashlib

    timeline: dict = {}
    render_plan_sections: list = []

    if getattr(arrangement_row, "arrangement_json", None):
        try:
            raw = json.loads(arrangement_row.arrangement_json)
            if isinstance(raw, dict):
                timeline = raw
        except Exception as exc:
            logger.warning("extract_observability: failed to parse arrangement_json: %s", exc)

    if getattr(arrangement_row, "render_plan_json", None):
        try:
            rp = json.loads(arrangement_row.render_plan_json)
            if isinstance(rp, dict):
                render_plan_sections = rp.get("sections") or []
        except Exception as exc:
            logger.warning("extract_observability: failed to parse render_plan_json: %s", exc)

    timeline_sections: list = timeline.get("sections") or []
    render_spec: dict = timeline.get("render_spec_summary") or {}

    phrase_split_count = int(render_spec.get("phrase_split_count") or 0)
    distinct_stem_set_count = int(render_spec.get("distinct_stem_set_count") or 0)
    hook_stages_rendered = list(render_spec.get("hook_stages") or [])
    transition_event_count = int(render_spec.get("transition_event_count") or 0)
    variation_uniqueness_score = float(render_spec.get("variation_uniqueness_score") or 0.0)
    variation_energy_curve = list(render_spec.get("variation_energy_curve") or [])
    variation_transition_style = list(render_spec.get("variation_transition_style") or [])
    producer_memory_state = dict(render_spec.get("producer_memory_state") or {})
    event_repetition_score = float(render_spec.get("event_repetition_score") or 0.0)
    section_similarity_score = float(render_spec.get("section_similarity_score") or 0.0)
    transition_overlap_rendered = bool(render_spec.get("transition_overlap_rendered"))
    hook_escalation_applied = bool(render_spec.get("hook_escalation_applied"))
    final_producer_score = float(render_spec.get("final_producer_score") or 0.0)

    # Planned stem map from render_plan_json
    planned_stem_map: list[dict] = []
    for idx, sec in enumerate(render_plan_sections):
        planned_stem_map.append({
            "section_index": idx,
            "section_type": str(sec.get("type") or sec.get("section_type") or "unknown"),
            "roles": list(sec.get("instruments") or sec.get("active_stem_roles") or []),
        })

    # Actual stem map + section execution report from timeline
    actual_stem_map: list[dict] = []
    section_execution_report: list[dict] = []
    fallback_triggered_count = 0
    fallback_reasons: list[str] = []
    render_signatures: list[str] = []

    for idx, ts in enumerate(timeline_sections):
        actual_roles = list(ts.get("runtime_active_stems") or ts.get("active_stem_roles") or [])
        planned_roles = list(ts.get("active_stem_roles") or [])

        # If runtime and planned differ that signals fallback
        sec_fallback = bool(ts.get("_stem_fallback_all"))
        fallback_used = sec_fallback
        fallback_reason = ""
        if sec_fallback:
            fallback_triggered_count += 1
            fallback_reason = "missing_required_stem_role"
            if fallback_reason not in fallback_reasons:
                fallback_reasons.append(fallback_reason)

        dropped_roles = [r for r in planned_roles if r not in actual_roles]
        if dropped_roles and "missing_required_stem_role" not in fallback_reasons:
            fallback_reasons.append("missing_required_stem_role")

        sig_material = "|".join(sorted(actual_roles)) + f"|{ts.get('type', '')}"
        sig = hashlib.md5(sig_material.encode()).hexdigest()[:12]
        render_signatures.append(sig)

        actual_stem_map.append({
            "section_index": idx,
            "section_type": str(ts.get("type") or "unknown"),
            "roles": actual_roles,
            "fallback": fallback_used,
        })
        section_execution_report.append({
            "section_index": idx,
            "section_type": str(ts.get("type") or "unknown"),
            "planned_roles": planned_roles,
            "actual_roles": actual_roles,
            "dropped_roles": dropped_roles,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason or None,
            "phrase_split_used": bool(ts.get("phrase_plan_used")),
            "render_signature": sig,
            "applied_events": list(ts.get("applied_events") or []),
        })

    unique_render_signature_count = len(set(render_signatures))

    recomputed = recompute_producer_metrics_from_execution_report(section_execution_report, actual_stem_map, render_signatures)
    return {
        "fallback_triggered_count": fallback_triggered_count,
        "fallback_sections_count": fallback_triggered_count,
        "fallback_reasons": fallback_reasons,
        "planned_stem_map_by_section": planned_stem_map,
        "actual_stem_map_by_section": actual_stem_map,
        "section_execution_report": section_execution_report,
        "render_signatures": render_signatures,
        "unique_render_signature_count": unique_render_signature_count,
        "phrase_split_count": max(phrase_split_count, int(recomputed["phrase_split_count"])),
        "distinct_stem_set_count": distinct_stem_set_count or unique_render_signature_count,
        "hook_stages_rendered": hook_stages_rendered or recomputed["hook_stages_rendered"],
        "transition_event_count": transition_event_count,
        "variation_uniqueness_score": max(variation_uniqueness_score, float(recomputed["variation_uniqueness_score"])),
        "variation_energy_curve": variation_energy_curve or recomputed["variation_energy_curve"],
        "variation_transition_style": variation_transition_style or recomputed["variation_transition_style"],
        "producer_memory_state": producer_memory_state,
        "event_repetition_score": event_repetition_score,
        "section_similarity_score": section_similarity_score,
        "transition_overlap_rendered": transition_overlap_rendered or bool(recomputed["transition_overlap_rendered"]),
        "transition_overlap_rendered_count": int(recomputed["transition_overlap_rendered_count"]),
        "hook_escalation_applied": hook_escalation_applied or bool(recomputed["hook_escalation_applied"]),
        "final_producer_score": max(final_producer_score, float(recomputed["final_producer_score"])),
    }


# ---------------------------------------------------------------------------
# Section occurrence info extractor (V2 observability)
# ---------------------------------------------------------------------------

def extract_section_occurrence_info(
    arrangement_plan_v2_dict: dict | None,
) -> dict:
    """Summarise section occurrence info from an ArrangementPlanV2 dict.

    Returns a dict with:
    - ``occurrence_counts``: {section_type: count}
    - ``repeated_sections``: list of section types that appear more than once
    - ``total_sections``: total section count in the plan
    - ``unique_section_types``: sorted list of distinct section types
    """
    if not arrangement_plan_v2_dict:
        return {}

    sections = arrangement_plan_v2_dict.get("sections", [])
    occurrence_counts: dict[str, int] = {}
    for sec in sections:
        stype = sec.get("section_type", "unknown")
        occurrence_counts[stype] = occurrence_counts.get(stype, 0) + 1

    repeated = sorted(k for k, v in occurrence_counts.items() if v > 1)
    return {
        "occurrence_counts": occurrence_counts,
        "repeated_sections": repeated,
        "total_sections": len(sections),
        "unique_section_types": sorted(occurrence_counts.keys()),
    }


def _compute_plan_vs_actual_match(
    planned: list[dict],
    actual: list[dict],
) -> Optional[float]:
    """Compute fraction of sections where planned roles exactly match actual roles.

    Returns a 0.0–1.0 float, or None when either list is empty.
    """
    if not planned or not actual:
        return None
    min_len = min(len(planned), len(actual))
    matches = sum(
        1
        for i in range(min_len)
        if set(planned[i].get("roles", [])) == set(actual[i].get("roles", []))
    )
    return round(matches / min_len, 3)


# ---------------------------------------------------------------------------
# Full metadata assembly
# ---------------------------------------------------------------------------

def assemble_render_metadata(
    *,
    worker_mode: str,
    job_terminal_state: str,
    failure_stage: Optional[str],
    render_path_used: str,
    source_quality_mode_used: str,
    observability: dict[str, Any],
    mastering_info: Optional[dict[str, Any]] = None,
    feature_flags_snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble the complete render_metadata payload for persistence.

    Merges worker-level context (worker_mode, terminal_state, failure_stage)
    with execution-level observability (stem maps, fallbacks, signatures).
    """
    metadata: dict[str, Any] = {
        "worker_mode": worker_mode,
        "job_terminal_state": job_terminal_state,
        "failure_stage": failure_stage,
        "render_path_used": render_path_used,
        "source_quality_mode_used": source_quality_mode_used,
        # Fallback tracking
        "fallback_triggered_count": observability.get("fallback_triggered_count", 0),
        "fallback_sections_count": observability.get("fallback_sections_count", 0),
        "fallback_reasons": observability.get("fallback_reasons", []),
        # Stem maps
        "planned_stem_map_by_section": observability.get("planned_stem_map_by_section", []),
        "actual_stem_map_by_section": observability.get("actual_stem_map_by_section", []),
        # Section execution detail
        "section_execution_report": observability.get("section_execution_report", []),
        # Render signatures
        "render_signatures": observability.get("render_signatures", []),
        "unique_render_signature_count": observability.get("unique_render_signature_count", 0),
        "phrase_split_count": observability.get("phrase_split_count", 0),
        "distinct_stem_set_count": observability.get("distinct_stem_set_count", 0),
        "hook_stages_rendered": observability.get("hook_stages_rendered", []),
        "transition_event_count": observability.get("transition_event_count", 0),
        "variation_uniqueness_score": observability.get("variation_uniqueness_score", 0.0),
        "variation_energy_curve": observability.get("variation_energy_curve", []),
        "variation_transition_style": observability.get("variation_transition_style", []),
        "producer_memory_state": observability.get("producer_memory_state", {}),
        "event_repetition_score": observability.get("event_repetition_score", 0.0),
        "section_similarity_score": observability.get("section_similarity_score", 0.0),
        "transition_overlap_rendered": observability.get("transition_overlap_rendered", False),
        "transition_overlap_rendered_count": observability.get("transition_overlap_rendered_count", 0),
        "hook_escalation_applied": observability.get("hook_escalation_applied", False),
        "final_producer_score": observability.get("final_producer_score", 0.0),
    }

    if mastering_info:
        metadata["mastering_applied"] = bool(mastering_info.get("applied"))
        metadata["mastering_profile"] = mastering_info.get("profile")
        metadata["mastering_peak_dbfs_before"] = mastering_info.get("peak_dbfs_before")
        metadata["mastering_peak_dbfs_after"] = mastering_info.get("peak_dbfs_after")
    else:
        metadata["mastering_applied"] = observability.get("mastering_applied")
        metadata["mastering_profile"] = observability.get("mastering_profile")

    if feature_flags_snapshot is not None:
        metadata["feature_flags_snapshot"] = feature_flags_snapshot

    # V2 observability fields (populated when ARRANGEMENT_TRUTH_OBSERVABILITY_V2=true).
    if observability.get("arrangement_plan_v2"):
        metadata["arrangement_plan_v2"] = observability["arrangement_plan_v2"]
    if observability.get("plan_vs_actual_comparison"):
        metadata["plan_vs_actual_comparison"] = observability["plan_vs_actual_comparison"]
    if observability.get("section_occurrence_info"):
        metadata["section_occurrence_info"] = observability["section_occurrence_info"]
    if observability.get("source_quality_mode"):
        metadata["source_quality_mode"] = observability["source_quality_mode"]

    # AI planning observability fields.
    for ai_key in (
        "ai_plan_raw",
        "ai_plan_rejected_reason",
        "ai_section_deltas",
        "ai_novelty_score",
    ):
        if ai_key in observability:
            metadata[ai_key] = observability[ai_key]

    # Compute plan-vs-actual match if not already supplied.
    if "ai_plan_vs_actual_match" in observability:
        metadata["ai_plan_vs_actual_match"] = observability["ai_plan_vs_actual_match"]
    else:
        computed = _compute_plan_vs_actual_match(
            observability.get("planned_stem_map_by_section", []),
            observability.get("actual_stem_map_by_section", []),
        )
        if computed is not None:
            metadata["ai_plan_vs_actual_match"] = computed

    return metadata
