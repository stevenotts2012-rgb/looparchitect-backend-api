"""
Production Quality Repair Pass — deterministic repair/tuning pass for LoopArchitect.

Consumes a :class:`~app.services.resolved_render_plan.ResolvedRenderPlan` and a
``production_quality_report`` (as returned by
:class:`~app.services.production_quality_auditor.ProductionQualityAuditor`)
and produces a repaired :class:`~app.services.resolved_render_plan.ResolvedRenderPlan`.

This is NOT a new planning engine.  It applies targeted, deterministic mutations to the
*already-resolved* plan to fix the issues surfaced by the auditor.  If any repair
raises an unexpected exception the original plan is returned unchanged and the failure
is recorded in the metadata.

Repair rules (applied in order)
--------------------------------
1. **Repeated sections** — change at least 2 audible dimensions between sections that
   share the same fingerprint.
2. **Weak hook payoff** — raise hook ``energy`` / ``target_fullness``, add/reinforce
   ``re_entry_accent``, ensure hook has more active roles than verse, ensure 808/bass
   or drums re-enter.
3. **Low pre-hook tension** — block or reduce one anchor role, add a tension boundary
   event, ensure re-entry into the following hook.
4. **Outro with low-end/drums** — remove 808/bass/drums from ``final_active_roles``
   and add a ``fade_out`` / ``resolution`` boundary event.
5. **Render mismatch** — force ``final_active_roles = final_active_roles − final_blocked_roles``.
6. **No-op events** — remove pattern and groove events with empty action/type.
7. **Transition safety** — deduplicate boundary events; add fade guard; lower intensity
   if clipping risk.

Output metadata
---------------
The repaired plan carries an extra ``repair_metadata`` attribute (dict) with::

    production_quality_repair_applied   bool
    production_quality_repairs          list[str]  – human-readable repair log
    production_quality_repair_count     int
    post_repair_quality_report          dict       – re-audit of repaired plan
    repair_failed_reason                str | None – set only when repair raised an exception
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.resolved_render_plan import (
    ResolvedBoundaryEvent,
    ResolvedRenderPlan,
    ResolvedSection,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants shared with the auditor (kept local to avoid circular imports)
# ---------------------------------------------------------------------------

_HOOK_TYPES = frozenset({"hook", "chorus"})
_PRE_HOOK_TYPES = frozenset({"pre_hook", "pre-hook", "buildup", "build"})
_ANCHOR_ROLES = frozenset({"drums", "kick", "808", "bass"})
_OUTRO_STRIP_ROLES = frozenset({"808", "bass", "drums", "kick"})

# Intensity cap applied when clipping risk is detected
_CLIPPING_INTENSITY_CAP = 0.75

# Boundary event types that are considered valid (non-no-op)
_VALID_BOUNDARY_EVENT_TYPES = frozenset({
    "pre_hook_silence_drop",
    "drum_fill",
    "snare_pickup",
    "riser_fx",
    "reverse_cymbal",
    "crash_hit",
    "bridge_strip",
    "outro_strip",
    "pre_hook_drum_mute",
    "bass_pause",
    "silence_drop_before_hook",
    "final_hook_expansion",
    "reverse_fx",
    "silence_gap",
    "subtractive_entry",
    "re_entry_accent",
    "fade_out",
    "resolution",
    "tension_riser",
})


# ---------------------------------------------------------------------------
# RepairedRenderPlan — wraps ResolvedRenderPlan with repair metadata
# ---------------------------------------------------------------------------

@dataclass
class RepairedRenderPlan:
    """A repaired render plan with an attached repair metadata dict.

    Attributes:
        resolved_plan:  The (possibly mutated) :class:`ResolvedRenderPlan`.
        repair_metadata: Metadata describing what was changed.
    """

    resolved_plan: ResolvedRenderPlan
    repair_metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main repair class
# ---------------------------------------------------------------------------


class ProductionQualityRepair:
    """Apply deterministic repairs to a :class:`ResolvedRenderPlan`.

    Parameters
    ----------
    resolved_plan:
        The resolved render plan produced by
        :class:`~app.services.final_plan_resolver.FinalPlanResolver`.
    quality_report:
        The ``production_quality_report`` dict produced by
        :class:`~app.services.production_quality_auditor.ProductionQualityAuditor`.
    available_roles:
        All roles available in the source material.
    genre:
        Genre hint (e.g. ``"trap"``).
    arrangement_id:
        Used only for log messages.
    """

    def __init__(
        self,
        resolved_plan: ResolvedRenderPlan,
        quality_report: Dict[str, Any],
        available_roles: Optional[List[str]] = None,
        genre: str = "generic",
        arrangement_id: int = 0,
    ) -> None:
        self._original = resolved_plan
        self._report = quality_report
        self._available_roles: List[str] = list(available_roles or resolved_plan.available_roles or [])
        self._genre = genre
        self._arrangement_id = arrangement_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def repair(self) -> RepairedRenderPlan:
        """Apply all repair rules and return a :class:`RepairedRenderPlan`.

        If repair raises an unexpected exception, the original plan is returned
        with ``repair_failed_reason`` set.
        """
        try:
            return self._apply_repairs()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PRODUCTION_QUALITY_REPAIR [arr=%d] failed (non-blocking): %s",
                self._arrangement_id,
                exc,
                exc_info=True,
            )
            return RepairedRenderPlan(
                resolved_plan=self._original,
                repair_metadata={
                    "production_quality_repair_applied": False,
                    "production_quality_repairs": [],
                    "production_quality_repair_count": 0,
                    "post_repair_quality_report": self._report,
                    "repair_failed_reason": str(exc),
                },
            )

    # ------------------------------------------------------------------
    # Internal orchestration
    # ------------------------------------------------------------------

    def _apply_repairs(self) -> RepairedRenderPlan:
        # Deep-copy so the original is never mutated
        plan = copy.deepcopy(self._original)
        sections = plan.resolved_sections
        repairs: List[str] = []

        # Rule 1: repeated sections
        repairs += self._repair_repeated_sections(sections)

        # Rule 2: weak hook payoff
        repairs += self._repair_weak_hook(sections)

        # Rule 3: low pre-hook tension
        repairs += self._repair_prehook_tension(sections)

        # Rule 4: outro with low-end/drums
        repairs += self._repair_outro(sections)

        # Rule 5: render mismatch
        repairs += self._repair_render_mismatch(sections)

        # Rule 6: no-op events
        repairs += self._repair_noop_events(sections)

        # Rule 7: transition safety
        repairs += self._repair_transition_safety(sections)

        # Re-run the auditor on the repaired plan to produce post-repair report
        post_report = self._reaudit(plan)

        logger.info(
            "PRODUCTION_QUALITY_REPAIR [arr=%d] repairs=%d "
            "pre_repetition=%.2f post_repetition=%.2f "
            "pre_hook=%.2f post_hook=%.2f",
            self._arrangement_id,
            len(repairs),
            self._report.get("repetition_score", 0.0),
            post_report.get("repetition_score", 0.0),
            self._report.get("hook_payoff_score", 0.0),
            post_report.get("hook_payoff_score", 0.0),
        )

        return RepairedRenderPlan(
            resolved_plan=plan,
            repair_metadata={
                "production_quality_repair_applied": True,
                "production_quality_repairs": repairs,
                "production_quality_repair_count": len(repairs),
                "post_repair_quality_report": post_report,
                "repair_failed_reason": None,
            },
        )

    # ------------------------------------------------------------------
    # Rule 1 — Repeated sections
    # ------------------------------------------------------------------

    def _repair_repeated_sections(self, sections: List[ResolvedSection]) -> List[str]:
        """Differentiate sections that share the same audible fingerprint.

        Strategy: for each repetition group, rotate at least 2 audible
        dimensions between the second (and later) occurrences.
        Dimensions cycled:
          - final_active_roles (toggle one non-anchor role in/out)
          - final_motif_treatment
          - target_fullness
          - target_energy (section.energy ± 0.05)
          - final_pattern_events (inject a synthetic differentiation marker)
          - final_groove_events (inject a synthetic differentiation marker)
        """
        repairs: List[str] = []
        groups: List[dict] = self._report.get("repetition_groups", [])
        if not groups:
            return repairs

        # Build a name → section index map
        name_to_idx = {sec.section_name: i for i, sec in enumerate(sections)}

        for group in groups:
            member_names: List[str] = group.get("sections", [])
            if len(member_names) < 2:
                continue

            # Keep first section unchanged; mutate duplicates
            for repeat_num, sec_name in enumerate(member_names[1:], start=1):
                idx = name_to_idx.get(sec_name)
                if idx is None:
                    continue
                sec = sections[idx]

                changes_made = 0

                # Dimension 1: rotate one non-anchor role
                non_anchor_available = [
                    r for r in self._available_roles
                    if r not in _ANCHOR_ROLES and r not in sec.final_blocked_roles
                ]
                if non_anchor_available and changes_made < 2:
                    # Toggle: add if absent, remove if present
                    candidate = non_anchor_available[repeat_num % len(non_anchor_available)]
                    if candidate in sec.final_active_roles and len(sec.final_active_roles) > 1:
                        sec.final_active_roles = [r for r in sec.final_active_roles if r != candidate]
                        repairs.append(
                            f"Repeated section '{sec_name}': removed role '{candidate}' to differentiate"
                        )
                    else:
                        sec.final_active_roles = list(sec.final_active_roles) + [candidate]
                        repairs.append(
                            f"Repeated section '{sec_name}': added role '{candidate}' to differentiate"
                        )
                    changes_made += 1

                # Dimension 2: adjust energy
                if changes_made < 2:
                    delta = 0.05 * repeat_num
                    new_energy = round(min(1.0, max(0.0, sec.energy + delta)), 4)
                    if new_energy != sec.energy:
                        sec.energy = new_energy
                        repairs.append(
                            f"Repeated section '{sec_name}': adjusted energy to {new_energy}"
                        )
                        changes_made += 1

                # Dimension 3: rotate target_fullness
                if changes_made < 2:
                    fullness_cycle = ["sparse", "medium", "high", "full"]
                    current = sec.target_fullness or "medium"
                    try:
                        next_idx = (fullness_cycle.index(current) + 1) % len(fullness_cycle)
                    except ValueError:
                        next_idx = 1
                    sec.target_fullness = fullness_cycle[next_idx]
                    repairs.append(
                        f"Repeated section '{sec_name}': target_fullness → {sec.target_fullness}"
                    )
                    changes_made += 1

                # Dimension 4: inject a differentiation marker into pattern events
                if changes_made < 2:
                    sec.final_pattern_events = list(sec.final_pattern_events) + [{
                        "action": "variation_shift",
                        "source": "repair_pass",
                        "repeat_num": repeat_num,
                    }]
                    repairs.append(
                        f"Repeated section '{sec_name}': injected pattern variation marker"
                    )
                    changes_made += 1

                # Dimension 5: inject a differentiation marker into groove events
                if changes_made < 2:
                    sec.final_groove_events = list(sec.final_groove_events) + [{
                        "groove_type": "swing_shift",
                        "source": "repair_pass",
                        "repeat_num": repeat_num,
                    }]
                    repairs.append(
                        f"Repeated section '{sec_name}': injected groove variation marker"
                    )
                    changes_made += 1

                # Dimension 6: motif treatment rotation
                if changes_made < 2:
                    motif_variants = ["call_response", "inversion", "augmentation", "fragmentation"]
                    new_motif_type = motif_variants[repeat_num % len(motif_variants)]
                    if sec.final_motif_treatment is None:
                        sec.final_motif_treatment = {"motif_type": new_motif_type, "source": "repair_pass"}
                    else:
                        sec.final_motif_treatment = dict(sec.final_motif_treatment)
                        sec.final_motif_treatment["motif_type"] = new_motif_type
                    repairs.append(
                        f"Repeated section '{sec_name}': motif_treatment → {new_motif_type}"
                    )
                    changes_made += 1

        return repairs

    # ------------------------------------------------------------------
    # Rule 2 — Weak hook payoff
    # ------------------------------------------------------------------

    def _repair_weak_hook(self, sections: List[ResolvedSection]) -> List[str]:
        """Strengthen hooks that fail the payoff threshold.

        Repairs:
        - Raise energy to at least 0.80 when below threshold.
        - Raise target_fullness to "full".
        - Add/reinforce re_entry_accent boundary event.
        - Ensure hook has more active roles than any verse.
        - Re-enter 808/bass or drums when those roles are available.
        """
        repairs: List[str] = []
        hook_payoff_score = float(self._report.get("hook_payoff_score", 1.0))
        if hook_payoff_score >= 0.75:
            return repairs

        verse_sections = [s for s in sections if s.section_type == "verse"]
        avg_verse_roles = (
            sum(len(s.final_active_roles) for s in verse_sections) / len(verse_sections)
            if verse_sections else 0
        )

        for sec in sections:
            if sec.section_type not in _HOOK_TYPES:
                continue

            changed = False

            # Raise energy
            if sec.energy < 0.80:
                sec.energy = 0.80
                repairs.append(f"Weak hook '{sec.section_name}': raised energy to 0.80")
                changed = True

            # Raise fullness
            if sec.target_fullness != "full":
                sec.target_fullness = "full"
                repairs.append(f"Weak hook '{sec.section_name}': target_fullness → full")
                changed = True

            # Add re_entry_accent if missing
            existing_event_types = {e.event_type for e in sec.final_boundary_events}
            if "re_entry_accent" not in existing_event_types:
                sec.final_boundary_events = list(sec.final_boundary_events) + [
                    ResolvedBoundaryEvent(
                        event_type="re_entry_accent",
                        source_engine="repair_pass",
                        placement="boundary",
                        intensity=0.85,
                        bar=sec.bar_start,
                    )
                ]
                repairs.append(
                    f"Weak hook '{sec.section_name}': added re_entry_accent boundary event"
                )
                changed = True

            # Ensure hook has more roles than verse
            if len(sec.final_active_roles) <= avg_verse_roles:
                missing_anchors = [
                    r for r in self._available_roles
                    if r in _ANCHOR_ROLES and r not in sec.final_active_roles
                ]
                if missing_anchors:
                    role_to_add = missing_anchors[0]
                    sec.final_active_roles = list(sec.final_active_roles) + [role_to_add]
                    if role_to_add in sec.final_blocked_roles:
                        sec.final_blocked_roles = [r for r in sec.final_blocked_roles if r != role_to_add]
                    repairs.append(
                        f"Weak hook '{sec.section_name}': added '{role_to_add}' to exceed verse density"
                    )
                    changed = True

            # Re-enter 808/bass/drums when available
            low_end_roles = [r for r in self._available_roles if r in {"808", "bass", "drums"}]
            for role in low_end_roles:
                if role not in sec.final_active_roles:
                    sec.final_active_roles = list(sec.final_active_roles) + [role]
                    if role in sec.final_blocked_roles:
                        sec.final_blocked_roles = [r for r in sec.final_blocked_roles if r != role]
                    if role not in sec.final_reentries:
                        sec.final_reentries = list(sec.final_reentries) + [role]
                    repairs.append(
                        f"Weak hook '{sec.section_name}': re-entered low-end role '{role}'"
                    )
                    changed = True

            if not changed:
                repairs.append(
                    f"Weak hook '{sec.section_name}': no structural change needed (energy/fullness already set)"
                )

        return repairs

    # ------------------------------------------------------------------
    # Rule 3 — Low pre-hook tension
    # ------------------------------------------------------------------

    def _repair_prehook_tension(self, sections: List[ResolvedSection]) -> List[str]:
        """Add tension to pre-hook sections that fail the tension threshold.

        Repairs:
        - Block or reduce one anchor role (drums/kick first, then 808/bass).
        - Add a tension boundary event (tension_riser).
        - Ensure re_entry_accent is present in the following hook.
        """
        repairs: List[str] = []
        tension_score = float(
            (self._report.get("impact_scores") or {}).get("pre_hook_tension", 1.0)
        )
        if tension_score >= 0.5:
            return repairs

        # Build a list of sections in order for "next hook" lookups
        hook_indices = {i for i, s in enumerate(sections) if s.section_type in _HOOK_TYPES}

        for i, sec in enumerate(sections):
            if sec.section_type not in _PRE_HOOK_TYPES:
                continue

            # Already has an anchor block — nothing to do
            existing_blocks = [r for r in sec.final_blocked_roles if r in _ANCHOR_ROLES]
            if existing_blocks:
                continue

            changed = False

            # Block one anchor role (prefer kick/drums, then 808/bass)
            anchor_priority = ["kick", "drums", "808", "bass"]
            for anchor in anchor_priority:
                if anchor in sec.final_active_roles and anchor not in sec.final_blocked_roles:
                    sec.final_blocked_roles = list(sec.final_blocked_roles) + [anchor]
                    sec.final_active_roles = [r for r in sec.final_active_roles if r != anchor]
                    repairs.append(
                        f"Pre-hook '{sec.section_name}': blocked '{anchor}' to add tension"
                    )
                    changed = True
                    break

            # Add tension_riser boundary event
            existing_event_types = {e.event_type for e in sec.final_boundary_events}
            if "tension_riser" not in existing_event_types:
                sec.final_boundary_events = list(sec.final_boundary_events) + [
                    ResolvedBoundaryEvent(
                        event_type="tension_riser",
                        source_engine="repair_pass",
                        placement="pre_boundary",
                        intensity=0.75,
                        bar=sec.bar_start + max(0, sec.bars - 2),
                    )
                ]
                repairs.append(
                    f"Pre-hook '{sec.section_name}': added tension_riser boundary event"
                )
                changed = True

            # Ensure the next hook has a re_entry_accent
            next_hook_idx = next(
                (j for j in range(i + 1, len(sections)) if j in hook_indices), None
            )
            if next_hook_idx is not None:
                hook_sec = sections[next_hook_idx]
                hook_events = {e.event_type for e in hook_sec.final_boundary_events}
                if "re_entry_accent" not in hook_events:
                    hook_sec.final_boundary_events = list(hook_sec.final_boundary_events) + [
                        ResolvedBoundaryEvent(
                            event_type="re_entry_accent",
                            source_engine="repair_pass",
                            placement="boundary",
                            intensity=0.85,
                            bar=hook_sec.bar_start,
                        )
                    ]
                    repairs.append(
                        f"Pre-hook repair: added re_entry_accent to following hook "
                        f"'{hook_sec.section_name}'"
                    )
                    changed = True

            if not changed:
                repairs.append(
                    f"Pre-hook '{sec.section_name}': tension repair — no anchor available to block"
                )

        return repairs

    # ------------------------------------------------------------------
    # Rule 4 — Outro with low-end/drums
    # ------------------------------------------------------------------

    def _repair_outro(self, sections: List[ResolvedSection]) -> List[str]:
        """Remove 808/bass/drums from outro and add fade/resolution event."""
        repairs: List[str] = []
        trap_issues = self._report.get("trap_structure_issues", [])

        # Only run if the auditor flagged an outro issue
        outro_issue = any("outro" in issue.lower() and "heavy" in issue.lower() for issue in trap_issues)
        # Also run if any outro section has heavy roles regardless of auditor flag
        outro_sections = [s for s in sections if s.section_type == "outro"]

        for sec in outro_sections:
            heavy_in_outro = [r for r in sec.final_active_roles if r in _OUTRO_STRIP_ROLES]
            if not heavy_in_outro and not outro_issue:
                continue

            # Remove heavy roles from active
            if heavy_in_outro:
                sec.final_active_roles = [r for r in sec.final_active_roles if r not in _OUTRO_STRIP_ROLES]
                for role in heavy_in_outro:
                    if role not in sec.final_blocked_roles:
                        sec.final_blocked_roles = list(sec.final_blocked_roles) + [role]
                repairs.append(
                    f"Outro '{sec.section_name}': stripped heavy roles {heavy_in_outro}"
                )

            # Add fade_out event if missing
            existing_event_types = {e.event_type for e in sec.final_boundary_events}
            if "fade_out" not in existing_event_types and "resolution" not in existing_event_types:
                sec.final_boundary_events = list(sec.final_boundary_events) + [
                    ResolvedBoundaryEvent(
                        event_type="fade_out",
                        source_engine="repair_pass",
                        placement="boundary",
                        intensity=0.60,
                        bar=sec.bar_start + max(0, sec.bars - 4),
                    )
                ]
                repairs.append(
                    f"Outro '{sec.section_name}': added fade_out boundary event"
                )

        return repairs

    # ------------------------------------------------------------------
    # Rule 5 — Render mismatch
    # ------------------------------------------------------------------

    def _repair_render_mismatch(self, sections: List[ResolvedSection]) -> List[str]:
        """Force final_active_roles = final_active_roles − final_blocked_roles."""
        repairs: List[str] = []
        mismatch_count = int(self._report.get("render_mismatch_count", 0))
        if mismatch_count == 0:
            return repairs

        for sec in sections:
            blocked_set = set(sec.final_blocked_roles)
            active_before = list(sec.final_active_roles)
            fixed = [r for r in active_before if r not in blocked_set]
            if fixed != active_before:
                removed = [r for r in active_before if r in blocked_set]
                sec.final_active_roles = fixed
                repairs.append(
                    f"Render mismatch '{sec.section_name}': removed blocked roles {removed} "
                    "from final_active_roles"
                )

        return repairs

    # ------------------------------------------------------------------
    # Rule 6 — No-op events
    # ------------------------------------------------------------------

    def _repair_noop_events(self, sections: List[ResolvedSection]) -> List[str]:
        """Remove pattern and groove events with empty action/type."""
        repairs: List[str] = []
        noop_count = int(self._report.get("no_op_event_count", 0))
        if noop_count == 0:
            return repairs

        for sec in sections:
            # Filter empty pattern events
            clean_pattern = [
                evt for evt in sec.final_pattern_events
                if str(evt.get("action") or evt.get("type") or "").strip()
            ]
            removed_pattern = len(sec.final_pattern_events) - len(clean_pattern)
            if removed_pattern:
                sec.final_pattern_events = clean_pattern
                repairs.append(
                    f"No-op events '{sec.section_name}': removed {removed_pattern} empty pattern event(s)"
                )

            # Filter empty groove events
            clean_groove = [
                evt for evt in sec.final_groove_events
                if str(evt.get("groove_type") or evt.get("type") or "").strip()
            ]
            removed_groove = len(sec.final_groove_events) - len(clean_groove)
            if removed_groove:
                sec.final_groove_events = clean_groove
                repairs.append(
                    f"No-op events '{sec.section_name}': removed {removed_groove} empty groove event(s)"
                )

        return repairs

    # ------------------------------------------------------------------
    # Rule 7 — Transition safety
    # ------------------------------------------------------------------

    def _repair_transition_safety(self, sections: List[ResolvedSection]) -> List[str]:
        """Deduplicate boundary events, add fade guard, lower clipping-risk intensity."""
        repairs: List[str] = []
        safety_findings = self._report.get("safety_findings", [])
        if not safety_findings:
            return repairs

        # Build per-section finding maps
        dup_sections = {f["section"] for f in safety_findings if f.get("check") == "duplicate_boundary_event"}
        clipping_sections = {
            f["section"] for f in safety_findings if f.get("check") == "gain_after_reentry_clipping_risk"
        }
        hard_cut_sections = {
            f["section"] for f in safety_findings if f.get("check") == "hard_cut_no_transition"
        }

        for sec in sections:
            # Deduplicate boundary events (keep first occurrence of each type)
            if sec.section_name in dup_sections:
                seen_types: set = set()
                unique_events = []
                for evt in sec.final_boundary_events:
                    if evt.event_type not in seen_types:
                        unique_events.append(evt)
                        seen_types.add(evt.event_type)
                removed_count = len(sec.final_boundary_events) - len(unique_events)
                if removed_count:
                    sec.final_boundary_events = unique_events
                    repairs.append(
                        f"Transition safety '{sec.section_name}': deduplicated {removed_count} "
                        "duplicate boundary event(s)"
                    )

            # Lower intensity for clipping risk
            if sec.section_name in clipping_sections:
                capped = []
                for evt in sec.final_boundary_events:
                    if evt.intensity > _CLIPPING_INTENSITY_CAP:
                        capped_evt = ResolvedBoundaryEvent(
                            event_type=evt.event_type,
                            source_engine=evt.source_engine,
                            placement=evt.placement,
                            intensity=_CLIPPING_INTENSITY_CAP,
                            bar=evt.bar,
                            params=dict(evt.params),
                        )
                        capped.append(capped_evt)
                        repairs.append(
                            f"Transition safety '{sec.section_name}': capped '{evt.event_type}' "
                            f"intensity {evt.intensity:.2f} → {_CLIPPING_INTENSITY_CAP}"
                        )
                    else:
                        capped.append(evt)
                sec.final_boundary_events = capped

            # Add fade guard for hard cuts
            if sec.section_name in hard_cut_sections:
                existing_event_types = {e.event_type for e in sec.final_boundary_events}
                if "fade_out" not in existing_event_types and "outro_strip" not in existing_event_types:
                    sec.final_boundary_events = list(sec.final_boundary_events) + [
                        ResolvedBoundaryEvent(
                            event_type="fade_out",
                            source_engine="repair_pass",
                            placement="boundary",
                            intensity=0.50,
                            bar=sec.bar_start + max(0, sec.bars - 2),
                        )
                    ]
                    repairs.append(
                        f"Transition safety '{sec.section_name}': added fade_out guard for hard-cut risk"
                    )

        return repairs

    # ------------------------------------------------------------------
    # Re-audit helper
    # ------------------------------------------------------------------

    def _reaudit(self, plan: ResolvedRenderPlan) -> dict:
        """Re-run the auditor on the repaired plan.  Returns {} on failure."""
        try:
            from app.services.production_quality_auditor import ProductionQualityAuditor
            auditor = ProductionQualityAuditor(
                resolved_plan=plan,
                arrangement_id=self._arrangement_id,
            )
            return auditor.audit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PRODUCTION_QUALITY_REPAIR [arr=%d] re-audit failed: %s",
                self._arrangement_id,
                exc,
            )
            return {}


# ---------------------------------------------------------------------------
# Convenience top-level function
# ---------------------------------------------------------------------------


def run_repair(
    resolved_plan: ResolvedRenderPlan,
    quality_report: Dict[str, Any],
    available_roles: Optional[List[str]] = None,
    genre: str = "generic",
    arrangement_id: int = 0,
) -> RepairedRenderPlan:
    """Apply the production quality repair pass.

    Returns a :class:`RepairedRenderPlan`.  Never raises — on failure the
    original plan is returned with ``repair_failed_reason`` set.
    """
    repairer = ProductionQualityRepair(
        resolved_plan=resolved_plan,
        quality_report=quality_report,
        available_roles=available_roles,
        genre=genre,
        arrangement_id=arrangement_id,
    )
    return repairer.repair()
