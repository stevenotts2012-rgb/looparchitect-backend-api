"""
Production Quality Auditor — end-to-end audio quality audit for LoopArchitect.

Investigates why arrangements still sound repetitive or weak even when the
resolved plan architecture is enabled.  Consumes a
:class:`~app.services.resolved_render_plan.ResolvedRenderPlan` (or raw render
plan dict) and produces a single ``production_quality_report`` dict.

Audit areas
-----------
1. **Resolved plan enforcement** — verifies that final_active_roles actually
   differ between sections, final_blocked_roles are muted, final_boundary_events
   are applied exactly once, and pattern/groove events are non-empty where
   expected.  Flags metadata-only events (events that carry no audio payload).

2. **Trap arrangement quality** — checks the structural arc expected from a
   quality trap arrangement: intro sparse → verse restrained → pre-hook
   subtracts kick/anchor → hook fullest → verse-2 differs from verse-1 →
   hook-2 differs from hook-1 → outro removes 808/drums.

3. **Repetition analysis** — detects sections that share the same active roles,
   density, boundary events, motif treatment, and drum/bass behavior.

4. **Impact analysis** — scores pre-hook tension, hook payoff, drop event
   strength, re-entry strength, and whether any drop is too short or subtle.

5. **Distortion / transition safety** — re-exposes and extends
   :class:`~app.services.render_truth_audit.TransitionSafetyAuditor`: hard
   cuts, clipping risk, duplicated events, overlapping boundary effects,
   missing fade/crossfade, gain-after-reentry.

Output
------
``ProductionQualityAuditor.audit()`` returns a ``production_quality_report``
dict with::

    repetition_score          float [0,1]  – 1 = fully unique sections
    contrast_score            float [0,1]  – 1 = maximum contrast
    hook_payoff_score         float [0,1]  – 1 = hooks deliver full uplift
    transition_safety_score   float [0,1]  – 1 = no safety issues
    no_op_event_count         int          – events with no audio payload
    render_mismatch_count     int          – blocked roles still active / other mismatches
    weak_sections             list[str]    – section names with quality issues
    recommended_fixes         list[str]    – human-readable fix descriptions
    section_audits            list[dict]   – per-section detail
    trap_structure_issues     list[str]    – trap-arc violations
    repetition_groups         list[dict]   – groups of repeated section fingerprints
    impact_scores             dict         – per-category impact scores
    safety_findings           list[dict]   – transition/distortion safety findings
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from app.services.resolved_render_plan import ResolvedRenderPlan, ResolvedSection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Section types that should always block 808/bass/drums in outro
_OUTRO_STRIP_ROLES: FrozenSet[str] = frozenset({"808", "bass", "drums", "kick"})

# Roles considered "anchor" roles for pre-hook subtraction check
_ANCHOR_ROLES: FrozenSet[str] = frozenset({"drums", "kick", "808", "bass"})

# Section types treated as the climax/hook
_HOOK_TYPES: FrozenSet[str] = frozenset({"hook", "chorus"})

# Section types treated as build-up
_PRE_HOOK_TYPES: FrozenSet[str] = frozenset({"pre_hook", "pre-hook", "buildup", "build"})

# Minimum density difference required to say two instances of the same section
# type "differ" (i.e. verse 2 must not match verse 1 exactly)
_DENSITY_DIFF_THRESHOLD: int = 1  # at least 1 role must differ

# Impact thresholds
_MIN_DROP_INTENSITY: float = 0.60   # drop event intensity considered "strong"
_MIN_PRE_HOOK_BLOCKS: int = 1       # pre-hook must block at least 1 anchor role
_MIN_HOOK_ENERGY: float = 0.75      # hooks must reach this energy level

# Re-entry: maximum bars for a drop section to qualify as "long enough"
_MIN_DROP_BARS: int = 4

# Transition safety: event types that require a fade or crossfade counterpart
_FADE_REQUIRED_EVENTS: FrozenSet[str] = frozenset({
    "silence_gap", "pre_hook_silence_drop", "bass_pause",
})


# ---------------------------------------------------------------------------
# Section fingerprinting (for repetition detection)
# ---------------------------------------------------------------------------


def _section_fingerprint(sec: ResolvedSection) -> dict:
    """Return a hashable fingerprint of a section's audible content."""
    boundary_types = tuple(sorted(e.event_type for e in sec.final_boundary_events))
    motif_type = (
        sec.final_motif_treatment.get("motif_type")
        if sec.final_motif_treatment
        else None
    )
    drum_roles = tuple(sorted(r for r in sec.final_active_roles if "drum" in r or "kick" in r))
    bass_roles = tuple(sorted(r for r in sec.final_active_roles if "bass" in r or "808" in r))
    return {
        "active_roles": tuple(sorted(sec.final_active_roles)),
        "density": len(sec.final_active_roles),
        "energy_bucket": round(sec.energy * 4) / 4,   # quantise to 0.25 buckets
        "boundary_types": boundary_types,
        "motif_type": motif_type,
        "drum_roles": drum_roles,
        "bass_roles": bass_roles,
    }


