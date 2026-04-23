"""
Render Truth Audit — records what each planning engine contributed and whether
its metadata actually affected the final audio.

Classes
-------
RenderTruthAudit
    Per-arrangement record of engine summaries, resolved plan, applied/skipped
    events, no-op annotations, role mute log, and final section role map.

TransitionSafetyAuditor
    Scans a :class:`~app.services.resolved_render_plan.ResolvedRenderPlan` for
    duplicate boundary events, hard cuts, post-reentry clipping risk, and
    overlapping conflicting events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.resolved_render_plan import ResolvedRenderPlan, ResolvedSection

logger = logging.getLogger(__name__)

# Pairs of event types that conflict when applied to the same section boundary.
_CONFLICTING_EVENT_PAIRS: frozenset[frozenset] = frozenset({
    frozenset({"silence_gap", "drum_fill"}),
    frozenset({"silence_gap", "crash_hit"}),
    frozenset({"pre_hook_silence_drop", "riser_fx"}),
    frozenset({"bass_pause", "subtractive_entry"}),
})

# Event types that can cause audio clipping when applied after re-entry.
_CLIPPING_RISK_AFTER_REENTRY: frozenset[str] = frozenset({
    "re_entry_accent",
    "crash_hit",
    "final_hook_expansion",
    "hook_expansion",
})


# ---------------------------------------------------------------------------
# RenderTruthAudit
# ---------------------------------------------------------------------------


@dataclass
class RenderTruthAudit:
    """Per-arrangement render truth record.

    Attributes
    ----------
    arrangement_id:
        ID of the arrangement being audited.
    engine_summaries:
        Dict mapping engine name to its plan summary dict.
    resolved_plan_summary:
        Compact summary of the :class:`ResolvedRenderPlan` produced by the
        :class:`~app.services.final_plan_resolver.FinalPlanResolver`.
    applied_events:
        Events that were applied and *did* affect final audio.
    skipped_events:
        Events that were planned but *not* applied.
    skipped_reasons:
        Human-readable reasons corresponding to ``skipped_events``.
    noop_annotations:
        Engine metadata that produced no audio change.
    applied_role_mutes:
        List of ``{"section": str, "role": str, "source_engine": str}`` dicts
        recording each role mute/hold-back that was enforced.
    applied_reintroductions:
        List of ``{"section": str, "role": str}`` dicts for role reentries.
    final_section_role_map:
        Resolved active roles per section (after all subtractions/reentries).
    transition_safety_findings:
        Issues found by :class:`TransitionSafetyAuditor`.
    """

    arrangement_id: int
    engine_summaries: Dict[str, Any] = field(default_factory=dict)
    resolved_plan_summary: Dict[str, Any] = field(default_factory=dict)
    applied_events: List[dict] = field(default_factory=list)
    skipped_events: List[dict] = field(default_factory=list)
    skipped_reasons: List[str] = field(default_factory=list)
    noop_annotations: List[dict] = field(default_factory=list)
    applied_role_mutes: List[dict] = field(default_factory=list)
    applied_reintroductions: List[dict] = field(default_factory=list)
    final_section_role_map: Dict[str, List[str]] = field(default_factory=dict)
    transition_safety_findings: List[dict] = field(default_factory=list)

    # ---------------------------------------------------------------------------
    # Factory
    # ---------------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        arrangement_id: int,
        raw_render_plan: Dict[str, Any],
        resolved_plan: ResolvedRenderPlan,
    ) -> "RenderTruthAudit":
        """Produce a :class:`RenderTruthAudit` from the raw plan and resolved plan.

        Parameters
        ----------
        arrangement_id:
            Arrangement being audited.
        raw_render_plan:
            The raw dict as persisted to ``render_plan_json`` (contains the
            ``_*_plan`` shadow results injected by each engine).
        resolved_plan:
            The :class:`ResolvedRenderPlan` produced by
            :class:`~app.services.final_plan_resolver.FinalPlanResolver`.
        """
        audit = cls(arrangement_id=arrangement_id)

        # --- engine summaries ---
        audit.engine_summaries = _extract_engine_summaries(raw_render_plan)

        # --- resolved plan summary ---
        audit.resolved_plan_summary = _build_resolved_plan_summary(resolved_plan)

        # --- role mute / reentry log ---
        for sec in resolved_plan.resolved_sections:
            for role in sec.final_blocked_roles:
                audit.applied_role_mutes.append({
                    "section": sec.section_name,
                    "role": role,
                    "source_engine": "decision",
                })
            for role in sec.final_reentries:
                audit.applied_reintroductions.append({
                    "section": sec.section_name,
                    "role": role,
                })

        # --- applied / skipped events ---
        audit.applied_events, audit.skipped_events, audit.skipped_reasons = (
            _classify_events(raw_render_plan, resolved_plan)
        )

        # --- no-op annotations from resolver ---
        audit.noop_annotations = list(resolved_plan.noop_annotations)

        # --- final section role map ---
        audit.final_section_role_map = resolved_plan.final_section_role_map

        # --- transition safety ---
        safety_auditor = TransitionSafetyAuditor(resolved_plan)
        audit.transition_safety_findings = safety_auditor.audit()

        # Log summary
        logger.info(
            "RENDER_TRUTH_AUDIT [arr=%d] sections=%d applied_events=%d "
            "skipped_events=%d noop_annotations=%d role_mutes=%d "
            "reentries=%d safety_findings=%d",
            arrangement_id,
            resolved_plan.section_count,
            len(audit.applied_events),
            len(audit.skipped_events),
            len(audit.noop_annotations),
            len(audit.applied_role_mutes),
            len(audit.applied_reintroductions),
            len(audit.transition_safety_findings),
        )

        return audit

    def to_dict(self) -> dict:
        return {
            "arrangement_id": self.arrangement_id,
            "engine_summaries": dict(self.engine_summaries),
            "resolved_plan_summary": dict(self.resolved_plan_summary),
            "applied_events": list(self.applied_events),
            "skipped_events": list(self.skipped_events),
            "skipped_reasons": list(self.skipped_reasons),
            "noop_annotations": list(self.noop_annotations),
            "applied_role_mutes": list(self.applied_role_mutes),
            "applied_reintroductions": list(self.applied_reintroductions),
            "final_section_role_map": dict(self.final_section_role_map),
            "transition_safety_findings": list(self.transition_safety_findings),
        }


# ---------------------------------------------------------------------------
# TransitionSafetyAuditor
# ---------------------------------------------------------------------------


class TransitionSafetyAuditor:
    """Scan a resolved plan for transition-safety issues.

    Checks performed:
    1. **Duplicate events**: same event_type applied > 1 time to same boundary.
    2. **Conflicting events**: event_type pairs that cancel each other out.
    3. **Post-reentry clipping risk**: a re_entry_accent / crash_hit appears
       in a section that also has reentries, with no documented gain guard.
    4. **Hard cuts**: sections with blocked roles but no transition event on
       their boundary (silence without a designed ramp).
    """

    def __init__(self, resolved_plan: ResolvedRenderPlan) -> None:
        self._plan = resolved_plan

    def audit(self) -> List[dict]:
        """Run all checks and return a list of finding dicts."""
        findings: List[dict] = []
        findings.extend(self._check_duplicate_boundary_events())
        findings.extend(self._check_conflicting_events())
        findings.extend(self._check_post_reentry_clipping())
        findings.extend(self._check_hard_cuts())
        return findings

    # ------------------------------------------------------------------

    def _check_duplicate_boundary_events(self) -> List[dict]:
        """Catch any boundary event type that appears more than once per section.

        With the resolver deduplication this should normally be empty, but we
        verify the guarantee here so regressions are caught in tests.
        """
        findings: List[dict] = []
        for sec in self._plan.resolved_sections:
            type_counts: Dict[str, int] = {}
            for evt in sec.final_boundary_events:
                type_counts[evt.event_type] = type_counts.get(evt.event_type, 0) + 1
            for evt_type, count in type_counts.items():
                if count > 1:
                    findings.append({
                        "severity": "critical",
                        "check": "duplicate_boundary_event",
                        "section": sec.section_name,
                        "event_type": evt_type,
                        "count": count,
                        "message": (
                            f"event_type '{evt_type}' appears {count} times in "
                            f"section '{sec.section_name}' — double-application will "
                            "produce compound silence or stacked gain"
                        ),
                    })
        return findings

    def _check_conflicting_events(self) -> List[dict]:
        """Detect mutually-exclusive event type pairs on the same boundary."""
        findings: List[dict] = []
        for sec in self._plan.resolved_sections:
            event_types = {evt.event_type for evt in sec.final_boundary_events}
            for pair in _CONFLICTING_EVENT_PAIRS:
                if pair.issubset(event_types):
                    types_str = " + ".join(sorted(pair))
                    findings.append({
                        "severity": "warning",
                        "check": "conflicting_boundary_events",
                        "section": sec.section_name,
                        "event_types": sorted(pair),
                        "message": (
                            f"Conflicting boundary event types [{types_str}] "
                            f"both applied to section '{sec.section_name}'"
                        ),
                    })
        return findings

    def _check_post_reentry_clipping(self) -> List[dict]:
        """Flag sections with reentries AND high-energy boundary events."""
        findings: List[dict] = []
        for sec in self._plan.resolved_sections:
            if not sec.final_reentries:
                continue
            risky_events = [
                evt for evt in sec.final_boundary_events
                if evt.event_type in _CLIPPING_RISK_AFTER_REENTRY
                and evt.intensity >= 0.8
            ]
            if risky_events:
                for evt in risky_events:
                    findings.append({
                        "severity": "warning",
                        "check": "post_reentry_clipping_risk",
                        "section": sec.section_name,
                        "event_type": evt.event_type,
                        "intensity": evt.intensity,
                        "reentries": list(sec.final_reentries),
                        "message": (
                            f"High-intensity '{evt.event_type}' (intensity={evt.intensity:.2f}) "
                            f"applied to section '{sec.section_name}' which also has "
                            f"role reentries {sec.final_reentries} — clipping risk without "
                            "headroom guard"
                        ),
                    })
        return findings

    def _check_hard_cuts(self) -> List[dict]:
        """Detect sections with role subtractions but no designed transition event."""
        findings: List[dict] = []
        for sec in self._plan.resolved_sections:
            if not sec.final_blocked_roles:
                continue
            if sec.final_boundary_events:
                continue  # has a transition — fine
            # Only flag section types that typically warrant a designed entry
            if sec.section_type in {"hook", "pre_hook", "drop", "chorus"}:
                findings.append({
                    "severity": "warning",
                    "check": "hard_cut_no_transition",
                    "section": sec.section_name,
                    "section_type": sec.section_type,
                    "blocked_roles": list(sec.final_blocked_roles),
                    "message": (
                        f"Section '{sec.section_name}' (type={sec.section_type}) has "
                        f"blocked roles {sec.final_blocked_roles} but no boundary transition "
                        "event — this may produce a hard cut with no designed ramp"
                    ),
                })
        return findings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_engine_summaries(raw_plan: Dict[str, Any]) -> Dict[str, Any]:
    """Extract compact summaries of each engine's shadow plan from raw_plan."""
    summaries: Dict[str, Any] = {}

    # Timeline
    timeline_plan = raw_plan.get("_timeline_plan")
    if timeline_plan:
        sections = timeline_plan.get("sections") or []
        summaries["timeline"] = {
            "section_count": len(sections),
            "total_events": sum(len(s.get("events") or []) for s in sections),
            "energy_curve": list(timeline_plan.get("energy_curve") or []),
        }

    # Pattern variation
    pattern_plan = raw_plan.get("_pattern_plan")
    if pattern_plan:
        events = pattern_plan.get("events") or []
        summaries["pattern"] = {
            "event_count": len(events),
            "roles_targeted": _unique_roles_from_events(events, key="role"),
        }

    # Groove
    groove_plan = raw_plan.get("_groove_plan")
    if groove_plan:
        events = groove_plan.get("groove_events") or []
        summaries["groove"] = {
            "event_count": len(events),
            "profile": groove_plan.get("groove_profile_name"),
            "bounce_score": groove_plan.get("bounce_score"),
        }

    # Decision
    decision_plan = raw_plan.get("_decision_plan")
    if decision_plan:
        decisions = decision_plan.get("section_decisions") or []
        summaries["decision"] = {
            "section_count": len(decisions),
            "global_contrast_score": decision_plan.get("global_contrast_score"),
            "payoff_readiness_score": decision_plan.get("payoff_readiness_score"),
            "fallback_used": decision_plan.get("fallback_used", False),
            "sections_with_subtractions": sum(
                1 for d in decisions if d.get("required_subtractions")
            ),
        }

    # Drop
    drop_plan = raw_plan.get("_drop_plan")
    if drop_plan:
        boundaries = drop_plan.get("boundaries") or []
        summaries["drop"] = {
            "boundary_count": len(boundaries),
            "total_drop_count": drop_plan.get("total_drop_count", 0),
            "repeated_hook_variation_score": drop_plan.get(
                "repeated_hook_drop_variation_score"
            ),
        }

    # Motif
    motif_plan = raw_plan.get("_motif_plan")
    if motif_plan:
        motif = motif_plan.get("motif") or {}
        summaries["motif"] = {
            "motif_type": motif.get("motif_type"),
            "source_role": motif.get("source_role"),
            "confidence": motif.get("confidence"),
            "occurrence_count": len(motif_plan.get("occurrences") or []),
            "motif_reuse_score": motif_plan.get("motif_reuse_score"),
            "motif_variation_score": motif_plan.get("motif_variation_score"),
        }

    return summaries


