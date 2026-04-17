"""
Core timeline planner.

:class:`TimelinePlanner` converts a high-level section list (names, bar counts,
available roles) into a :class:`~app.services.timeline_engine.types.TimelinePlan`
by applying deterministic section templates and the core planning rules:

Planning rules enforced
-----------------------
1. Something must change every 4–8 bars when material allows.
2. Repeated sections log at least one variation attempt.
3. Hooks must introduce novelty when source material allows.
4. Bridge/breakdown must reduce density below their neighbours.
5. No flat energy curve — energy must vary by at least 0.1.
6. Weak source material degrades gracefully (fewer events, no crash).
"""

import logging
from typing import Dict, List, Optional

from app.services.timeline_engine.event_engine import (
    make_drum_fill,
    make_pattern_change,
    make_add_percussion,
)
from app.services.timeline_engine.section_templates import (
    build_breakdown_section,
    build_bridge_section,
    build_hook_section,
    build_intro_section,
    build_outro_section,
    build_pre_hook_section,
    build_verse_section,
)
from app.services.timeline_engine.state import TimelineState
from app.services.timeline_engine.types import TimelinePlan, TimelineSection

logger = logging.getLogger(__name__)

# Minimum number of roles before we consider the source material limited
_WEAK_SOURCE_ROLE_THRESHOLD = 2

# Minimum bars between mandatory variation events
_VARIATION_INTERVAL_MIN = 4
_VARIATION_INTERVAL_MAX = 8


