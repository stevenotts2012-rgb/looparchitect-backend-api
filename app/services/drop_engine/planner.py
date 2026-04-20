"""
Drop Engine Planner.

Creates a :class:`~app.services.drop_engine.types.DropPlan` from an
arrangement's section sequence by assigning intentional drop events at every
meaningful section boundary.

The planner is:
- deterministic (no randomness)
- stateful within a single run (uses :class:`~app.services.drop_engine.state.DropEngineState`)
- source-quality-aware (degrades gracefully for weak material)
- hook-variation-aware (escalates payoff for later hook repetitions)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.drop_engine.state import DropEngineState
from app.services.drop_engine.templates import select_template
from app.services.drop_engine.types import DropBoundaryPlan, DropPlan

logger = logging.getLogger(__name__)

# Canonical section types that are significant enough to warrant drop planning.
_SIGNIFICANT_SECTIONS = frozenset(
    {
        "intro",
        "verse",
        "pre_hook",
        "hook",
        "bridge",
        "breakdown",
        "outro",
    }
)

# Boundary pairs that are always planned (highest priority).
_ALWAYS_PLAN_BOUNDARIES = frozenset(
    {
        ("pre_hook", "hook"),
        ("bridge", "hook"),
        ("breakdown", "hook"),
    }
)


def _derive_section_type(name: str) -> str:
    """Derive a canonical section type from a raw section name string."""
    n = name.lower().strip()
    for token in ("pre_hook", "pre-hook", "prehook", "buildup", "build"):
        if token in n:
            return "pre_hook"
    for token in ("hook", "chorus", "drop"):
        if token in n:
            return "hook"
    for token in ("verse",):
        if token in n:
            return "verse"
    for token in ("bridge",):
        if token in n:
            return "bridge"
    for token in ("breakdown", "break"):
        if token in n:
            return "breakdown"
    for token in ("intro",):
        if token in n:
            return "intro"
    for token in ("outro",):
        if token in n:
            return "outro"
    return "verse"


def _compute_hook_variation_score(
    boundaries: List[DropBoundaryPlan],
) -> float:
    """Compute a repeated-hook drop variation score for the full plan.

    Heuristics:
    - Only hook-entry boundaries count (pre_hook → hook).
    - Perfect variation: every hook entry uses a different primary event type.
    - Zero variation: all hook entries use the same type.
    - Payoff escalation also rewards the score.

    Returns a float in [0.0, 1.0].
    """
    hook_boundaries = [
        b for b in boundaries
        if b.from_section == "pre_hook" and b.to_section == "hook"
    ]
    if len(hook_boundaries) < 2:
        # Single hook or no hook: neutral score.
        return 0.5

    event_types = [
        b.primary_drop_event.event_type
        for b in hook_boundaries
        if b.primary_drop_event is not None
    ]
    if not event_types:
        return 0.0

    unique_ratio = len(set(event_types)) / len(event_types)

    # Reward payoff escalation: later hooks should have >= earlier hooks.
    payoffs = [b.payoff_score for b in hook_boundaries]
    escalation_bonus = 0.0
    if len(payoffs) >= 2:
        escalations = sum(1 for i in range(1, len(payoffs)) if payoffs[i] >= payoffs[i - 1])
        escalation_bonus = 0.2 * (escalations / (len(payoffs) - 1))

    return min(1.0, unique_ratio * 0.8 + escalation_bonus)


class DropEnginePlanner:
    """Plan intentional drop events across all section boundaries.

    Parameters
    ----------
    source_quality:
        Source quality mode string (e.g. ``"true_stems"``, ``"ai_separated"``,
        ``"stereo_fallback"``).
    available_roles:
        Instrument roles present in the source material.

    Usage::

        planner = DropEnginePlanner(source_quality="true_stems", available_roles=["drums", "bass"])
        drop_plan = planner.build(sections=[...])
    """

    def __init__(
        self,
        source_quality: str = "stereo_fallback",
        available_roles: Optional[List[str]] = None,
    ) -> None:
        self.source_quality = source_quality
        self.available_roles: List[str] = list(available_roles or [])

    def build(
        self,
        sections: List[Dict[str, Any]],
        section_occurrences: Optional[Dict[str, int]] = None,
        energy_curve: Optional[List[float]] = None,
        pattern_variation_summaries: Optional[List[Dict]] = None,
        groove_summaries: Optional[List[Dict]] = None,
        ai_producer_plan_summaries: Optional[List[Dict]] = None,
    ) -> DropPlan:
        """Build a :class:`DropPlan` from an arrangement section sequence.

        Parameters
        ----------
        sections:
            Ordered list of section dicts.  Each dict must contain at least a
            ``type`` or ``name`` key identifying the section type, and
            optionally a ``bars`` key.
        section_occurrences:
            Optional pre-computed per-section-type occurrence counts.
            If ``None``, occurrence counts are derived from the section list.
        energy_curve:
            Optional per-section energy values (same length as *sections*).
        pattern_variation_summaries:
            Optional list of pattern variation plan summaries per section.
        groove_summaries:
            Optional list of groove plan summaries per section.
        ai_producer_plan_summaries:
            Optional list of AI producer plan summaries.

        Returns
        -------
        DropPlan
            The complete drop design plan.
        """
        if not sections:
            return DropPlan(
                boundaries=[],
                total_drop_count=0,
                repeated_hook_drop_variation_score=0.5,
                fallback_used=True,
            )

        state = DropEngineState()
        fallback_used = False
        is_weak = self.source_quality in ("stereo_fallback", "ai_separated")
        if is_weak:
            fallback_used = True

        # Normalise section types.
        section_types: List[str] = []
        for s in sections:
            raw_name = str(s.get("type") or s.get("name") or "verse")
            section_types.append(_derive_section_type(raw_name))

        boundaries: List[DropBoundaryPlan] = []

        for idx in range(len(section_types) - 1):
            from_type = section_types[idx]
            to_type = section_types[idx + 1]

            # Skip identical consecutive types (e.g. verse → verse).
            if from_type == to_type and (from_type, to_type) not in _ALWAYS_PLAN_BOUNDARIES:
                continue

            # Skip boundaries involving insignificant section types.
            if (
                from_type not in _SIGNIFICANT_SECTIONS
                or to_type not in _SIGNIFICANT_SECTIONS
            ):
                continue

            occurrence_index = state.get_occurrence_index(
                f"{from_type} -> {to_type}"
            )

            try:
                boundary_plan = select_template(
                    from_section=from_type,
                    to_section=to_type,
                    occurrence_index=occurrence_index,
                    source_quality=self.source_quality,
                    available_roles=self.available_roles,
                    state=state,
                )
            except Exception as exc:
                logger.warning(
                    "DropEnginePlanner: template selection failed for %s -> %s "
                    "(occurrence %d): %s",
                    from_type, to_type, occurrence_index, exc,
                )
                fallback_used = True
                boundary_plan = DropBoundaryPlan(
                    from_section=from_type,
                    to_section=to_type,
                    occurrence_index=occurrence_index,
                    tension_score=0.20,
                    payoff_score=0.20,
                    primary_drop_event=None,
                    support_events=[],
                    notes=["error_fallback"],
                )

            # Record boundary in state.
            primary_type = (
                boundary_plan.primary_drop_event.event_type
                if boundary_plan.primary_drop_event is not None
                else None
            )
            state.record_boundary(
                boundary_key=f"{from_type} -> {to_type}",
                primary_event_type=primary_type,
                tension_score=boundary_plan.tension_score,
                payoff_score=boundary_plan.payoff_score,
            )

            boundaries.append(boundary_plan)

        total_drop_count = sum(
            1 for b in boundaries if b.primary_drop_event is not None
        )
        variation_score = _compute_hook_variation_score(boundaries)

        return DropPlan(
            boundaries=boundaries,
            total_drop_count=total_drop_count,
            repeated_hook_drop_variation_score=variation_score,
            fallback_used=fallback_used,
        )