def _build_resolved_plan_summary(resolved: ResolvedRenderPlan) -> Dict[str, Any]:
    return {
        "section_count": resolved.section_count,
        "bpm": resolved.bpm,
        "key": resolved.key,
        "total_bars": resolved.total_bars,
        "source_quality": resolved.source_quality,
        "available_roles": list(resolved.available_roles),
        "total_boundary_events": len(resolved.all_boundary_event_types),
        "sections_with_subtractions": sum(
            1 for s in resolved.resolved_sections if s.final_blocked_roles
        ),
        "sections_with_reentries": sum(
            1 for s in resolved.resolved_sections if s.final_reentries
        ),
        "noop_count": len(resolved.noop_annotations),
    }


def _classify_events(
    raw_plan: Dict[str, Any],
    resolved: ResolvedRenderPlan,
) -> tuple[List[dict], List[dict], List[str]]:
    """Classify all raw plan events as applied or skipped.

    Returns
    -------
    tuple (applied_events, skipped_events, skipped_reasons)
    """
    applied: List[dict] = []
    skipped: List[dict] = []
    reasons: List[str] = []

    # Build lookup: resolved active roles per section name
    resolved_roles_by_section: Dict[str, set] = {
        sec.section_name: set(sec.final_active_roles)
        for sec in resolved.resolved_sections
    }
    resolved_section_names = set(resolved_roles_by_section.keys())

    # Classify raw plan events
    raw_events: List[dict] = list(raw_plan.get("events") or [])
    for evt in raw_events:
        evt_type = str(evt.get("type") or "")
        evt_section = str(evt.get("section_name") or evt.get("section") or "")

        # An event is "applied" if its section exists in the resolved plan
        # and the type was not filtered out.
        if evt_section and evt_section not in resolved_section_names:
            skipped.append(evt)
            reasons.append(f"section '{evt_section}' not found in resolved plan")
        elif not evt_type:
            skipped.append(evt)
            reasons.append("event_type is empty")
        else:
            applied.append(evt)

    # Classify decision engine subtractions that had no matching role
    for annotation in resolved.noop_annotations:
        skipped.append({
            "engine": annotation.get("engine_name"),
            "section": annotation.get("section"),
            "action": annotation.get("planned_action"),
        })
        reasons.append(str(annotation.get("reason_not_applied") or "no-op"))

    return applied, skipped, reasons


def _unique_roles_from_events(events: List[dict], key: str = "role") -> List[str]:
    seen: set = set()
    out: List[str] = []
    for evt in events:
        role = str(evt.get(key) or "")
        if role and role not in seen:
            seen.add(role)
            out.append(role)
    return out
