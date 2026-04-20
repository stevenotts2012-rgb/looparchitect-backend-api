"""
Pattern Variation Engine.

Transforms static loop repetition into musically evolving patterns.

The engine operates AFTER the Timeline Engine and BEFORE final rendering.
It runs entirely in shadow mode — results are stored in
``job.render_metadata["pattern_variations"]`` and do NOT alter the live
audio render path.

Design goals:
- Prevent repetition fatigue
- Introduce controlled variation every 4–8 bars
- Differentiate repeated sections (verse 1 vs verse 2, hook 1 vs hook 2)
- Maintain groove consistency while adding movement
- 100 % deterministic: same input → same output

Usage::

    from app.services.pattern_variation_engine.variation_engine import (
        PatternVariationEngine,
    )
    from app.services.pattern_variation_engine.types import VariationContext

    ctx = VariationContext(
        section_name="Hook 2",
        section_index=6,
        section_occurrence_index=1,
        total_occurrences=3,
        bars=16,
        energy=0.9,
        density=0.8,
        active_roles=["drums", "bass", "melody"],
    )
    engine = PatternVariationEngine()
    plan = engine.build_variation_plan(ctx)
"""

from __future__ import annotations

import logging
from typing import List

from app.services.pattern_variation_engine.bass_patterns import build_bass_plan
from app.services.pattern_variation_engine.drum_patterns import build_drum_plan
from app.services.pattern_variation_engine.melodic_patterns import build_melodic_plan
from app.services.pattern_variation_engine.types import (
    PatternVariationEvent,
    VariationContext,
    VariationPlan,
)
from app.services.pattern_variation_engine.variation_rules import (
    apply_energy_alignment_rule,
    apply_hook_priority_rule,
    apply_no_identical_repeat_rule,
    apply_role_safety_rule,
    apply_variation_frequency_rule,
    score_repetition,
)

logger = logging.getLogger(__name__)

# Minimum acceptable repetition score; plans below this are logged as warnings.
_MIN_REPETITION_SCORE = 0.3


