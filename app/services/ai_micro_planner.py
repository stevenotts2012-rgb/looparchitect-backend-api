"""
AI Micro Planner — Phase 5.

Generates a deterministic, concrete bar-range micro-plan from a section-level
``ProducerArrangementPlanV2``.

Design contracts
----------------
- The micro planner operates as a **pure planning layer** — it never renders audio.
- All deltas are concrete: bar numbers, role names, behavior strings.
- Vague instructions (e.g. "make it bigger", "add more energy") are rejected.
- The planner applies producer heuristics:
    - Delayed melody entry in intros / breakdowns
    - Hat density build in the last 4 bars before a hook
    - Drop on the last bar before a bridge/breakdown
    - Fill in the last 2 bars of any section >= 8 bars
    - Role additions at the midpoint of verses >= 8 bars
    - Re-entry stagger after a drop

Usage
-----
::

    from app.services.ai_micro_planner import AIMicroPlanner

    planner = AIMicroPlanner()
    micro_plan = planner.plan(arrangement_plan)
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.schemas.producer_plan import (
    AIMicroBarRange,
    AIMicroPlan,
    AIMicroSectionPlan,
)
from app.services.producer_plan_builder import (
    ProducerArrangementPlanV2,
    ProducerSectionPlan,
    SectionKind,
    DensityLevel,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vague phrase detection (re-used from ai_producer_assist level)
# ---------------------------------------------------------------------------

_VAGUE_PHRASES: frozenset[str] = frozenset([
    "add more energy",
    "make it bigger",
    "keep it the same but stronger",
    "more energy",
    "just like before",
    "same as before",
    "keep the same",
    "same but stronger",
    "make it louder",
    "just louder",
    "more intense",
    "similar to before",
    "repeat the same",
])


def _is_vague(text: str) -> bool:
    if not text:
        return False
    lower = text.strip().lower()
    return any(phrase in lower for phrase in _VAGUE_PHRASES)


# ---------------------------------------------------------------------------
# Micro planner
# ---------------------------------------------------------------------------


class AIMicroPlanner:
    """Deterministic bar-range micro-plan generator.

    Applies producer heuristics to every section in a
    ``ProducerArrangementPlanV2`` to produce a concrete
    ``AIMicroPlan`` with bar-level ``AIMicroBarRange`` entries.
    """

    def plan(self, arrangement_plan: ProducerArrangementPlanV2) -> AIMicroPlan:
        """Build and return a validated ``AIMicroPlan``.

        Parameters
        ----------
        arrangement_plan:
            The section-level plan to expand into bar-range micro-actions.

        Returns
        -------
        AIMicroPlan
            A complete micro-plan.  ``validation_errors`` will be non-empty
            when any vague or invalid delta was detected and auto-corrected.
        """
        section_plans: List[AIMicroSectionPlan] = []
        validation_errors: List[str] = []
        total_deltas = 0

        for section in arrangement_plan.sections:
            micro_section = self._plan_section(section, arrangement_plan)
            # Validate deltas
            for delta in micro_section.bar_ranges:
                errs = self._validate_delta(delta, section.label)
                validation_errors.extend(errs)
            section_plans.append(micro_section)
            total_deltas += len(micro_section.bar_ranges)

        logger.info(
            "AIMicroPlanner: %d sections, %d deltas, %d validation errors",
            len(section_plans),
            total_deltas,
            len(validation_errors),
        )

        return AIMicroPlan(
            sections=section_plans,
            generated_by="deterministic",
            total_deltas=total_deltas,
            validation_errors=validation_errors,
        )

    # ------------------------------------------------------------------
    # Per-section planning
    # ------------------------------------------------------------------

    def _plan_section(
        self,
        section: ProducerSectionPlan,
        plan: ProducerArrangementPlanV2,
    ) -> AIMicroSectionPlan:
        """Generate the micro-plan for a single section."""
        bars = section.length_bars
        deltas: List[AIMicroBarRange] = []

        # ---- 1. Intro / Breakdown: delayed melody entry ----------------
        if section.section_type in (SectionKind.INTRO, SectionKind.BREAKDOWN):
            melody_roles = [r for r in section.active_roles if r in ("melody", "arp", "synth")]
            if melody_roles:
                delay_bars = min(4, bars // 2)
                deltas.append(AIMicroBarRange(
                    bar_start=1,
                    bar_end=delay_bars,
                    role_remove=melody_roles,
                    melody_behavior=f"silent bars 1-{delay_bars}, enters bar {delay_bars + 1}",
                    reason=f"Delayed melody entry {delay_bars} bars — producer heuristic: {section.section_type.value} starts sparse",
                ))
                if delay_bars < bars:
                    deltas.append(AIMicroBarRange(
                        bar_start=delay_bars + 1,
                        bar_end=bars,
                        role_add=melody_roles,
                        melody_behavior=f"enters bar {delay_bars + 1}",
                        delayed_entry_bars=delay_bars,
                        reason=f"Melody re-enters after delayed entry at bar {delay_bars + 1}",
                    ))

        # ---- 2. Pre-hook: hat density build in last 4 bars -------------
        if section.section_type == SectionKind.PRE_HOOK and bars >= 4:
            build_start = max(1, bars - 3)
            has_drums = any(r in section.active_roles for r in ("drums", "percussion"))
            if has_drums:
                deltas.append(AIMicroBarRange(
                    bar_start=build_start,
                    bar_end=bars,
                    hat_behavior=f"open_hat_8th bars {build_start}-{bars}; hat_density_up",
                    reason="Hat density build in last 4 bars of pre-hook — creates tension before hook",
                ))

        # ---- 3. Hook: kick and bass full from bar 1, delayed hat -------
        if section.section_type == SectionKind.HOOK:
            has_kick = any(r in section.active_roles for r in ("drums",))
            has_bass = "bass" in section.active_roles
            if has_kick:
                deltas.append(AIMicroBarRange(
                    bar_start=1,
                    bar_end=bars,
                    kick_behavior=f"four_on_floor bars 1-{bars}",
                    hat_behavior=f"closed_hat_8th bars 1-4; open_hat_upbeat bars 5-{bars}",
                    reason="Hook: kick four-on-floor from bar 1; hat variation introduces novelty",
                ))
            if has_bass:
                deltas.append(AIMicroBarRange(
                    bar_start=1,
                    bar_end=bars,
                    bass_behavior=f"bass_root_quarter bars 1-2; bass_pattern bars 3-{bars}",
                    reason="Hook: bass root note entry for impact then pattern from bar 3",
                ))

        # ---- 4. Verse >= 8 bars: role addition at midpoint -------------
        if section.section_type == SectionKind.VERSE and bars >= 8:
            mid = bars // 2 + 1
            layerable = [
                r for r in plan.available_roles
                if r not in section.active_roles and r not in ("full_mix",)
            ]
            if layerable:
                add_role = layerable[0]
                deltas.append(AIMicroBarRange(
                    bar_start=mid,
                    bar_end=bars,
                    role_add=[add_role],
                    reason=f"Verse layer add at bar {mid} (midpoint) — something changes every 4-8 bars",
                ))

        # ---- 5. Fill in last 2 bars of sections >= 8 bars -------------
        if bars >= 8 and section.section_type not in (SectionKind.INTRO, SectionKind.OUTRO):
            has_drums = any(r in section.active_roles for r in ("drums", "percussion"))
            if has_drums:
                deltas.append(AIMicroBarRange(
                    bar_start=bars - 1,
                    bar_end=bars,
                    fill_at=bars,
                    kick_behavior=f"kick_fill bar {bars}",
                    hat_behavior=f"snare_roll bar {bars}",
                    reason=f"Section-end fill at bar {bars} — standard producer transition technique",
                ))

        # ---- 6. Bridge / Breakdown: drop on last bar before end -------
        if section.section_type in (SectionKind.BRIDGE, SectionKind.BREAKDOWN):
            if bars >= 4:
                drop_bar = bars - 1
                deltas.append(AIMicroBarRange(
                    bar_start=drop_bar,
                    bar_end=bars,
                    drop_at=drop_bar,
                    role_remove=[r for r in section.active_roles if r in ("drums", "bass")],
                    kick_behavior=f"mute_kick bar {drop_bar}",
                    bass_behavior=f"mute_bass bar {drop_bar}",
                    reason=f"Drop on bar {drop_bar} at end of breakdown — tension before re-entry",
                ))
                # Re-entry hint (the next section owns re-entry but we log intent here)
                deltas.append(AIMicroBarRange(
                    bar_start=bars,
                    bar_end=bars,
                    reentry_at=bars,
                    reason=f"Re-entry at bar {bars} end of breakdown — signal next section starts full",
                ))

        # ---- 7. Outro: progressive role removal -----------------------
        if section.section_type == SectionKind.OUTRO and bars >= 4:
            # Remove one role per 4-bar block
            strip_order = [r for r in ("drums", "bass", "melody", "arp", "pads") if r in section.active_roles]
            for idx, role in enumerate(strip_order):
                remove_bar = min(bars, 1 + idx * 4)
                deltas.append(AIMicroBarRange(
                    bar_start=remove_bar,
                    bar_end=bars,
                    role_remove=[role],
                    reason=f"Outro progressive removal: mute {role} from bar {remove_bar}",
                ))

        # Sort by bar_start
        deltas.sort(key=lambda d: (d.bar_start, d.bar_end))

        return AIMicroSectionPlan(
            section_index=section.index,
            section_label=section.label,
            section_type=section.section_type.value,
            total_bars=bars,
            bar_ranges=deltas,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_delta(delta: AIMicroBarRange, section_label: str) -> List[str]:
        """Validate a single delta.  Returns a list of error strings."""
        errors: List[str] = []

        # Bar range must be valid
        if delta.bar_start > delta.bar_end:
            errors.append(
                f"[{section_label}] Invalid bar range: bar_start={delta.bar_start} > bar_end={delta.bar_end}"
            )

        # Reason must not be vague
        if _is_vague(delta.reason):
            errors.append(
                f"[{section_label}] Vague delta reason rejected: '{delta.reason}'"
            )

        # Behavior strings must not be vague
        for field_name, value in [
            ("kick_behavior", delta.kick_behavior),
            ("hat_behavior", delta.hat_behavior),
            ("bass_behavior", delta.bass_behavior),
            ("melody_behavior", delta.melody_behavior),
        ]:
            if value and _is_vague(value):
                errors.append(
                    f"[{section_label}] Vague {field_name} rejected: '{value}'"
                )

        return errors


# Module-level singleton
ai_micro_planner = AIMicroPlanner()
