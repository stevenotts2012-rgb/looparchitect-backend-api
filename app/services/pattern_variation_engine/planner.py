"""
Core planner for the Pattern Variation Engine.

:class:`PatternVariationPlanner` converts a high-level section specification
into a :class:`PatternVariationPlan` by:

1. Iterating over each section in arrangement order.
2. Determining the occurrence index for the section type.
3. Delegating to drum, melodic, and bass pattern sub-planners.
4. Respecting the variation budget set by source quality.
5. Recording state for deterministic repeated-section differentiation.

Usage::

    planner = PatternVariationPlanner(source_quality="true_stems")
    spec = [
        {"section_type": "intro",    "section_name": "Intro",    "bars": 8},
        {"section_type": "verse",    "section_name": "Verse 1",  "bars": 16},
        {"section_type": "pre_hook", "section_name": "Pre-Hook", "bars": 8},
        {"section_type": "hook",     "section_name": "Hook 1",   "bars": 16},
        {"section_type": "verse",    "section_name": "Verse 2",  "bars": 16},
        {"section_type": "hook",     "section_name": "Hook 2",   "bars": 16},
        {"section_type": "outro",    "section_name": "Outro",    "bars": 8},
    ]
    plan = planner.build_plan(spec)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.services.pattern_variation_engine.bass_patterns import build_bass_plan
from app.services.pattern_variation_engine.drum_patterns import build_drum_plan
from app.services.pattern_variation_engine.melodic_patterns import build_melodic_plan
from app.services.pattern_variation_engine.state import PatternVariationState
from app.services.pattern_variation_engine.types import (
    PatternSectionPlan,
    PatternVariationPlan,
)

logger = logging.getLogger(__name__)

# Variation budget (max simultaneous pattern events) per source quality mode.
# These caps prevent over-engineering weak sources.
# true_stems supports all 3 layers (drums + melody + bass) fully — the
# richest hook can generate up to ~9 events so the budget is set accordingly.
_VARIATION_BUDGET: Dict[str, int] = {
    "true_stems": 12,
    "zip_stems": 9,
    "ai_separated": 3,
    "stereo_fallback": 0,
}

# Energy targets per section type — used for state energy tracking.
_SECTION_ENERGY: Dict[str, float] = {
    "intro": 0.3,
    "verse": 0.55,
    "pre_hook": 0.65,
    "hook": 0.9,
    "bridge": 0.35,
    "breakdown": 0.25,
    "outro": 0.2,
}


class PatternVariationPlanner:
    """Builds a :class:`PatternVariationPlan` from a structured section spec.

    Parameters
    ----------
    source_quality:
        Source quality mode string (``"true_stems"``, ``"zip_stems"``,
        ``"ai_separated"``, or ``"stereo_fallback"``).
        Controls variation budget and which pattern actions are available.
    """

    def __init__(self, source_quality: str = "true_stems") -> None:
        self.source_quality = source_quality.lower()
        self._budget = _VARIATION_BUDGET.get(self.source_quality, 3)

    def build_plan(self, section_spec: List[Dict]) -> PatternVariationPlan:
        """Build and return a :class:`PatternVariationPlan` from *section_spec*.

        Parameters
        ----------
        section_spec:
            Ordered list of dicts.  Each dict must have at minimum:

            * ``"section_type"`` — canonical section type (e.g. ``"verse"``).
            * ``"section_name"`` — human-readable label (e.g. ``"Verse 1"``).
            * ``"bars"``         — integer bar count.

        Returns
        -------
        PatternVariationPlan
            Fully populated plan.  Stereo-fallback sources return a plan with
            empty event lists but do not raise.
        """
        state = PatternVariationState()
        plan = PatternVariationPlan(source_quality=self.source_quality)

        for item in section_spec:
            section_type: str = str(item.get("section_type", "verse")).lower()
            section_name: str = str(item.get("section_name", section_type.title()))
            bars: int = max(1, int(item.get("bars", 8)))

            occurrence = state.next_occurrence(section_type)
            section_plan = self._build_section_plan(
                section_type=section_type,
                section_name=section_name,
                bars=bars,
                occurrence=occurrence,
            )

            # Track state for deterministic decisions
            self._update_state(state, section_type, section_plan)
            plan.sections.append(section_plan)

            plan.decision_log.append(
                f"{section_name} (occ={occurrence}): "
                f"{len(section_plan.events)} pattern events "
                f"[budget={self._budget}, sq={self.source_quality}]"
            )

        return plan

    # ------------------------------------------------------------------ #
    # Section construction                                                 #
    # ------------------------------------------------------------------ #

    def _build_section_plan(
        self,
        section_type: str,
        section_name: str,
        bars: int,
        occurrence: int,
    ) -> PatternSectionPlan:
        """Assemble pattern events from drum, melodic, and bass sub-planners."""
        section_plan = PatternSectionPlan(
            section_name=section_name,
            section_type=section_type,
            occurrence=occurrence,
            bars=bars,
            source_quality=self.source_quality,
            variation_budget=self._budget,
        )

        if self._budget == 0:
            section_plan.notes = "stereo_fallback — no pattern variation applied"
            return section_plan

        drum_events = build_drum_plan(
            section_type=section_type,
            occurrence=occurrence,
            bars=bars,
            source_quality=self.source_quality,
        )
        melodic_events = build_melodic_plan(
            section_type=section_type,
            occurrence=occurrence,
            bars=bars,
            source_quality=self.source_quality,
        )
        bass_events = build_bass_plan(
            section_type=section_type,
            occurrence=occurrence,
            bars=bars,
            source_quality=self.source_quality,
        )

        all_events = drum_events + melodic_events + bass_events

        # Enforce variation budget: cap total simultaneous pattern events
        if len(all_events) > self._budget:
            all_events = all_events[: self._budget]
            logger.debug(
                "planner: %s occ=%d — trimmed to budget %d",
                section_name, occurrence, self._budget,
            )

        section_plan.events = all_events
        section_plan.notes = self._build_notes(section_type, occurrence, all_events)
        return section_plan

    # ------------------------------------------------------------------ #
    # State updates                                                        #
    # ------------------------------------------------------------------ #

    def _update_state(
        self,
        state: PatternVariationState,
        section_type: str,
        section_plan: PatternSectionPlan,
    ) -> None:
        """Update mutable state from the freshly built section plan."""
        drum_actions = [
            e.pattern_action
            for e in section_plan.events
            if e.role in ("drums", "percussion")
        ]
        melody_actions = [
            e.pattern_action
            for e in section_plan.events
            if e.role == "melody"
        ]

        if drum_actions:
            state.update_drum_behavior(section_type, drum_actions[-1])
        if melody_actions:
            state.update_melody_behavior(section_type, melody_actions[-1])
        if section_type == "hook":
            state.update_hook_pattern_style(section_plan.active_actions)

        state.record_pattern_combination(section_type, section_plan.active_actions)
        energy = _SECTION_ENERGY.get(section_type, 0.5)
        state.record_energy(energy)

    # ------------------------------------------------------------------ #
    # Notes builder                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_notes(section_type: str, occurrence: int, events: list) -> str:
        if not events:
            return f"{section_type} occ={occurrence}: no pattern variation (default groove)"
        action_names = ", ".join(e.pattern_action.value for e in events)
        return f"{section_type} occ={occurrence}: {action_names}"
