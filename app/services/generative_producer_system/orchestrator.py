"""
Orchestrator for the Generative Producer System.

Ties together:
1. Genre profile resolution
2. Event generation
3. Renderer mapping / skipped event collection
4. Validation
5. Plan assembly and metadata scoring
"""

from __future__ import annotations

import logging
import random as _random_mod
from collections import defaultdict
from typing import Any

from app.services.generative_producer_system.types import (
    ProducerEvent,
    ProducerPlan,
    SkippedEvent,
    SUPPORTED_GENRES,
)
from app.services.generative_producer_system.genre_profiles import get_genre_profile
from app.services.generative_producer_system.event_generator import generate_events
from app.services.generative_producer_system.renderer_mapping import map_event
from app.services.generative_producer_system.validator import validate_producer_plan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scoring helper
# ---------------------------------------------------------------------------


def _compute_section_variation_score(events: list[ProducerEvent]) -> float:
    """Score 0–1 expressing how much variation exists across sections.

    Based on average number of distinct event types per section name.
    """
    if not events:
        return 0.0
    by_section: dict[str, set[str]] = defaultdict(set)
    for ev in events:
        by_section[ev.section_name].add(ev.event_type)
    # Average distinct types per section, normalised by a ceiling of 5
    avg = sum(len(v) for v in by_section.values()) / len(by_section)
    return min(1.0, round(avg / 5.0, 4))


def _compute_event_count_per_section(events: list[ProducerEvent]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for ev in events:
        counts[ev.section_name] += 1
    return dict(counts)


# ---------------------------------------------------------------------------
# Deterministic fallback event generator
# ---------------------------------------------------------------------------

# Mapping of fallback move per section type (section_name → render_action).
# These fire when the full event pipeline produces zero kept events so the
# arrangement is never rendered as plain loop repetition.
_FALLBACK_MOVES: dict[str, str] = {
    "intro":     "filter_role",
    "verse":     "add_drum_fill",
    "verse_2":   "add_hat_roll",
    "pre_hook":  "filter_role",
    "hook":      "add_impact",
    "hook_2":    "add_fx_riser",
    "bridge":    "filter_role",
    "breakdown": "filter_role",
    "outro":     "fade_role",
}


def _generate_fallback_events(
    sections: list[dict[str, Any]],
    seed: int,
) -> list[ProducerEvent]:
    """Return one deterministic fallback ProducerEvent per section.

    Called when the full generator+mapper pipeline produces zero kept events.
    Events use only ``SUPPORTED_RENDER_ACTIONS`` so they survive the mapper
    without being skipped.  Dropout moves (``mute_role``) are intentionally
    excluded to prevent dead-air in the fallback path.
    """
    rng = _random_mod.Random(seed)
    events: list[ProducerEvent] = []
    for section in sections:
        name: str = str(section.get("name", "verse")).lower()
        bar_start: int = int(section.get("bar_start", 0) or 0)
        bar_end: int = int(section.get("bar_end", bar_start + 4) or (bar_start + 4))
        bars: int = max(1, bar_end - bar_start)
        render_action = _FALLBACK_MOVES.get(name, "add_drum_fill")
        # Place the event 3/4 through the section (pre-boundary position)
        event_bar = bar_start + max(0, bars * 3 // 4)
        event_end = min(bar_end, event_bar + 1)
        events.append(
            ProducerEvent.make(
                section_name=name,
                occurrence_index=0,
                bar_start=event_bar,
                bar_end=event_end,
                target_role="drums",
                event_type=render_action,
                intensity=rng.uniform(0.5, 0.8),
                parameters={},
                render_action=render_action,
                reason=f"Fallback move for {name}: {render_action}",
            )
        )
    return events


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class GenerativeProducerOrchestrator:
    """Runs the full generative producer pipeline and returns a ProducerPlan."""

    def __init__(
        self,
        *,
        available_roles: list[str],
        arrangement_id: int = 0,
        correlation_id: str = "",
    ) -> None:
        self.available_roles = available_roles
        self.arrangement_id = arrangement_id
        self.correlation_id = correlation_id

    def run(
        self,
        *,
        sections: list[dict[str, Any]],
        genre: str,
        vibe: str,
        seed: int,
    ) -> ProducerPlan:
        """Generate a ProducerPlan for the arrangement.

        Parameters
        ----------
        sections:
            Section template — list of dicts with at minimum ``name`` and
            ``bars`` (or ``bar_start`` / ``bar_end``).
        genre:
            Target genre string.
        vibe:
            Vibe string from the arrangement job (informational only for now).
        seed:
            Deterministic random seed.

        Returns
        -------
        ProducerPlan
        """
        # Normalise genre
        normalised_genre = (genre or "generic").lower().strip()
        if normalised_genre not in SUPPORTED_GENRES:
            logger.info(
                "GENERATIVE_PRODUCER [arr=%d] genre=%r not in supported set — using generic",
                self.arrangement_id,
                normalised_genre,
            )
            normalised_genre = "generic"

        profile = get_genre_profile(normalised_genre)

        # Generate raw events
        raw_events = generate_events(
            sections=sections,
            profile=profile,
            available_roles=self.available_roles,
            seed=seed,
        )

        # Map events through renderer; collect skipped
        kept_events: list[ProducerEvent] = []
        skipped_events: list[SkippedEvent] = []
        for ev in raw_events:
            mapped, skip = map_event(ev)
            if mapped is not None:
                kept_events.append(mapped)
            else:
                skipped_events.append(skip)  # type: ignore[arg-type]

        # Validate plan
        plan = ProducerPlan(
            genre=normalised_genre,
            vibe=vibe or "",
            seed=seed,
            events=kept_events,
            skipped_events=skipped_events,
        )
        validation_result = validate_producer_plan(plan)

        # Attach validation warnings
        plan.warnings = list(validation_result.warnings)
        if not validation_result.is_valid:
            for err in validation_result.errors:
                plan.warnings.append(f"[ERROR] {err}")

        # If no events survived the generator+mapper pipeline, inject deterministic
        # fallback moves so the arrangement is never rendered as plain loop repetition.
        if not plan.events and sections:
            plan.events = _generate_fallback_events(sections, seed)
            plan.warnings.append("fallback_events_used: no generator events survived")

        # Compute scores
        plan.section_variation_score = _compute_section_variation_score(plan.events)
        plan.event_count_per_section = _compute_event_count_per_section(plan.events)

        logger.info(
            "GENERATIVE_PRODUCER [arr=%d] genre=%r vibe=%r seed=%d "
            "events=%d skipped=%d variation_score=%.4f warnings=%d",
            self.arrangement_id,
            normalised_genre,
            vibe,
            seed,
            len(plan.events),
            len(skipped_events),
            plan.section_variation_score,
            len(plan.warnings),
        )

        return plan


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def plan_to_dict(plan: ProducerPlan) -> dict[str, Any]:
    """Serialise a ProducerPlan to a JSON-safe dict."""
    return plan.to_dict()
