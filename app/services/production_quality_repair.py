"""
Production Quality Repair Pass — deterministic post-audit repair of weak or
repetitive Resolved Arrangement Plans before rendering.

Consumes a :class:`~app.services.resolved_render_plan.ResolvedRenderPlan` and
a ``production_quality_report`` dict (from
:class:`~app.services.production_quality_auditor.ProductionQualityAuditor`)
and applies deterministic, audible repairs.

Enabled only when the ``PRODUCTION_QUALITY_REPAIR`` environment variable is
``true`` (default: ``false``).

Pipeline position
-----------------
Resolved Plan → Production Quality Audit → **Repair Pass** → Re-audit → Render

Repair rules applied (in order)
--------------------------------
1. **Render mismatch** — force ``final_active_roles = final_active_roles -
   final_blocked_roles`` for every section that contains overlap.
2. **No-op events** — remove ``final_pattern_events`` and
   ``final_groove_events`` entries that carry no audio payload.
3. **Transition safety** — deduplicate ``final_boundary_events`` (keep first
   occurrence), lower clipping-risk intensities, add fade guard where a silence
   event has no strip companion.
4. **Repeated sections** — change at least 2 audible dimensions (energy,
   target_fullness, pattern variation event, groove event) for every section
   that shares a fingerprint with a prior section.
5. **Weak hook** — boost energy, set ``target_fullness="full"``, inject
   ``re_entry_accent``, and re-introduce any blocked 808/bass/drums roles.
6. **Pre-hook tension** — block one anchor role, add a tension boundary event,
   and mark the blocked role for re-entry in the following hook section.
7. **Outro** — strip 808/bass/drums/kick from ``final_active_roles``, move
   them to ``final_blocked_roles``, and add an ``outro_strip`` boundary event.

Safety
------
If **any** repair pass raises an unhandled exception the original, unrepaired
:class:`~app.services.resolved_render_plan.ResolvedRenderPlan` is returned
unchanged and ``repair_failed_reason`` is recorded in the returned metadata
dict — the render job is never crashed by a repair failure.

Metadata returned (always present)
-----------------------------------
``production_quality_repair_applied``   bool
``production_quality_repairs``          list[dict]  – one entry per repair applied
``production_quality_repair_count``     int
``post_repair_quality_report``          dict        – populated by the caller after
                                                       re-running the auditor
``repair_failed_reason``                str         – only present on failure
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.resolved_render_plan import (
    ResolvedBoundaryEvent,
    ResolvedRenderPlan,
    ResolvedSection,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ANCHOR_ROLES: frozenset[str] = frozenset({"drums", "kick", "808", "bass"})
_OUTRO_STRIP_ROLES: frozenset[str] = frozenset({"808", "bass", "drums", "kick"})
_HOOK_TYPES: frozenset[str] = frozenset({"hook", "chorus"})
_PRE_HOOK_TYPES: frozenset[str] = frozenset({"pre_hook", "pre-hook", "buildup", "build"})

# Minimum energy a hook section must reach after repair
_HOOK_MIN_ENERGY: float = 0.82

# Energy delta applied to each duplicated section to break repetition
_ENERGY_NUDGE: float = 0.06

# Intensity ceiling for reentry accent / crash events when reentries are present
_CLIPPING_THRESHOLD: float = 0.80
_SAFE_REENTRY_INTENSITY: float = 0.75

# Silence-type events that require a fade/strip companion
_SILENCE_EVENT_TYPES: frozenset[str] = frozenset({
    "silence_gap",
    "pre_hook_silence_drop",
    "bass_pause",
})
_STRIP_EVENT_TYPES: frozenset[str] = frozenset({"outro_strip", "bridge_strip"})

# High-gain reentry event types checked for clipping risk
_REENTRY_HIGH_GAIN_TYPES: frozenset[str] = frozenset({
    "re_entry_accent",
    "crash_hit",
    "final_hook_expansion",
})


# ---------------------------------------------------------------------------
# Public repair class
# ---------------------------------------------------------------------------


class ProductionQualityRepair:
    """Apply deterministic repairs to a :class:`ResolvedRenderPlan`.

    Parameters
    ----------
    resolved_plan:
        The canonical resolved render plan to repair (output of
        :class:`~app.services.final_plan_resolver.FinalPlanResolver`).
    production_quality_report:
        Output of ``ProductionQualityAuditor.audit()`` run on the same plan.
    available_roles:
        All roles present in the source material for this arrangement.
        Defaults to ``resolved_plan.available_roles`` when not provided.
    genre:
        Selected genre / vibe / style profile (used for logging context).
    arrangement_id:
        Arrangement database identifier used only for log messages.
    """

    def __init__(
        self,
        resolved_plan: ResolvedRenderPlan,
        production_quality_report: Dict[str, Any],
        available_roles: Optional[List[str]] = None,
        genre: str = "generic",
        arrangement_id: int = 0,
    ) -> None:
        self._resolved = resolved_plan
        self._report = production_quality_report
        self._available_roles: List[str] = list(
            available_roles if available_roles is not None else resolved_plan.available_roles
        )
        self._genre = genre
        self._arrangement_id = arrangement_id
        self._repairs: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def repair(self) -> Tuple[ResolvedRenderPlan, Dict[str, Any]]:
        """Run all repair passes and return ``(repaired_plan, repair_metadata)``.

        The returned ``repair_metadata`` dict always contains:
        - ``production_quality_repair_applied`` – ``True`` on success
        - ``production_quality_repairs`` – list of applied repair records
        - ``production_quality_repair_count`` – len of the repairs list

        On failure the **original, unmodified** plan is returned together with
        metadata containing ``production_quality_repair_applied=False`` and
        ``repair_failed_reason``.
        """
        try:
            sections = [_copy_section(s) for s in self._resolved.resolved_sections]
            sections = self._repair_render_mismatches(sections)
            sections = self._repair_no_op_events(sections)
            sections = self._repair_transition_safety(sections)
            sections = self._repair_repeated_sections(sections)
            sections = self._repair_weak_hook(sections)
            sections = self._repair_pre_hook_tension(sections)
            sections = self._repair_outro(sections)

            repaired_plan = dataclasses.replace(
                self._resolved,
                resolved_sections=sections,
            )

            metadata: Dict[str, Any] = {
                "production_quality_repair_applied": True,
                "production_quality_repairs": list(self._repairs),
                "production_quality_repair_count": len(self._repairs),
            }

            logger.info(
                "PRODUCTION_QUALITY_REPAIR [arr=%d] applied %d repair(s) genre=%s",
                self._arrangement_id,
                len(self._repairs),
                self._genre,
            )
            return repaired_plan, metadata

        except Exception as exc:  # pragma: no cover – safety net
            logger.warning(
                "PRODUCTION_QUALITY_REPAIR [arr=%d] failed (non-blocking): %s",
                self._arrangement_id,
                exc,
                exc_info=True,
            )
            return self._resolved, {
                "production_quality_repair_applied": False,
                "production_quality_repairs": [],
                "production_quality_repair_count": 0,
                "repair_failed_reason": str(exc),
            }

    # ------------------------------------------------------------------
    # Repair pass 1 — render mismatch
    # ------------------------------------------------------------------

    def _repair_render_mismatches(
        self, sections: List[ResolvedSection]
    ) -> List[ResolvedSection]:
        """Force ``final_active_roles = final_active_roles − final_blocked_roles``."""
        repaired: List[ResolvedSection] = []
        for sec in sections:
            blocked_set = set(sec.final_blocked_roles)
            overlap = set(sec.final_active_roles) & blocked_set
            if overlap:
                new_active = [r for r in sec.final_active_roles if r not in blocked_set]
                self._record(
                    rule="render_mismatch",
                    section=sec.section_name,
                    detail=f"Removed blocked roles {sorted(overlap)} from final_active_roles",
                )
                repaired.append(dataclasses.replace(sec, final_active_roles=new_active))
            else:
                repaired.append(sec)
        return repaired

    # ------------------------------------------------------------------
    # Repair pass 2 — no-op events
    # ------------------------------------------------------------------

    def _repair_no_op_events(
        self, sections: List[ResolvedSection]
    ) -> List[ResolvedSection]:
        """Remove ``final_pattern_events`` / ``final_groove_events`` with no payload."""
        repaired: List[ResolvedSection] = []
        for sec in sections:
            clean_pattern = [
                e for e in sec.final_pattern_events
                if str(e.get("action") or e.get("type") or "").strip()
            ]
            clean_groove = [
                e for e in sec.final_groove_events
                if str(e.get("groove_type") or e.get("type") or "").strip()
            ]
            removed_p = len(sec.final_pattern_events) - len(clean_pattern)
            removed_g = len(sec.final_groove_events) - len(clean_groove)
            if removed_p or removed_g:
                self._record(
                    rule="no_op_events_removed",
                    section=sec.section_name,
                    detail=(
                        f"Removed {removed_p} no-op pattern event(s) "
                        f"and {removed_g} no-op groove event(s)"
                    ),
                )
                repaired.append(dataclasses.replace(
                    sec,
                    final_pattern_events=clean_pattern,
                    final_groove_events=clean_groove,
                ))
            else:
                repaired.append(sec)
        return repaired

    # ------------------------------------------------------------------
    # Repair pass 3 — transition safety
    # ------------------------------------------------------------------

    def _repair_transition_safety(
        self, sections: List[ResolvedSection]
    ) -> List[ResolvedSection]:
        """Deduplicate boundary events, guard clipping risk, add fade guard."""
        repaired: List[ResolvedSection] = []
        for sec in sections:
            events = list(sec.final_boundary_events)

            # --- 3a. Deduplicate boundary events (keep first occurrence) ---
            seen_types: Set[str] = set()
            deduped: List[ResolvedBoundaryEvent] = []
            removed_dup = 0
            for evt in events:
                if evt.event_type in seen_types:
                    removed_dup += 1
                else:
                    seen_types.add(evt.event_type)
                    deduped.append(evt)
            if removed_dup:
                self._record(
                    rule="deduplicate_boundary_events",
                    section=sec.section_name,
                    detail=f"Removed {removed_dup} duplicate boundary event(s)",
                )

            # --- 3b. Lower clipping-risk intensity ---
            guarded: List[ResolvedBoundaryEvent] = []
            clipping_lowered = 0
            for evt in deduped:
                if (
                    evt.event_type in _REENTRY_HIGH_GAIN_TYPES
                    and evt.intensity >= _CLIPPING_THRESHOLD
                    and sec.final_reentries
                ):
                    guarded.append(dataclasses.replace(evt, intensity=_SAFE_REENTRY_INTENSITY))
                    clipping_lowered += 1
                else:
                    guarded.append(evt)
            if clipping_lowered:
                self._record(
                    rule="clipping_risk_intensity_lowered",
                    section=sec.section_name,
                    detail=(
                        f"Lowered intensity of {clipping_lowered} high-gain reentry "
                        f"event(s) to {_SAFE_REENTRY_INTENSITY}"
                    ),
                )

            # --- 3c. Add fade guard where silence event has no strip companion ---
            current_types = {e.event_type for e in guarded}
            if _SILENCE_EVENT_TYPES & current_types and not (_STRIP_EVENT_TYPES & current_types):
                guarded.append(_make_boundary_event(
                    event_type="bridge_strip",
                    source_engine="repair",
                    placement="boundary",
                    intensity=0.50,
                    bar=sec.bar_start,
                ))
                self._record(
                    rule="fade_guard_added",
                    section=sec.section_name,
                    detail="Added bridge_strip fade guard (silence event without strip companion)",
                )

            repaired.append(dataclasses.replace(sec, final_boundary_events=guarded))
        return repaired

    # ------------------------------------------------------------------
    # Repair pass 4 — repeated sections
    # ------------------------------------------------------------------

    def _repair_repeated_sections(
        self, sections: List[ResolvedSection]
    ) -> List[ResolvedSection]:
        """Differentiate sections that share an identical fingerprint.

        For each repetition group the first occurrence is kept unchanged.
        Every subsequent section receives at least 2 audible dimension changes:
        - energy nudge (alternating ± per position)
        - target_fullness rotation
        - injected pattern variation event
        - injected groove event
        """
        repetition_groups: List[Dict[str, Any]] = self._report.get("repetition_groups") or []
        if not repetition_groups:
            return sections

        idx_by_name: Dict[str, int] = {s.section_name: i for i, s in enumerate(sections)}

        for group in repetition_groups:
            group_names: List[str] = group.get("sections") or []
            if len(group_names) < 2:
                continue
            for position, name in enumerate(group_names[1:], start=1):
                sec_idx = idx_by_name.get(name)
                if sec_idx is None:
                    continue
                sections[sec_idx] = self._differentiate_section(sections[sec_idx], position)
                # Rebuild index (section references are stable)
                idx_by_name = {s.section_name: i for i, s in enumerate(sections)}

        return sections

    def _differentiate_section(
        self, sec: ResolvedSection, position: int
    ) -> ResolvedSection:
        """Apply ≥ 2 audible dimension changes to break the repetition fingerprint."""
        fullness_cycle = ("sparse", "medium", "high", "full")
        current_fullness = sec.target_fullness or "medium"
        try:
            fi = fullness_cycle.index(current_fullness)
        except ValueError:
            fi = 1

        direction = 1 if position % 2 == 1 else -1
        new_energy = round(max(0.05, min(1.0, sec.energy + direction * _ENERGY_NUDGE)), 4)
        new_fullness = fullness_cycle[(fi + position) % len(fullness_cycle)]
        new_pattern = list(sec.final_pattern_events) + [
            {"action": f"variation_pass_{position}", "source": "repair"}
        ]
        new_groove = list(sec.final_groove_events) + [
            {"groove_type": f"groove_shift_{position}", "source": "repair"}
        ]

        self._record(
            rule="repeated_section_differentiated",
            section=sec.section_name,
            detail=(
                f"Changed 4 audible dimensions — "
                f"energy {sec.energy:.2f}→{new_energy:.2f}, "
                f"fullness {current_fullness}→{new_fullness}, "
                f"added pattern event 'variation_pass_{position}', "
                f"added groove event 'groove_shift_{position}'"
            ),
        )

        return dataclasses.replace(
            sec,
            energy=new_energy,
            target_fullness=new_fullness,
            final_pattern_events=new_pattern,
            final_groove_events=new_groove,
        )

    # ------------------------------------------------------------------
    # Repair pass 5 — weak hook
    # ------------------------------------------------------------------

    def _repair_weak_hook(
        self, sections: List[ResolvedSection]
    ) -> List[ResolvedSection]:
        """Boost hook energy, fullness, add re_entry_accent, re-introduce anchors."""
        verse_sections = [s for s in sections if s.section_type == "verse"]
        avg_verse_density = (
            sum(len(s.final_active_roles) for s in verse_sections) / len(verse_sections)
            if verse_sections
            else 0.0
        )

        repaired: List[ResolvedSection] = []
        for sec in sections:
            if sec.section_type not in _HOOK_TYPES:
                repaired.append(sec)
                continue

            changes: Dict[str, Any] = {}
            desc: List[str] = []

            # 5a. Energy boost
            if sec.energy < _HOOK_MIN_ENERGY:
                changes["energy"] = _HOOK_MIN_ENERGY
                desc.append(f"energy {sec.energy:.2f}→{_HOOK_MIN_ENERGY}")

            # 5b. Fullness
            if sec.target_fullness != "full":
                changes["target_fullness"] = "full"
                desc.append("target_fullness=full")

            # 5c. re_entry_accent
            existing_types = {e.event_type for e in sec.final_boundary_events}
            if "re_entry_accent" not in existing_types:
                new_events = list(sec.final_boundary_events) + [
                    _make_boundary_event(
                        event_type="re_entry_accent",
                        source_engine="repair",
                        placement="boundary",
                        intensity=_SAFE_REENTRY_INTENSITY,
                        bar=sec.bar_start,
                    )
                ]
                changes["final_boundary_events"] = new_events
                desc.append("added re_entry_accent")

            # 5d. Re-introduce available anchor roles (808/bass/drums) to hook
            active_set = set(changes.get("final_active_roles", sec.final_active_roles))
            blocked_set = set(sec.final_blocked_roles)
            added_anchors: List[str] = []
            for role in self._available_roles:
                if role in _ANCHOR_ROLES and role not in active_set and role not in blocked_set:
                    # Re-introduce if hook density is ≤ verse or if it's a core anchor
                    if len(active_set) <= avg_verse_density or role in {"808", "bass", "drums"}:
                        active_set.add(role)
                        added_anchors.append(role)
            if added_anchors:
                new_active = [r for r in (changes.get("final_active_roles") or sec.final_active_roles)
                              if r in active_set]
                for r in added_anchors:
                    if r not in new_active:
                        new_active.append(r)
                changes["final_active_roles"] = new_active
                desc.append(f"added anchor roles {added_anchors}")

            if desc:
                self._record(
                    rule="weak_hook_repaired",
                    section=sec.section_name,
                    detail="; ".join(desc),
                )
                repaired.append(dataclasses.replace(sec, **changes))
            else:
                repaired.append(sec)

        return repaired

    # ------------------------------------------------------------------
    # Repair pass 6 — pre-hook tension
    # ------------------------------------------------------------------

    def _repair_pre_hook_tension(
        self, sections: List[ResolvedSection]
    ) -> List[ResolvedSection]:
        """Block one anchor role in each under-tensioned pre-hook section.

        Also adds a tension boundary event and arranges re-entry of the blocked
        role in the immediately following hook section.
        """
        repaired = list(sections)

        for i, sec in enumerate(repaired):
            if sec.section_type not in _PRE_HOOK_TYPES:
                continue

            # Already has a blocked anchor — no repair needed
            if any(r in _ANCHOR_ROLES for r in sec.final_blocked_roles):
                continue

            # Must have at least one active anchor to block
            active_anchors = [r for r in sec.final_active_roles if r in _ANCHOR_ROLES]
            if not active_anchors:
                continue

            anchor_to_block = active_anchors[0]
            new_active = [r for r in sec.final_active_roles if r != anchor_to_block]
            new_blocked = list(sec.final_blocked_roles) + [anchor_to_block]

            # Add tension boundary event
            existing_types = {e.event_type for e in sec.final_boundary_events}
            new_events = list(sec.final_boundary_events)
            added_event: Optional[str] = None
            if "pre_hook_silence_drop" not in existing_types:
                new_events.append(_make_boundary_event(
                    event_type="pre_hook_silence_drop",
                    source_engine="repair",
                    placement="pre_boundary",
                    intensity=0.70,
                    bar=sec.bar_start,
                ))
                added_event = "pre_hook_silence_drop"
            elif "pre_hook_drum_mute" not in existing_types:
                new_events.append(_make_boundary_event(
                    event_type="pre_hook_drum_mute",
                    source_engine="repair",
                    placement="pre_boundary",
                    intensity=0.70,
                    bar=sec.bar_start,
                ))
                added_event = "pre_hook_drum_mute"

            self._record(
                rule="pre_hook_tension_added",
                section=sec.section_name,
                detail=(
                    f"Blocked anchor '{anchor_to_block}'; "
                    + (f"added '{added_event}' event" if added_event
                       else "existing tension event retained")
                ),
            )
            repaired[i] = dataclasses.replace(
                sec,
                final_active_roles=new_active,
                final_blocked_roles=new_blocked,
                final_boundary_events=new_events,
            )

            # Arrange re-entry of the blocked anchor in the next hook section
            for j in range(i + 1, len(repaired)):
                next_sec = repaired[j]
                if next_sec.section_type in _HOOK_TYPES:
                    if anchor_to_block not in next_sec.final_reentries:
                        repaired[j] = dataclasses.replace(
                            next_sec,
                            final_reentries=list(next_sec.final_reentries) + [anchor_to_block],
                        )
                        self._record(
                            rule="pre_hook_reentry_into_hook",
                            section=next_sec.section_name,
                            detail=(
                                f"Added '{anchor_to_block}' to final_reentries "
                                f"(re-entry after pre-hook block)"
                            ),
                        )
                    break

        return repaired

    # ------------------------------------------------------------------
    # Repair pass 7 — outro
    # ------------------------------------------------------------------

    def _repair_outro(
        self, sections: List[ResolvedSection]
    ) -> List[ResolvedSection]:
        """Strip heavy roles from outro and add an outro_strip boundary event."""
        repaired: List[ResolvedSection] = []
        for sec in sections:
            if sec.section_type != "outro":
                repaired.append(sec)
                continue

            heavy = [r for r in sec.final_active_roles if r in _OUTRO_STRIP_ROLES]
            if not heavy:
                repaired.append(sec)
                continue

            new_active = [r for r in sec.final_active_roles if r not in _OUTRO_STRIP_ROLES]
            new_blocked = list(set(sec.final_blocked_roles) | set(heavy))

            existing_types = {e.event_type for e in sec.final_boundary_events}
            new_events = list(sec.final_boundary_events)
            added_event: Optional[str] = None
            if "outro_strip" not in existing_types:
                new_events.append(_make_boundary_event(
                    event_type="outro_strip",
                    source_engine="repair",
                    placement="boundary",
                    intensity=0.60,
                    bar=sec.bar_start,
                ))
                added_event = "outro_strip"

            self._record(
                rule="outro_heavy_roles_removed",
                section=sec.section_name,
                detail=(
                    f"Removed {heavy} from final_active_roles; "
                    + (f"added '{added_event}' event" if added_event
                       else "outro_strip already present")
                ),
            )
            repaired.append(dataclasses.replace(
                sec,
                final_active_roles=new_active,
                final_blocked_roles=new_blocked,
                final_boundary_events=new_events,
            ))

        return repaired

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _record(self, rule: str, section: str, detail: str) -> None:
        """Append a repair record to the internal repairs list."""
        self._repairs.append({"rule": rule, "section": section, "detail": detail})


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _copy_section(sec: ResolvedSection) -> ResolvedSection:
    """Return a shallow copy of *sec* with all list fields independently copied."""
    return dataclasses.replace(
        sec,
        final_active_roles=list(sec.final_active_roles),
        final_blocked_roles=list(sec.final_blocked_roles),
        final_reentries=list(sec.final_reentries),
        final_boundary_events=list(sec.final_boundary_events),
        final_pattern_events=list(sec.final_pattern_events),
        final_groove_events=list(sec.final_groove_events),
    )


def _make_boundary_event(
    event_type: str,
    source_engine: str = "repair",
    placement: str = "boundary",
    intensity: float = 0.70,
    bar: int = 0,
    params: Optional[Dict[str, Any]] = None,
) -> ResolvedBoundaryEvent:
    """Convenience factory for :class:`~app.services.resolved_render_plan.ResolvedBoundaryEvent`."""
    return ResolvedBoundaryEvent(
        event_type=event_type,
        source_engine=source_engine,
        placement=placement,
        intensity=intensity,
        bar=bar,
        params=params or {},
    )
