"""
Impact & Contrast Engine — forces strong musical contrast, impactful drops,
and section identity before rendering.

Consumes a :class:`~app.services.resolved_render_plan.ResolvedRenderPlan`, a
``production_quality_report`` dict (from
:class:`~app.services.production_quality_auditor.ProductionQualityAuditor`),
a ``selected_genre`` string, and a ``selected_vibe`` string.

Pipeline position
-----------------
Production Quality Repair → **Impact & Contrast Engine** → Render Executor

Rules applied (in order)
------------------------
1. **Section contrast** — when ``contrast_score < 0.6``:
   - Reduce verse ``final_active_roles`` density by 20–40%.
   - Set hook ``target_fullness = "full"`` and ensure energy ≥ 0.9.
   - Remove at least one shared role from verse that also appears in hook.

2. **Real drops** — for every hook section ensure at least one of
   ``silence_drop``, ``silence_drop_before_hook``, or ``subtractive_entry``
   exists as a boundary event, and that the preceding gap is ≥ 0.25 bars.

3. **Re-entry impact** — when a hook immediately follows a pre-hook section:
   - Add ``re_entry_accent`` if missing from hook boundary events.
   - Ensure anchor roles (drums, 808) appear in ``final_reentries``.

4. **Repeated section differentiation** — when repetition is detected,
   modify at least 2 of: pattern events, groove events, energy, active roles.

5. **Hook identity** — hooks must:
   - Have more ``final_active_roles`` than any verse section.
   - Have the highest ``energy`` of all sections.
   - Include an ``fx_impact`` boundary event.

Safety
------
- Boundary events are never duplicated (by type, per section).
- Intensities never exceed ``_SAFE_GAIN_CEILING``.
- Blocked roles are never added to ``final_active_roles``.

Metadata returned (always present)
-----------------------------------
``impact_engine_applied``      bool
``contrast_adjustments``       list[dict]
``drop_enforcements``          list[dict]
``reentry_enforcements``       list[dict]
``impact_engine_version``      str
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

IMPACT_ENGINE_VERSION = "1.0"

_HOOK_TYPES: frozenset[str] = frozenset({"hook", "chorus"})
_PRE_HOOK_TYPES: frozenset[str] = frozenset({"pre_hook", "pre-hook", "buildup", "build"})
_ANCHOR_ROLES: frozenset[str] = frozenset({"drums", "kick", "808", "bass"})

# Minimum contrast_score that triggers contrast enforcement
_CONTRAST_THRESHOLD: float = 0.6

# Hook must reach at least this energy level
_HOOK_MIN_ENERGY: float = 0.9

# Maximum intensity any injected event may carry
_SAFE_GAIN_CEILING: float = 0.80

# Verse density reduction bounds (20–40%)
_VERSE_DENSITY_REDUCE_MIN: float = 0.20
_VERSE_DENSITY_REDUCE_MAX: float = 0.40

# Drop event types that satisfy the "real drop" requirement
_DROP_EVENT_TYPES: frozenset[str] = frozenset({
    "silence_drop",
    "silence_drop_before_hook",
    "subtractive_entry",
})

# Minimum drop duration in bars
_MIN_DROP_BARS: float = 0.25

# Groove/pattern event tags used when differentiating repeated sections
_DIFFERENTIATION_GROOVE_TAG = "impact_groove_shift"
_DIFFERENTIATION_PATTERN_TAG = "impact_variation_pass"


# ---------------------------------------------------------------------------
# Public engine class
# ---------------------------------------------------------------------------


class ImpactEngine:
    """Apply impact and contrast enforcement to a :class:`ResolvedRenderPlan`.

    Parameters
    ----------
    resolved_plan:
        The canonical resolved render plan (output of
        :class:`~app.services.final_plan_resolver.FinalPlanResolver` or
        :class:`~app.services.production_quality_repair.ProductionQualityRepair`).
    production_quality_report:
        Output of ``ProductionQualityAuditor.audit()`` run on the same plan.
    selected_genre:
        Genre string (e.g. ``"trap"``, ``"rnb"``).
    selected_vibe:
        Vibe/mood string (e.g. ``"aggressive"``, ``"smooth"``).
    arrangement_id:
        Arrangement database identifier used only for log messages.
    """

    def __init__(
        self,
        resolved_plan: ResolvedRenderPlan,
        production_quality_report: Dict[str, Any],
        selected_genre: str = "generic",
        selected_vibe: str = "neutral",
        arrangement_id: int = 0,
    ) -> None:
        self._resolved = resolved_plan
        self._report = production_quality_report
        self._genre = selected_genre
        self._vibe = selected_vibe
        self._arrangement_id = arrangement_id

        # Accumulated records per output metadata field
        self._contrast_adjustments: List[Dict[str, Any]] = []
        self._drop_enforcements: List[Dict[str, Any]] = []
        self._reentry_enforcements: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enforce(self) -> Tuple[ResolvedRenderPlan, Dict[str, Any]]:
        """Run all impact/contrast passes and return ``(plan, metadata)``.

        On failure the **original, unmodified** plan is returned with
        ``impact_engine_applied = False`` and ``impact_engine_error`` set.
        """
        try:
            sections = [_copy_section(s) for s in self._resolved.resolved_sections]

            contrast_score: float = float(
                self._report.get("contrast_score", 1.0)
            )

            sections = self._enforce_section_contrast(sections, contrast_score)
            sections = self._enforce_real_drops(sections)
            sections = self._enforce_reentry_impact(sections)
            sections = self._differentiate_repeated_sections(sections)
            sections = self._strengthen_hook_identity(sections)

            enforced_plan = dataclasses.replace(
                self._resolved,
                resolved_sections=sections,
            )

            metadata: Dict[str, Any] = {
                "impact_engine_applied": True,
                "contrast_adjustments": list(self._contrast_adjustments),
                "drop_enforcements": list(self._drop_enforcements),
                "reentry_enforcements": list(self._reentry_enforcements),
                "impact_engine_version": IMPACT_ENGINE_VERSION,
            }

            logger.info(
                "IMPACT_ENGINE [arr=%d] applied — contrast=%d drop=%d reentry=%d "
                "genre=%s vibe=%s",
                self._arrangement_id,
                len(self._contrast_adjustments),
                len(self._drop_enforcements),
                len(self._reentry_enforcements),
                self._genre,
                self._vibe,
            )
            return enforced_plan, metadata

        except Exception as exc:  # pragma: no cover — safety net
            logger.warning(
                "IMPACT_ENGINE [arr=%d] failed (non-blocking): %s",
                self._arrangement_id,
                exc,
                exc_info=True,
            )
            return self._resolved, {
                "impact_engine_applied": False,
                "contrast_adjustments": [],
                "drop_enforcements": [],
                "reentry_enforcements": [],
                "impact_engine_version": IMPACT_ENGINE_VERSION,
                "impact_engine_error": str(exc),
            }

    # ------------------------------------------------------------------
    # Rule 1 — section contrast
    # ------------------------------------------------------------------

    def _enforce_section_contrast(
        self,
        sections: List[ResolvedSection],
        contrast_score: float,
    ) -> List[ResolvedSection]:
        """Enforce strong contrast when ``contrast_score < _CONTRAST_THRESHOLD``.

        For each verse: reduce ``final_active_roles`` density by 20–40% and
        remove at least one role that appears in any hook.
        For each hook: set energy ≥ 0.9 and ``target_fullness = "full"``.
        """
        if contrast_score >= _CONTRAST_THRESHOLD:
            return sections

        hook_roles: Set[str] = set()
        for s in sections:
            if s.section_type in _HOOK_TYPES:
                hook_roles.update(s.final_active_roles)

        repaired: List[ResolvedSection] = []
        for sec in sections:
            if sec.section_type == "verse":
                sec = self._reduce_verse_density(sec, hook_roles)
            elif sec.section_type in _HOOK_TYPES:
                sec = self._boost_hook_contrast(sec)
            repaired.append(sec)

        return repaired

    def _reduce_verse_density(
        self,
        sec: ResolvedSection,
        hook_roles: Set[str],
    ) -> ResolvedSection:
        """Reduce verse density and remove at least one shared hook role."""
        blocked_set: Set[str] = set(sec.final_blocked_roles)
        active = list(sec.final_active_roles)

        if not active:
            return sec

        # Compute target count after 20–40% reduction (use 30% midpoint)
        reduction = 0.30
        target_count = max(1, round(len(active) * (1.0 - reduction)))

        # Prefer to remove roles shared with hooks first
        shared = [r for r in active if r in hook_roles and r not in _ANCHOR_ROLES]
        non_shared = [r for r in active if r not in hook_roles or r in _ANCHOR_ROLES]

        new_active: List[str] = []
        removed: List[str] = []

        # Build new_active: keep non-shared first, then shared up to target_count
        # This ensures at least one shared role is removed if shared roles exist
        # and there's room to cut.
        for r in non_shared:
            if len(new_active) < target_count:
                new_active.append(r)
            else:
                removed.append(r)

        shared_kept = 0
        for r in shared:
            if len(new_active) < target_count and shared_kept == 0:
                # Keep at most (target_count - len(non_shared kept)) shared roles,
                # but always remove at least one shared role if available.
                new_active.append(r)
                shared_kept += 1
            else:
                removed.append(r)

        # Never include blocked roles
        new_active = [r for r in new_active if r not in blocked_set]

        if not new_active:
            new_active = [active[0]] if active[0] not in blocked_set else active[:1]

        shared_removed = [r for r in removed if r in hook_roles]

        self._contrast_adjustments.append({
            "rule": "verse_density_reduced",
            "section": sec.section_name,
            "original_count": len(active),
            "new_count": len(new_active),
            "removed_roles": removed,
            "shared_roles_removed": shared_removed,
        })

        return dataclasses.replace(sec, final_active_roles=new_active)

    def _boost_hook_contrast(self, sec: ResolvedSection) -> ResolvedSection:
        """Ensure hook energy ≥ 0.9 and target_fullness = 'full'."""
        changes: Dict[str, Any] = {}
        desc: List[str] = []

        if sec.energy < _HOOK_MIN_ENERGY:
            changes["energy"] = _HOOK_MIN_ENERGY
            desc.append(f"energy {sec.energy:.2f}→{_HOOK_MIN_ENERGY}")

        if sec.target_fullness != "full":
            changes["target_fullness"] = "full"
            desc.append("target_fullness=full")

        if desc:
            self._contrast_adjustments.append({
                "rule": "hook_density_boosted",
                "section": sec.section_name,
                "detail": "; ".join(desc),
            })
            return dataclasses.replace(sec, **changes)

        return sec

    # ------------------------------------------------------------------
    # Rule 2 — enforce real drops
    # ------------------------------------------------------------------

    def _enforce_real_drops(
        self,
        sections: List[ResolvedSection],
    ) -> List[ResolvedSection]:
        """Ensure every hook has at least one drop event and drop_bars ≥ 0.25."""
        repaired: List[ResolvedSection] = []
        for sec in sections:
            if sec.section_type not in _HOOK_TYPES:
                repaired.append(sec)
                continue

            existing_types = {e.event_type for e in sec.final_boundary_events}
            has_drop = bool(_DROP_EVENT_TYPES & existing_types)

            new_events = list(sec.final_boundary_events)
            added_event: Optional[str] = None

            if not has_drop:
                drop_type = "silence_drop_before_hook"
                new_events.append(_make_boundary_event(
                    event_type=drop_type,
                    source_engine="impact_engine",
                    placement="pre_boundary",
                    intensity=min(0.75, _SAFE_GAIN_CEILING),
                    bar=sec.bar_start,
                    params={"drop_bars": _MIN_DROP_BARS},
                ))
                added_event = drop_type

            # Ensure any existing drop event carries a drop_bars param ≥ 0.25
            patched_events: List[ResolvedBoundaryEvent] = []
            for evt in new_events:
                if evt.event_type in _DROP_EVENT_TYPES:
                    drop_bars = float(evt.params.get("drop_bars", _MIN_DROP_BARS))
                    if drop_bars < _MIN_DROP_BARS:
                        new_params = dict(evt.params)
                        new_params["drop_bars"] = _MIN_DROP_BARS
                        evt = dataclasses.replace(evt, params=new_params)
                patched_events.append(evt)

            if added_event or patched_events != new_events:
                self._drop_enforcements.append({
                    "section": sec.section_name,
                    "added_drop_event": added_event,
                    "drop_bars_enforced": _MIN_DROP_BARS,
                })

            if patched_events != list(sec.final_boundary_events) or added_event:
                repaired.append(dataclasses.replace(sec, final_boundary_events=patched_events))
            else:
                repaired.append(sec)

        return repaired

    # ------------------------------------------------------------------
    # Rule 3 — enforce re-entry impact
    # ------------------------------------------------------------------

    def _enforce_reentry_impact(
        self,
        sections: List[ResolvedSection],
    ) -> List[ResolvedSection]:
        """Add re_entry_accent and anchor re-entries when hook follows pre-hook."""
        repaired = list(sections)

        for i, sec in enumerate(repaired):
            if sec.section_type not in _HOOK_TYPES:
                continue

            # Check whether the immediately preceding section is a pre-hook
            if i == 0:
                continue
            prev = repaired[i - 1]
            if prev.section_type not in _PRE_HOOK_TYPES:
                continue

            changes: Dict[str, Any] = {}
            desc: List[str] = []

            # 3a. Add re_entry_accent if missing
            existing_types = {e.event_type for e in sec.final_boundary_events}
            if "re_entry_accent" not in existing_types:
                new_events = list(sec.final_boundary_events) + [
                    _make_boundary_event(
                        event_type="re_entry_accent",
                        source_engine="impact_engine",
                        placement="boundary",
                        intensity=min(0.75, _SAFE_GAIN_CEILING),
                        bar=sec.bar_start,
                    )
                ]
                changes["final_boundary_events"] = new_events
                desc.append("added re_entry_accent")

            # 3b. Ensure anchor roles (drums, 808) are in final_reentries
            blocked_set = set(sec.final_blocked_roles)
            missing_anchors = [
                r for r in ("drums", "808")
                if r not in sec.final_reentries
                and r not in blocked_set
            ]
            if missing_anchors:
                changes["final_reentries"] = list(sec.final_reentries) + missing_anchors
                desc.append(f"added anchor re-entries {missing_anchors}")

            if desc:
                self._reentry_enforcements.append({
                    "section": sec.section_name,
                    "prev_section": prev.section_name,
                    "detail": "; ".join(desc),
                })
                repaired[i] = dataclasses.replace(sec, **changes)

        return repaired

    # ------------------------------------------------------------------
    # Rule 4 — differentiate repeated sections
    # ------------------------------------------------------------------

    def _differentiate_repeated_sections(
        self,
        sections: List[ResolvedSection],
    ) -> List[ResolvedSection]:
        """Ensure repeated sections differ in ≥ 2 audible dimensions."""
        idx_by_name: Dict[str, int] = {s.section_name: i for i, s in enumerate(sections)}

        repetition_groups: List[Dict[str, Any]] = (
            self._report.get("repetition_groups") or []
        )
        if not repetition_groups:
            # Self-detect repetitions using simple fingerprint
            repetition_groups = self._detect_repetitions(sections)

        for group in repetition_groups:
            group_names: List[str] = group.get("sections") or []
            if len(group_names) < 2:
                continue
            for position, name in enumerate(group_names[1:], start=1):
                sec_idx = idx_by_name.get(name)
                if sec_idx is None:
                    continue
                sections[sec_idx] = self._differentiate_section(
                    sections[sec_idx], position
                )

        return sections

    @staticmethod
    def _detect_repetitions(
        sections: List[ResolvedSection],
    ) -> List[Dict[str, Any]]:
        """Detect sections that share the same fingerprint."""
        fingerprints: Dict[Tuple[str, frozenset], List[str]] = {}
        for sec in sections:
            fp = (sec.section_type, frozenset(sec.final_active_roles))
            fingerprints.setdefault(fp, []).append(sec.section_name)

        groups = []
        for names in fingerprints.values():
            if len(names) >= 2:
                groups.append({"sections": names})
        return groups

    def _differentiate_section(
        self,
        sec: ResolvedSection,
        position: int,
    ) -> ResolvedSection:
        """Apply ≥ 2 audible dimension changes to break the repetition fingerprint."""
        blocked_set = set(sec.final_blocked_roles)

        # Dimension 1: energy nudge
        direction = 1 if position % 2 == 1 else -1
        new_energy = round(max(0.05, min(1.0, sec.energy + direction * 0.06)), 4)

        # Dimension 2: inject pattern variation event
        new_pattern = list(sec.final_pattern_events) + [
            {"action": f"{_DIFFERENTIATION_PATTERN_TAG}_{position}", "source": "impact_engine"}
        ]

        # Dimension 3: inject groove event
        new_groove = list(sec.final_groove_events) + [
            {"groove_type": f"{_DIFFERENTIATION_GROOVE_TAG}_{position}", "source": "impact_engine"}
        ]

        # Dimension 4: rotate one non-anchor active role (if possible)
        non_anchor_active = [r for r in sec.final_active_roles if r not in _ANCHOR_ROLES]
        new_active = list(sec.final_active_roles)
        rotated_role: Optional[str] = None
        if len(non_anchor_active) > 1:
            # Remove the last non-anchor role to create audible difference
            role_to_rotate = non_anchor_active[-1]
            if role_to_rotate not in blocked_set:
                new_active = [r for r in sec.final_active_roles if r != role_to_rotate]
                rotated_role = role_to_rotate

        changes: Dict[str, Any] = {
            "energy": new_energy,
            "final_pattern_events": new_pattern,
            "final_groove_events": new_groove,
        }
        if rotated_role:
            changes["final_active_roles"] = new_active

        self._contrast_adjustments.append({
            "rule": "repeated_section_differentiated",
            "section": sec.section_name,
            "position": position,
            "energy_change": new_energy - sec.energy,
            "pattern_event_added": f"{_DIFFERENTIATION_PATTERN_TAG}_{position}",
            "groove_event_added": f"{_DIFFERENTIATION_GROOVE_TAG}_{position}",
            "rotated_role": rotated_role,
        })

        return dataclasses.replace(sec, **changes)

    # ------------------------------------------------------------------
    # Rule 5 — strengthen hook identity
    # ------------------------------------------------------------------

    def _strengthen_hook_identity(
        self,
        sections: List[ResolvedSection],
    ) -> List[ResolvedSection]:
        """Ensure hooks have max roles, max energy, and an fx_impact event."""
        verse_sections = [s for s in sections if s.section_type == "verse"]
        max_verse_role_count = max(
            (len(s.final_active_roles) for s in verse_sections), default=0
        )
        max_verse_energy = max(
            (s.energy for s in verse_sections), default=0.0
        )
        max_hook_energy = max(
            (s.energy for s in sections if s.section_type in _HOOK_TYPES), default=0.0
        )
        global_max_energy = max(
            (s.energy for s in sections), default=0.0
        )

        repaired: List[ResolvedSection] = []
        for sec in sections:
            if sec.section_type not in _HOOK_TYPES:
                repaired.append(sec)
                continue

            blocked_set = set(sec.final_blocked_roles)
            changes: Dict[str, Any] = {}
            desc: List[str] = []

            # 5a. Hooks must have more active roles than any verse
            hook_role_count = len(sec.final_active_roles)
            if hook_role_count <= max_verse_role_count:
                # Try to add available roles from plan that aren't already active/blocked
                available = list(self._resolved.available_roles)
                new_active = list(sec.final_active_roles)
                for role in available:
                    if len(new_active) > max_verse_role_count:
                        break
                    if role not in new_active and role not in blocked_set:
                        new_active.append(role)
                if len(new_active) > hook_role_count:
                    changes["final_active_roles"] = new_active
                    desc.append(
                        f"role count {hook_role_count}→{len(new_active)} "
                        f"(verse max={max_verse_role_count})"
                    )

            # 5b. Hooks must have the highest energy
            target_energy = max(
                _HOOK_MIN_ENERGY,
                round(min(1.0, global_max_energy + 0.01), 4)
                if sec.energy <= max_verse_energy
                else sec.energy,
            )
            if sec.energy < target_energy:
                changes["energy"] = target_energy
                desc.append(f"energy {sec.energy:.2f}→{target_energy:.2f}")

            # 5c. Include fx_impact boundary event
            existing_types = {e.event_type for e in sec.final_boundary_events}
            if "fx_impact" not in existing_types:
                new_events = list(
                    changes.get("final_boundary_events", sec.final_boundary_events)
                ) + [
                    _make_boundary_event(
                        event_type="fx_impact",
                        source_engine="impact_engine",
                        placement="boundary",
                        intensity=min(0.80, _SAFE_GAIN_CEILING),
                        bar=sec.bar_start,
                    )
                ]
                changes["final_boundary_events"] = new_events
                desc.append("added fx_impact event")

            if desc:
                self._contrast_adjustments.append({
                    "rule": "hook_identity_strengthened",
                    "section": sec.section_name,
                    "detail": "; ".join(desc),
                })
                repaired.append(dataclasses.replace(sec, **changes))
            else:
                repaired.append(sec)

        return repaired

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_drop(self, section: str, detail: str) -> None:
        self._drop_enforcements.append({"section": section, "detail": detail})

    def _record_reentry(self, section: str, detail: str) -> None:
        self._reentry_enforcements.append({"section": section, "detail": detail})


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
    source_engine: str = "impact_engine",
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
        intensity=min(intensity, _SAFE_GAIN_CEILING),
        bar=bar,
        params=params or {},
    )
