"""
Validator for the Generative Producer System.

Checks:
- Every event has a valid bar range.
- Every event has a supported render_action or is logged as skipped.
- Intro is sparse (no full-energy events).
- Hook has the strongest payoff (highest average intensity).
- Repeated sections differ from prior occurrences.
- Outro is simplified.
- No unsupported roles.
- No duplicate destructive events in the same bar window.
"""

from __future__ import annotations

from typing import Any

from app.services.generative_producer_system.types import (
    ProducerEvent,
    SkippedEvent,
    ProducerPlan,
    SUPPORTED_RENDER_ACTIONS,
)
from app.services.generative_producer_system.producer_rules import (
    events_clash,
    is_hook_section,
    is_intro_section,
    is_outro_section,
)
from app.services.generative_producer_system.renderer_mapping import (
    map_event,
    validate_render_action,
)

# ---------------------------------------------------------------------------
# Supported roles (expanded to cover all common stem roles)
# ---------------------------------------------------------------------------

_SUPPORTED_ROLES: frozenset[str] = frozenset(
    {
        "drums",
        "percussion",
        "bass",
        "melody",
        "harmony",
        "pads",
        "fx",
        "accent",
        "vocal",
        "vocals",
        "lead",
        "synth",
        "strings",
        "horn",
        "kick",
        "snare",
        "hats",
        "clap",
        "pad",
    }
)

# Events with intensity above this threshold are considered "high energy"
_HIGH_ENERGY_THRESHOLD = 0.75


def _avg_intensity(events: list[ProducerEvent]) -> float:
    if not events:
        return 0.0
    return sum(e.intensity for e in events) / len(events)


def _max_intensity(events: list[ProducerEvent]) -> float:
    if not events:
        return 0.0
    return max(e.intensity for e in events)


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------


class ValidationResult:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------


def _check_bar_ranges(events: list[ProducerEvent], result: ValidationResult) -> None:
    for ev in events:
        if ev.bar_start < 0:
            result.error(f"Event {ev.event_id} ({ev.section_name}): bar_start < 0")
        if ev.bar_end <= ev.bar_start:
            result.error(
                f"Event {ev.event_id} ({ev.section_name}): bar_end={ev.bar_end} <= bar_start={ev.bar_start}"
            )


def _check_render_actions(
    events: list[ProducerEvent],
    result: ValidationResult,
) -> tuple[list[ProducerEvent], list[SkippedEvent]]:
    """Map events to render actions; collect skipped events for unsupported types."""
    kept: list[ProducerEvent] = []
    skipped: list[SkippedEvent] = []
    for ev in events:
        mapped_ev, skip = map_event(ev)
        if mapped_ev is not None:
            kept.append(mapped_ev)
        else:
            skipped.append(skip)  # type: ignore[arg-type]
    return kept, skipped


def _check_intro_sparse(events: list[ProducerEvent], result: ValidationResult) -> None:
    intro_events = [e for e in events if is_intro_section(e.section_name)]
    high_energy = [e for e in intro_events if e.intensity > _HIGH_ENERGY_THRESHOLD]
    if high_energy:
        result.warn(
            f"Intro has {len(high_energy)} high-energy event(s) (intensity > {_HIGH_ENERGY_THRESHOLD}). "
            "Intro should be sparse."
        )


def _check_hook_strongest(events: list[ProducerEvent], result: ValidationResult) -> None:
    hook_events = [e for e in events if is_hook_section(e.section_name)]
    non_hook_non_intro = [
        e for e in events
        if not is_hook_section(e.section_name) and not is_intro_section(e.section_name)
    ]
    if not hook_events:
        result.warn("No hook events found. Hook should have the strongest payoff.")
        return
    hook_avg = _avg_intensity(hook_events)
    other_avg = _avg_intensity(non_hook_non_intro)
    if non_hook_non_intro and hook_avg <= other_avg:
        result.warn(
            f"Hook average intensity ({hook_avg:.2f}) is not greater than non-hook average "
            f"({other_avg:.2f}). Hook should have the strongest payoff."
        )


def _check_outro_simplified(events: list[ProducerEvent], result: ValidationResult) -> None:
    outro_events = [e for e in events if is_outro_section(e.section_name)]
    all_events_energy = _avg_intensity(events)
    outro_energy = _avg_intensity(outro_events)
    if outro_events and all_events_energy > 0 and outro_energy > all_events_energy * 0.8:
        result.warn(
            f"Outro average intensity ({outro_energy:.2f}) is not significantly lower than "
            f"arrangement average ({all_events_energy:.2f}). Outro should simplify."
        )


def _check_repeated_sections_differ(
    events: list[ProducerEvent],
    result: ValidationResult,
) -> None:
    """Check that repeated sections (occurrence_index > 0) use at least one different event type."""
    from collections import defaultdict
    section_types: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for ev in events:
        section_types[ev.section_name][ev.occurrence_index].add(ev.event_type)

    for section_name, occurrences in section_types.items():
        occurrence_indices = sorted(occurrences.keys())
        for i in range(1, len(occurrence_indices)):
            prev_idx = occurrence_indices[i - 1]
            curr_idx = occurrence_indices[i]
            prev_types = occurrences[prev_idx]
            curr_types = occurrences[curr_idx]
            if prev_types == curr_types:
                result.warn(
                    f"Section '{section_name}' occurrence {curr_idx} uses identical event types "
                    f"to occurrence {prev_idx}. Repeated sections should differ."
                )


def _check_no_unsupported_roles(events: list[ProducerEvent], result: ValidationResult) -> None:
    for ev in events:
        if ev.target_role not in _SUPPORTED_ROLES:
            result.warn(
                f"Event {ev.event_id} ({ev.section_name}): target_role={ev.target_role!r} "
                "is not a known role."
            )


def _check_no_destructive_clashes(events: list[ProducerEvent], result: ValidationResult) -> None:
    event_dicts = [e.to_dict() for e in events]
    for i, ev_a in enumerate(event_dicts):
        for ev_b in event_dicts[i + 1:]:
            if events_clash(ev_a, ev_b):
                result.warn(
                    f"Destructive event clash: event {ev_a['event_id']} and "
                    f"{ev_b['event_id']} in section '{ev_a['section_name']}' "
                    f"(type={ev_a['event_type']!r}, role={ev_a['target_role']!r})"
                )


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------


def validate_producer_plan(
    plan: ProducerPlan,
) -> ValidationResult:
    """Run all validators against a ProducerPlan.

    Returns a ValidationResult with any errors and warnings.
    The plan is not mutated.
    """
    result = ValidationResult()
    events = plan.events

    _check_bar_ranges(events, result)
    _check_intro_sparse(events, result)
    _check_hook_strongest(events, result)
    _check_outro_simplified(events, result)
    _check_repeated_sections_differ(events, result)
    _check_no_unsupported_roles(events, result)
    _check_no_destructive_clashes(events, result)

    # Check render actions on plan events (already mapped by orchestrator)
    for ev in events:
        if not validate_render_action(ev.render_action):
            result.error(
                f"Event {ev.event_id} ({ev.section_name}): render_action={ev.render_action!r} "
                "is not supported."
            )

    return result