class TimelinePlanner:
    """Builds a :class:`TimelinePlan` from a structured section specification.

    Parameters
    ----------
    available_roles:
        All instrument roles present in the source material.  Pass an empty
        list or a single role to trigger graceful-degradation mode.

    Example usage::

        planner = TimelinePlanner(available_roles=["kick", "bass", "hats", "melody"])
        spec = [
            {"name": "intro",  "bars": 8},
            {"name": "verse",  "bars": 16},
            {"name": "hook",   "bars": 16},
            {"name": "outro",  "bars": 8},
        ]
        plan = planner.build_plan(spec)
    """

    def __init__(self, available_roles: Optional[List[str]] = None) -> None:
        self.available_roles: List[str] = list(available_roles or [])
        self._is_weak_source = len(self.available_roles) < _WEAK_SOURCE_ROLE_THRESHOLD

    def build_plan(self, section_spec: List[Dict]) -> TimelinePlan:
        """Build and return a :class:`TimelinePlan` from *section_spec*.

        Parameters
        ----------
        section_spec:
            Ordered list of dicts, each with at minimum ``{"name": str, "bars": int}``.
            An optional ``"roles"`` key overrides which roles are active for that section.

        Returns
        -------
        TimelinePlan
            A fully populated plan.  If source material is weak the plan will
            have fewer events but will not raise.
        """
        state = TimelineState()
        sections: List[TimelineSection] = []

        for spec_item in section_spec:
            name: str = spec_item.get("name", "verse").lower()
            bars: int = int(spec_item.get("bars", 8))
            roles: List[str] = list(spec_item.get("roles") or self.available_roles)
            occurrence: int = state.occurrence_count(name) + 1

            section = self._build_section(name, bars, roles, occurrence)

            # Rule 2: log a variation attempt for every repeated section
            if occurrence > 1:
                success = self._attempt_variation(section, occurrence, roles)
                state.record_variation_attempt(
                    section_name=name,
                    attempt_description=f"occurrence_{occurrence}_variation",
                    success=success,
                )

            # Rule 1: ensure something changes every 4–8 bars
            self._enforce_periodic_changes(section)

            state.record_section(name, section.active_roles, section.target_energy)
            sections.append(section)

        # Rule 5: post-process to avoid flat energy curves
        sections = self._adjust_energy_curve(sections)

        total_bars = sum(s.bars for s in sections)
        energy_curve = [s.target_energy for s in sections]

        return TimelinePlan(
            sections=sections,
            total_bars=total_bars,
            energy_curve=energy_curve,
            variation_log=list(state.variation_history),
            state_snapshot=state.to_dict(),
        )

    # ------------------------------------------------------------------ #
    # Section construction                                                 #
    # ------------------------------------------------------------------ #

    def _build_section(
        self,
        name: str,
        bars: int,
        roles: List[str],
        occurrence: int,
    ) -> TimelineSection:
        """Delegate to the appropriate section template."""
        effective_roles = roles if not self._is_weak_source else roles[:1]

        builders = {
            "intro": lambda: build_intro_section(bars=bars, available_roles=effective_roles),
            "verse": lambda: build_verse_section(
                bars=bars, available_roles=effective_roles, occurrence=occurrence
            ),
            "pre_hook": lambda: build_pre_hook_section(
                bars=bars, available_roles=effective_roles
            ),
            "hook": lambda: build_hook_section(
                bars=bars, available_roles=effective_roles, occurrence=occurrence
            ),
            "bridge": lambda: build_bridge_section(
                bars=bars, available_roles=effective_roles
            ),
            "breakdown": lambda: build_breakdown_section(
                bars=bars, available_roles=effective_roles
            ),
            "outro": lambda: build_outro_section(
                bars=bars, available_roles=effective_roles
            ),
        }

        if name in builders:
            return builders[name]()

        # Unknown section type: create a minimal section
        logger.warning("Unknown section type '%s' — using minimal fallback.", name)
        return TimelineSection(
            name=name,
            bars=bars,
            target_energy=0.5,
            target_density=0.5,
            active_roles=list(effective_roles),
            events=[],
        )

    # ------------------------------------------------------------------ #
    # Rule 1 — periodic changes                                           #
    # ------------------------------------------------------------------ #

    def _enforce_periodic_changes(self, section: TimelineSection) -> None:
        """Inject events to guarantee a change every 4–8 bars when possible.

        In weak-source mode we skip injection to degrade gracefully.
        """
        if self._is_weak_source:
            return
        if section.bars < _VARIATION_INTERVAL_MIN:
            return

        # Find bars that already have an event
        covered_bars = set()
        for event in section.events:
            for b in range(event.bar_start, event.bar_end + 1):
                covered_bars.add(b)

        bar = _VARIATION_INTERVAL_MAX
        while bar <= section.bars:
            if bar not in covered_bars:
                # Inject a lightweight drum fill to mark the change
                fill = make_drum_fill(bar_start=bar, duration_bars=1, intensity=0.5)
                section.events.append(fill)
                covered_bars.add(bar)
            bar += _VARIATION_INTERVAL_MAX

    # ------------------------------------------------------------------ #
    # Rule 2 — variation on repeated sections                             #
    # ------------------------------------------------------------------ #

    def _attempt_variation(
        self,
        section: TimelineSection,
        occurrence: int,
        roles: List[str],
    ) -> bool:
        """Try to add at least one variation event to a repeated section.

        Returns ``True`` if a variation was successfully added.
        """
        if self._is_weak_source:
            return False

        if not roles:
            return False

        try:
            var_bar = max(1, section.bars // 2)
            perc_event = make_add_percussion(
                bar_start=var_bar,
                bar_end=section.bars,
                target_role="percussion",
                pattern=f"{section.name}_v{occurrence}_perc",
            )
            section.events.append(perc_event)
            return True
        except Exception:
            logger.exception("Failed to add variation to section '%s'.", section.name)
            return False

    # ------------------------------------------------------------------ #
    # Rule 5 — no flat energy curve                                       #
    # ------------------------------------------------------------------ #

    def _adjust_energy_curve(
        self, sections: List[TimelineSection]
    ) -> List[TimelineSection]:
        """Nudge energy values to avoid a flat curve.

        If the span of energies across all sections is < 0.1 we adjust the
        first and last sections to create minimal contrast.  This is a
        last-resort nudge only — it should rarely trigger when templates are
        used correctly.
        """
        if not sections:
            return sections

        energies = [s.target_energy for s in sections]
        span = max(energies) - min(energies)

        if span >= 0.1:
            return sections

        logger.warning(
            "Energy curve is flat (span=%.3f). Applying minimal correction.", span
        )

        # Raise first section energy slightly, lower last section energy slightly
        sections[0].target_energy = min(1.0, sections[0].target_energy + 0.1)
        sections[-1].target_energy = max(0.0, sections[-1].target_energy - 0.1)

        return sections