def _fingerprint_key(fp: dict) -> tuple:
    """Convert fingerprint dict to a hashable key."""
    return (
        fp["active_roles"],
        fp["density"],
        fp["energy_bucket"],
        fp["boundary_types"],
        fp["motif_type"],
        fp["drum_roles"],
        fp["bass_roles"],
    )


# ---------------------------------------------------------------------------
# Main auditor class
# ---------------------------------------------------------------------------


class ProductionQualityAuditor:
    """Run a full production-quality audit on a :class:`ResolvedRenderPlan`.

    Parameters
    ----------
    resolved_plan:
        The canonical resolved render plan produced by
        :class:`~app.services.final_plan_resolver.FinalPlanResolver`.
    raw_render_plan:
        Optional raw render plan dict (used to cross-check no-op events and
        render mismatches).
    arrangement_id:
        Used only for log messages.
    """

    def __init__(
        self,
        resolved_plan: ResolvedRenderPlan,
        raw_render_plan: Optional[Dict[str, Any]] = None,
        arrangement_id: int = 0,
    ) -> None:
        self._resolved = resolved_plan
        self._raw = raw_render_plan or {}
        self._arrangement_id = arrangement_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def audit(self) -> dict:
        """Run all audit checks and return the production_quality_report dict."""
        sections = self._resolved.resolved_sections

        # 1. Resolved plan enforcement
        no_op_count, noop_details = self._count_no_op_events()
        mismatch_count, mismatch_details = self._count_render_mismatches()

        # 2. Trap arrangement quality
        trap_issues = self._check_trap_structure(sections)

        # 3. Repetition analysis
        repetition_score, repetition_groups = self._analyze_repetition(sections)

        # 4. Impact analysis
        impact_scores = self._analyze_impact(sections)

        # 5. Section-level audits
        section_audits = [self._audit_section(sec) for sec in sections]

        # 6. Transition / distortion safety
        safety_findings = self._check_transition_safety(sections)
        transition_safety_score = self._score_transition_safety(safety_findings)

        # 7. Contrast score
        contrast_score = self._score_contrast(sections)

        # 8. Hook payoff score
        hook_payoff_score = impact_scores.get("hook_payoff", 0.0)

        # 9. Aggregate weak sections
        weak_sections = self._find_weak_sections(section_audits, trap_issues)

        # 10. Recommended fixes
        recommended_fixes = self._build_recommended_fixes(
            trap_issues=trap_issues,
            repetition_groups=repetition_groups,
            impact_scores=impact_scores,
            safety_findings=safety_findings,
            noop_details=noop_details,
            mismatch_details=mismatch_details,
        )

        report = {
            "repetition_score": round(repetition_score, 4),
            "contrast_score": round(contrast_score, 4),
            "hook_payoff_score": round(hook_payoff_score, 4),
            "transition_safety_score": round(transition_safety_score, 4),
            "no_op_event_count": no_op_count,
            "render_mismatch_count": mismatch_count,
            "weak_sections": weak_sections,
            "recommended_fixes": recommended_fixes,
            "section_audits": section_audits,
            "trap_structure_issues": trap_issues,
            "repetition_groups": repetition_groups,
            "impact_scores": impact_scores,
            "safety_findings": safety_findings,
        }

        logger.info(
            "PRODUCTION_QUALITY_AUDIT [arr=%d] sections=%d repetition=%.2f "
            "contrast=%.2f hook_payoff=%.2f safety=%.2f noops=%d mismatches=%d "
            "weak_sections=%d fixes=%d",
            self._arrangement_id,
            len(sections),
            repetition_score,
            contrast_score,
            hook_payoff_score,
            transition_safety_score,
            no_op_count,
            mismatch_count,
            len(weak_sections),
            len(recommended_fixes),
        )

        return report

    # ------------------------------------------------------------------
    # 1. Resolved plan enforcement
    # ------------------------------------------------------------------

    def _count_no_op_events(self) -> Tuple[int, List[dict]]:
        """Count events that exist only as metadata and carry no audio payload.

        A no-op event is one where:
        - a boundary_event type is in noop_annotations (duplicate/phantom), OR
        - a pattern_event or groove_event has an empty or unknown action, OR
        - a blocked role was not in the section's base roles (phantom block).
        """
        no_ops: List[dict] = []

        # From resolver noop_annotations (phantom blocks, duplicate boundaries)
        for ann in self._resolved.noop_annotations:
            no_ops.append({
                "type": "resolver_noop",
                "engine": ann.get("engine_name", ""),
                "section": ann.get("section", ""),
                "action": ann.get("planned_action", ""),
                "reason": ann.get("reason_not_applied", ""),
            })

        # Pattern events with empty action
        for sec in self._resolved.resolved_sections:
            for evt in sec.final_pattern_events:
                action = str(evt.get("action") or evt.get("type") or "").strip()
                if not action:
                    no_ops.append({
                        "type": "empty_pattern_event",
                        "engine": "pattern_variation",
                        "section": sec.section_name,
                        "action": "(empty)",
                        "reason": "pattern event has no action — no audio change",
                    })

            # Groove events with empty type
            for evt in sec.final_groove_events:
                gtype = str(evt.get("groove_type") or evt.get("type") or "").strip()
                if not gtype:
                    no_ops.append({
                        "type": "empty_groove_event",
                        "engine": "groove",
                        "section": sec.section_name,
                        "action": "(empty)",
                        "reason": "groove event has no type — no audio change",
                    })

        return len(no_ops), no_ops

    def _count_render_mismatches(self) -> Tuple[int, List[dict]]:
        """Detect cases where the resolved plan says a role is blocked but it
        still appears in the raw section's instrument list (render bypassed the plan).
        """
        mismatches: List[dict] = []
        raw_sections: List[dict] = list(self._raw.get("sections") or [])
        raw_by_name: Dict[str, dict] = {
            str(s.get("name") or s.get("type") or ""): s
            for s in raw_sections
        }

        for sec in self._resolved.resolved_sections:
            raw = raw_by_name.get(sec.section_name)
            if raw is None:
                continue
            raw_instruments = set(
                str(r).lower()
                for r in (raw.get("instruments") or raw.get("active_stem_roles") or [])
            )
            # A mismatch: a blocked role still in raw instruments list means
            # the renderer may have ignored the resolved plan
            for blocked in sec.final_blocked_roles:
                if blocked.lower() in raw_instruments:
                    mismatches.append({
                        "section": sec.section_name,
                        "blocked_role": blocked,
                        "reason": (
                            f"role '{blocked}' is final_blocked but still present in "
                            "raw section instruments — renderer may bypass resolved plan"
                        ),
                    })

            # A mismatch: a reentry role not in raw instruments or active roles
            for reentry in sec.final_reentries:
                if reentry.lower() not in raw_instruments and reentry not in sec.final_active_roles:
                    mismatches.append({
                        "section": sec.section_name,
                        "reentry_role": reentry,
                        "reason": (
                            f"role '{reentry}' is a final_reentry but absent from "
                            "both raw instruments and final_active_roles"
                        ),
                    })

        return len(mismatches), mismatches

    # ------------------------------------------------------------------
    # 2. Trap arrangement quality
    # ------------------------------------------------------------------

    def _check_trap_structure(self, sections: List[ResolvedSection]) -> List[str]:
        """Check whether the arrangement follows the expected trap arc."""
        issues: List[str] = []
        by_type: Dict[str, List[ResolvedSection]] = {}
        for sec in sections:
            by_type.setdefault(sec.section_type, []).append(sec)

        # Intro should be sparse (≤ 2 active roles or lower energy)
        for sec in by_type.get("intro", []):
            if len(sec.final_active_roles) > 3:
                issues.append(
                    f"Intro '{sec.section_name}' is too full "
                    f"({len(sec.final_active_roles)} active roles — expected ≤ 3 for sparse intro)"
                )
            if sec.energy > 0.55:
                issues.append(
                    f"Intro '{sec.section_name}' energy {sec.energy:.2f} is too high "
                    f"(expected ≤ 0.55 for restrained intro)"
                )

        # Verse should be restrained (not as full as hook)
        hook_sections = [
            s for stype in _HOOK_TYPES for s in by_type.get(stype, [])
        ]
        verse_sections = by_type.get("verse", [])
        if hook_sections and verse_sections:
            avg_hook_density = sum(len(s.final_active_roles) for s in hook_sections) / len(hook_sections)
            for sec in verse_sections:
                if len(sec.final_active_roles) >= avg_hook_density:
                    issues.append(
                        f"Verse '{sec.section_name}' has {len(sec.final_active_roles)} roles "
                        f"(≥ avg hook density {avg_hook_density:.1f}) — verse should be more restrained"
                    )

        # Pre-hook must subtract at least one anchor (kick/808/bass) role
        for stype in _PRE_HOOK_TYPES:
            for sec in by_type.get(stype, []):
                blocked_anchor = [r for r in sec.final_blocked_roles if r in _ANCHOR_ROLES]
                if not blocked_anchor:
                    issues.append(
                        f"Pre-hook '{sec.section_name}' does not subtract any anchor role "
                        f"(kick/808/bass/drums) — pre-hook tension will be weak"
                    )

        # Hook must be the fullest section (highest density and energy)
        if hook_sections and sections:
            max_hook_density = max(len(s.final_active_roles) for s in hook_sections)
            max_hook_energy = max(s.energy for s in hook_sections)
            for sec in sections:
                if sec.section_type not in _HOOK_TYPES and sec.section_type not in _PRE_HOOK_TYPES:
                    if len(sec.final_active_roles) > max_hook_density:
                        issues.append(
                            f"Non-hook section '{sec.section_name}' ({sec.section_type}) "
                            f"has {len(sec.final_active_roles)} roles which exceeds the max "
                            f"hook density {max_hook_density} — hook should be fullest"
                        )
            if max_hook_energy < _MIN_HOOK_ENERGY:
                issues.append(
                    f"Hook sections reach only energy={max_hook_energy:.2f} "
                    f"(expected ≥ {_MIN_HOOK_ENERGY}) — hook payoff will be weak"
                )

        # Verse 2 should differ from Verse 1
        verses = by_type.get("verse", [])
        if len(verses) >= 2:
            v1, v2 = verses[0], verses[1]
            roles_v1 = set(v1.final_active_roles)
            roles_v2 = set(v2.final_active_roles)
            if roles_v1 == roles_v2 and v1.energy == v2.energy:
                issues.append(
                    f"Verse 1 '{v1.section_name}' and Verse 2 '{v2.section_name}' "
                    "have identical active roles and energy — Verse 2 must evolve"
                )

        # Hook 2 should differ from Hook 1
        hooks = [s for stype in _HOOK_TYPES for s in by_type.get(stype, [])]
        if len(hooks) >= 2:
            h1, h2 = hooks[0], hooks[1]
            roles_h1 = set(h1.final_active_roles)
            roles_h2 = set(h2.final_active_roles)
            be_h1 = {e.event_type for e in h1.final_boundary_events}
            be_h2 = {e.event_type for e in h2.final_boundary_events}
            if roles_h1 == roles_h2 and be_h1 == be_h2:
                issues.append(
                    f"Hook 1 '{h1.section_name}' and Hook 2 '{h2.section_name}' "
                    "have identical active roles and boundary events — Hook 2 must expand"
                )

        # Outro should remove 808/drums
        for sec in by_type.get("outro", []):
            still_playing = [r for r in sec.final_active_roles if r in _OUTRO_STRIP_ROLES]
            if still_playing:
                issues.append(
                    f"Outro '{sec.section_name}' still has heavy roles "
                    f"{still_playing} — outro should strip 808/drums for closure"
                )

        return issues

    # ------------------------------------------------------------------
    # 3. Repetition analysis
    # ------------------------------------------------------------------

    def _analyze_repetition(
        self, sections: List[ResolvedSection]
    ) -> Tuple[float, List[dict]]:
        """Return (repetition_score, repetition_groups).

        repetition_score is [0, 1] where 1 = all sections are unique.
        repetition_groups lists groups of sections sharing the same fingerprint.
        """
        if not sections:
            return 1.0, []

        fp_to_sections: Dict[tuple, List[str]] = {}
        for sec in sections:
            fp = _fingerprint_key(_section_fingerprint(sec))
            fp_to_sections.setdefault(fp, []).append(sec.section_name)

        # Groups of 2+ sections with identical fingerprint
        groups = [
            {
                "sections": names,
                "fingerprint": {
                    "active_roles": list(fp[0]),
                    "density": fp[1],
                    "energy_bucket": fp[2],
                    "boundary_types": list(fp[3]),
                    "motif_type": fp[4],
                    "drum_roles": list(fp[5]),
                    "bass_roles": list(fp[6]),
                },
            }
            for fp, names in fp_to_sections.items()
            if len(names) >= 2
        ]

        total = len(sections)
        repeated_count = sum(len(g["sections"]) - 1 for g in groups)
        repetition_score = round(1.0 - (repeated_count / max(total, 1)), 4)
        return repetition_score, groups

    # ------------------------------------------------------------------
    # 4. Impact analysis
    # ------------------------------------------------------------------

    def _analyze_impact(self, sections: List[ResolvedSection]) -> dict:
        """Return per-category impact scores."""
        scores: dict = {}

        # Pre-hook tension: how many anchor roles are subtracted before the hook
        pre_hooks = [s for s in sections if s.section_type in _PRE_HOOK_TYPES]
        if pre_hooks:
            anchor_blocks = [
                len([r for r in sec.final_blocked_roles if r in _ANCHOR_ROLES])
                for sec in pre_hooks
            ]
            avg_anchor_blocks = sum(anchor_blocks) / len(anchor_blocks)
            scores["pre_hook_tension"] = round(min(1.0, avg_anchor_blocks / 2.0), 4)
        else:
            scores["pre_hook_tension"] = 0.0

        # Hook payoff: energy + density uplift vs non-hook sections
        hooks = [s for s in sections if s.section_type in _HOOK_TYPES]
        non_hooks = [s for s in sections if s.section_type not in _HOOK_TYPES]
        if hooks and non_hooks:
            avg_hook_energy = sum(s.energy for s in hooks) / len(hooks)
            avg_other_energy = sum(s.energy for s in non_hooks) / len(non_hooks)
            energy_uplift = avg_hook_energy - avg_other_energy

            avg_hook_density = sum(len(s.final_active_roles) for s in hooks) / len(hooks)
            avg_other_density = sum(len(s.final_active_roles) for s in non_hooks) / len(non_hooks)
            density_uplift = avg_hook_density - avg_other_density

            energy_score = max(0.0, min(1.0, (energy_uplift + 0.3) / 0.6))
            density_score = max(0.0, min(1.0, (density_uplift + 2.0) / 4.0))
            scores["hook_payoff"] = round(0.6 * energy_score + 0.4 * density_score, 4)
        else:
            scores["hook_payoff"] = 0.3 if hooks else 0.0

        # Drop event strength: average intensity of all boundary events
        all_boundary_events = [
            evt
            for sec in sections
            for evt in sec.final_boundary_events
        ]
        if all_boundary_events:
            avg_intensity = sum(e.intensity for e in all_boundary_events) / len(all_boundary_events)
            scores["drop_event_strength"] = round(avg_intensity, 4)
            # Flag weak drops (below threshold)
            weak_drops = [e for e in all_boundary_events if e.intensity < _MIN_DROP_INTENSITY]
            scores["weak_drop_count"] = len(weak_drops)
        else:
            scores["drop_event_strength"] = 0.0
            scores["weak_drop_count"] = 0

        # Re-entry strength: sections with reentries and a re_entry_accent event
        reentry_sections = [s for s in sections if s.final_reentries]
        if reentry_sections:
            accented = [
                s for s in reentry_sections
                if any(e.event_type == "re_entry_accent" for e in s.final_boundary_events)
            ]
            scores["re_entry_strength"] = round(len(accented) / len(reentry_sections), 4)
        else:
            scores["re_entry_strength"] = 0.0

        # Drop length check: sections that function as a "drop" (hooks/choruses)
        drop_sections = [s for s in sections if s.section_type in _HOOK_TYPES]
        if drop_sections:
            short_drops = [s for s in drop_sections if s.bars < _MIN_DROP_BARS]
            scores["drop_too_short_count"] = len(short_drops)
            scores["drop_too_subtle_count"] = len(
                [s for s in drop_sections if s.energy < _MIN_HOOK_ENERGY]
            )
        else:
            scores["drop_too_short_count"] = 0
            scores["drop_too_subtle_count"] = 0

        return scores

    # ------------------------------------------------------------------
    # 5. Per-section audit
    # ------------------------------------------------------------------

    def _audit_section(self, sec: ResolvedSection) -> dict:
        """Produce a per-section audit dict."""
        issues: List[str] = []

        # Check that boundary events are all unique (double application guard)
        event_types = [e.event_type for e in sec.final_boundary_events]
        seen: set = set()
        for etype in event_types:
            if etype in seen:
                issues.append(f"boundary event '{etype}' applied more than once")
            seen.add(etype)

        # Check that pattern events have a non-empty action
        for evt in sec.final_pattern_events:
            if not str(evt.get("action") or evt.get("type") or "").strip():
                issues.append("pattern event with empty action (metadata-only)")

        # Check groove events have a type
        for evt in sec.final_groove_events:
            if not str(evt.get("groove_type") or evt.get("type") or "").strip():
                issues.append("groove event with empty type (metadata-only)")

        # Pre-hook must have at least one anchor block
        if sec.section_type in _PRE_HOOK_TYPES:
            blocked_anchor = [r for r in sec.final_blocked_roles if r in _ANCHOR_ROLES]
            if not blocked_anchor:
                issues.append("pre-hook: no anchor role subtracted (kick/808/bass)")

        # Hook must have full density
        if sec.section_type in _HOOK_TYPES:
            if sec.energy < _MIN_HOOK_ENERGY:
                issues.append(
                    f"hook energy {sec.energy:.2f} < {_MIN_HOOK_ENERGY} — hook is too weak"
                )
            if sec.bars < _MIN_DROP_BARS:
                issues.append(
                    f"hook is only {sec.bars} bars — too short to build payoff"
                )

        # Intro should not be full
        if sec.section_type == "intro" and len(sec.final_active_roles) > 3:
            issues.append(
                f"intro has {len(sec.final_active_roles)} roles — should be sparse (≤ 3)"
            )

        # Outro should strip heavy roles
        if sec.section_type == "outro":
            heavy = [r for r in sec.final_active_roles if r in _OUTRO_STRIP_ROLES]
            if heavy:
                issues.append(f"outro still has heavy roles {heavy} — should strip 808/drums")

        return {
            "section_name": sec.section_name,
            "section_type": sec.section_type,
            "energy": sec.energy,
            "active_role_count": len(sec.final_active_roles),
            "blocked_role_count": len(sec.final_blocked_roles),
            "boundary_event_count": len(sec.final_boundary_events),
            "pattern_event_count": len(sec.final_pattern_events),
            "groove_event_count": len(sec.final_groove_events),
            "has_motif_treatment": sec.final_motif_treatment is not None,
            "issues": issues,
        }

    # ------------------------------------------------------------------
    # 6. Transition / distortion safety
    # ------------------------------------------------------------------

    def _check_transition_safety(self, sections: List[ResolvedSection]) -> List[dict]:
        """Extend the base TransitionSafetyAuditor with additional checks.

        Additional checks beyond the base auditor:
        - Missing fade/crossfade before or after silence events
        - Gain-after-reentry without headroom guard
        - Overlapping boundary effects (conflicting event pairs)
        """
        findings: List[dict] = []

        for sec in sections:
            event_types = {e.event_type for e in sec.final_boundary_events}

            # Duplicate boundary events (already caught by TransitionSafetyAuditor,
            # but we re-check here for completeness)
            type_counts: Dict[str, int] = {}
            for evt in sec.final_boundary_events:
                type_counts[evt.event_type] = type_counts.get(evt.event_type, 0) + 1
            for etype, count in type_counts.items():
                if count > 1:
                    findings.append({
                        "severity": "critical",
                        "check": "duplicate_boundary_event",
                        "section": sec.section_name,
                        "event_type": etype,
                        "count": count,
                        "message": (
                            f"'{etype}' applied {count}× in '{sec.section_name}' — "
                            "double-application produces compound silence or stacked gain"
                        ),
                    })

            # Missing fade before silence event
            for etype in _FADE_REQUIRED_EVENTS:
                if etype in event_types and "outro_strip" not in event_types and "bridge_strip" not in event_types:
                    findings.append({
                        "severity": "warning",
                        "check": "missing_fade_crossfade",
                        "section": sec.section_name,
                        "event_type": etype,
                        "message": (
                            f"Section '{sec.section_name}' has '{etype}' but no "
                            "fade/crossfade guard — may produce a hard cut into silence"
                        ),
                    })

            # Gain-after-reentry without headroom guard
            if sec.final_reentries:
                high_gain_events = [
                    e for e in sec.final_boundary_events
                    if e.event_type in {"re_entry_accent", "crash_hit", "final_hook_expansion"}
                    and e.intensity >= 0.8
                ]
                if high_gain_events:
                    for evt in high_gain_events:
                        findings.append({
                            "severity": "warning",
                            "check": "gain_after_reentry_clipping_risk",
                            "section": sec.section_name,
                            "event_type": evt.event_type,
                            "intensity": evt.intensity,
                            "reentries": list(sec.final_reentries),
                            "message": (
                                f"'{evt.event_type}' (intensity={evt.intensity:.2f}) "
                                f"+ role reentries {sec.final_reentries} in "
                                f"'{sec.section_name}' — clipping risk without headroom guard"
                            ),
                        })

            # Hard cut: blocked roles with no transition event in hook/pre_hook
            if (
                sec.final_blocked_roles
                and not sec.final_boundary_events
                and sec.section_type in {"hook", "pre_hook", "drop", "chorus"}
            ):
                findings.append({
                    "severity": "warning",
                    "check": "hard_cut_no_transition",
                    "section": sec.section_name,
                    "section_type": sec.section_type,
                    "blocked_roles": list(sec.final_blocked_roles),
                    "message": (
                        f"'{sec.section_name}' ({sec.section_type}) blocks roles "
                        f"{sec.final_blocked_roles} with no boundary event — hard cut risk"
                    ),
                })

        return findings

    def _score_transition_safety(self, findings: List[dict]) -> float:
        """Derive a [0, 1] safety score from the findings list."""
        if not findings:
            return 1.0
        critical = sum(1 for f in findings if f.get("severity") == "critical")
        warnings = sum(1 for f in findings if f.get("severity") == "warning")
        # Each critical costs 0.20; each warning costs 0.05; floor at 0.0
        penalty = critical * 0.20 + warnings * 0.05
        return round(max(0.0, 1.0 - penalty), 4)

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def _score_contrast(self, sections: List[ResolvedSection]) -> float:
        """Section-to-section energy and density contrast score [0, 1]."""
        if len(sections) < 2:
            return 0.0
        energy_diffs: List[float] = []
        density_diffs: List[float] = []
        for i in range(1, len(sections)):
            prev = sections[i - 1]
            curr = sections[i]
            energy_diffs.append(abs(curr.energy - prev.energy))
            density_diffs.append(
                min(1.0, abs(len(curr.final_active_roles) - len(prev.final_active_roles)) / 5.0)
            )
        avg_e = sum(energy_diffs) / len(energy_diffs)
        avg_d = sum(density_diffs) / len(density_diffs)
        energy_contrast = min(1.0, avg_e / 0.30)
        density_contrast = min(1.0, avg_d / 0.40)
        return round(0.5 * energy_contrast + 0.5 * density_contrast, 4)

    # ------------------------------------------------------------------
    # Weak section aggregation
    # ------------------------------------------------------------------

    def _find_weak_sections(
        self, section_audits: List[dict], trap_issues: List[str]
    ) -> List[str]:
        """Return list of section names that have at least one audit issue."""
        weak: List[str] = []
        for audit in section_audits:
            if audit["issues"]:
                weak.append(audit["section_name"])
        # Also include sections mentioned in trap_structure_issues by name
        for issue in trap_issues:
            # Extract quoted names from issue strings like "Verse 'Verse 1' ..."
            for match in re.findall(r"'([^']+)'", issue):
                if match not in weak:
                    weak.append(match)
        return weak

    # ------------------------------------------------------------------
    # Recommended fixes
    # ------------------------------------------------------------------

    def _build_recommended_fixes(
        self,
        trap_issues: List[str],
        repetition_groups: List[dict],
        impact_scores: dict,
        safety_findings: List[dict],
        noop_details: List[dict],
        mismatch_details: List[dict],
    ) -> List[str]:
        """Return a prioritised list of human-readable fix recommendations."""
        fixes: List[str] = []

        # Repetition
        for group in repetition_groups:
            names = group["sections"]
            fixes.append(
                f"Sections {names} are audibly identical — differentiate via "
                "varied active roles, energy levels, or boundary events"
            )

        # Trap structure
        for issue in trap_issues:
            fixes.append(f"Trap structure: {issue}")

        # Hook payoff
        if impact_scores.get("hook_payoff", 1.0) < 0.50:
            fixes.append(
                "Hook payoff is weak — increase hook energy to ≥ 0.80 and/or add "
                "2+ more roles compared to verses"
            )

        # Pre-hook tension
        if impact_scores.get("pre_hook_tension", 1.0) < 0.50:
            fixes.append(
                "Pre-hook tension is low — subtract kick, 808, or bass role to "
                "create contrast before hook drop"
            )

        # Weak drops
        weak_drop_count = impact_scores.get("weak_drop_count", 0)
        if weak_drop_count:
            fixes.append(
                f"{weak_drop_count} boundary event(s) have intensity < {_MIN_DROP_INTENSITY:.2f} "
                "— increase drop intensity for stronger impact"
            )

        # Drops too short
        short = impact_scores.get("drop_too_short_count", 0)
        if short:
            fixes.append(
                f"{short} hook section(s) are fewer than {_MIN_DROP_BARS} bars — "
                "extend to at least 8 bars for a satisfying payoff"
            )

        # Re-entry strength
        if impact_scores.get("re_entry_strength", 1.0) < 0.50 and self._resolved.resolved_sections:
            reentry_count = sum(
                1 for s in self._resolved.resolved_sections if s.final_reentries
            )
            if reentry_count:
                fixes.append(
                    "Re-entry events lack accent — add re_entry_accent boundary event "
                    "to sections with role reentries"
                )

        # Safety: duplicate events
        critical_findings = [f for f in safety_findings if f.get("severity") == "critical"]
        if critical_findings:
            for finding in critical_findings:
                fixes.append(
                    f"[CRITICAL] Duplicate boundary event '{finding.get('event_type')}' "
                    f"in section '{finding.get('section')}' — deduplicate in FinalPlanResolver"
                )

        # Safety: hard cuts
        hard_cuts = [f for f in safety_findings if f.get("check") == "hard_cut_no_transition"]
        for hc in hard_cuts:
            fixes.append(
                f"Hard cut risk in '{hc.get('section')}' — add a riser or drum fill "
                "boundary event before the role subtractions"
            )

        # Safety: missing fades
        missing_fades = [f for f in safety_findings if f.get("check") == "missing_fade_crossfade"]
        for mf in missing_fades:
            fixes.append(
                f"Section '{mf.get('section')}' has '{mf.get('event_type')}' with no fade guard "
                "— add outro_strip or bridge_strip event to prevent hard silence cut"
            )

        # No-op events
        if noop_details:
            fixes.append(
                f"{len(noop_details)} no-op event(s) detected (metadata-only, no audio change) "
                "— review noop_annotations in FinalPlanResolver output"
            )

        # Render mismatches
        if mismatch_details:
            fixes.append(
                f"{len(mismatch_details)} render mismatch(es) detected — renderer may be "
                "bypassing the resolved plan; ensure _apply_resolved_plan_primary is used"
            )

        return fixes