class PatternVariationEngine:
    """Converts a :class:`VariationContext` into a :class:`VariationPlan`.

    All strategies are deterministic; no random state is used.  The engine
    delegates to the existing drum / melodic / bass sub-planners and then
    applies the five variation rules to refine the output.
    """

    def build_variation_plan(self, context: VariationContext) -> VariationPlan:
        """Build a variation plan for the section described by *context*.

        Steps
        -----
        1. Derive candidate events from drum, melodic, and bass sub-planners.
        2. Convert internal :class:`PatternEvent` objects to
           :class:`PatternVariationEvent` with human-readable ``variation_type``.
        3. Apply the five variation rules (in order) to refine the event list.
        4. Compute variation density and repetition score.
        5. Reject plans with repetition score < 0.3 (log a warning; return the
           best-effort plan so callers are never blocked).

        Parameters
        ----------
        context:
            Fully populated :class:`VariationContext` for the section.

        Returns
        -------
        VariationPlan
            Populated plan.  The plan's ``repetition_score`` field indicates
            quality — callers may choose to log or surface low-scoring plans.
        """
        section_type = context.section_type
        occurrence = context.occurrence
        bars = context.bars
        source_quality = context.source_quality

        # ------------------------------------------------------------------ #
        # Step 1: Gather candidate events from sub-planners                   #
        # ------------------------------------------------------------------ #
        raw_events: List[PatternVariationEvent] = []

        if "drums" in context.active_roles or "percussion" in context.active_roles:
            raw_events.extend(self._drum_events(section_type, occurrence, bars, source_quality))

        if "melody" in context.active_roles:
            raw_events.extend(self._melodic_events(section_type, occurrence, bars, source_quality))

        if "bass" in context.active_roles:
            raw_events.extend(self._bass_events(section_type, occurrence, bars, source_quality))

        # ------------------------------------------------------------------ #
        # Step 2: Apply variation rules                                        #
        # ------------------------------------------------------------------ #
        applied: List[str] = []

        # Rule 2 — No Identical Repeats (applied before frequency rule so
        # injected events also satisfy the frequency rule)
        applied.extend(apply_no_identical_repeat_rule(context, raw_events))

        # Rule 1 — Variation Frequency
        applied.extend(apply_variation_frequency_rule(context, raw_events))

        # Rule 3 — Energy Alignment
        applied.extend(apply_energy_alignment_rule(context, raw_events))

        # Rule 4 — Role Safety
        applied.extend(apply_role_safety_rule(context, raw_events))

        # Rule 5 — Hook Priority
        applied.extend(apply_hook_priority_rule(context, raw_events))

        # ------------------------------------------------------------------ #
        # Step 3: Compute density and build plan                               #
        # ------------------------------------------------------------------ #
        variation_density = self._compute_density(
            raw_events, context.bars, context.active_roles
        )

        plan = VariationPlan(
            section_name=context.section_name,
            variations=raw_events,
            variation_density=variation_density,
            repetition_score=0.0,  # filled below
            applied_strategies=applied,
        )

        # ------------------------------------------------------------------ #
        # Step 4: Score repetition                                             #
        # ------------------------------------------------------------------ #
        plan.repetition_score = score_repetition(context.active_roles, plan)

        # ------------------------------------------------------------------ #
        # Step 5: Warn on low scores (never raise — shadow mode)              #
        # ------------------------------------------------------------------ #
        if plan.repetition_score < _MIN_REPETITION_SCORE and context.active_roles:
            logger.warning(
                "PatternVariationEngine: low repetition score %.3f for section %r "
                "(occurrence=%d, roles=%s) — plan may sound repetitive",
                plan.repetition_score,
                context.section_name,
                occurrence,
                context.active_roles,
            )

        logger.debug(
            "PatternVariationEngine: section=%r type=%s occ=%d "
            "events=%d density=%.2f score=%.3f strategies=%d",
            context.section_name,
            section_type,
            occurrence,
            len(raw_events),
            variation_density,
            plan.repetition_score,
            len(applied),
        )

        return plan

    # ------------------------------------------------------------------ #
    # Private helpers                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _drum_events(
        section_type: str, occurrence: int, bars: int, source_quality: str
    ) -> List[PatternVariationEvent]:
        """Convert drum sub-planner events to PatternVariationEvents."""
        raw = build_drum_plan(
            section_type=section_type,
            occurrence=occurrence,
            bars=bars,
            source_quality=source_quality,
        )
        result: List[PatternVariationEvent] = []
        for evt in raw:
            result.append(PatternVariationEvent(
                bar_start=evt.bar_start,
                bar_end=evt.bar_end,
                role=evt.role,
                variation_type=evt.pattern_action.value,
                intensity=evt.intensity,
                parameters=dict(evt.parameters),
            ))
        return result

    @staticmethod
    def _melodic_events(
        section_type: str, occurrence: int, bars: int, source_quality: str
    ) -> List[PatternVariationEvent]:
        """Convert melodic sub-planner events to PatternVariationEvents."""
        raw = build_melodic_plan(
            section_type=section_type,
            occurrence=occurrence,
            bars=bars,
            source_quality=source_quality,
        )
        result: List[PatternVariationEvent] = []
        for evt in raw:
            result.append(PatternVariationEvent(
                bar_start=evt.bar_start,
                bar_end=evt.bar_end,
                role=evt.role,
                variation_type=evt.pattern_action.value,
                intensity=evt.intensity,
                parameters=dict(evt.parameters),
            ))
        return result

    @staticmethod
    def _bass_events(
        section_type: str, occurrence: int, bars: int, source_quality: str
    ) -> List[PatternVariationEvent]:
        """Convert bass sub-planner events to PatternVariationEvents."""
        raw = build_bass_plan(
            section_type=section_type,
            occurrence=occurrence,
            bars=bars,
            source_quality=source_quality,
        )
        result: List[PatternVariationEvent] = []
        for evt in raw:
            result.append(PatternVariationEvent(
                bar_start=evt.bar_start,
                bar_end=evt.bar_end,
                role=evt.role,
                variation_type=evt.pattern_action.value,
                intensity=evt.intensity,
                parameters=dict(evt.parameters),
            ))
        return result

    @staticmethod
    def _compute_density(
        variations: List[PatternVariationEvent],
        bars: int,
        active_roles: List[str],
    ) -> float:
        """Compute normalised variation density in [0.0, 1.0].

        Density = (number of variation events) / (max possible events).
        Max possible events = roles × bar-windows.
        """
        if not active_roles or bars < 1:
            return 0.0
        max_events = max(1, len(active_roles) * max(1, bars // 4))
        return min(1.0, len(variations) / max_events)
