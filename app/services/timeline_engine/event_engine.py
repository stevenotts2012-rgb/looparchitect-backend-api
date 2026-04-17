"""
Supported timeline event types and event-generation helpers.
"""

from typing import Optional, List

from app.services.timeline_engine.types import TimelineEvent

# ---------------------------------------------------------------------------
# Catalogue of supported action strings
# ---------------------------------------------------------------------------

#: All recognised event action identifiers.
SUPPORTED_ACTIONS: List[str] = [
    "add_layer",
    "remove_layer",
    "drop_kick",
    "add_percussion",
    "filter_sweep",
    "reverse_fx",
    "drum_fill",
    "pattern_change",
    "delayed_entry",
    "silence_gap",
]


def is_valid_action(action: str) -> bool:
    """Return ``True`` if *action* is a recognised event type."""
    return action in SUPPORTED_ACTIONS


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_add_layer(
    bar_start: int,
    bar_end: int,
    target_role: str,
    fade_bars: int = 1,
) -> TimelineEvent:
    """Create an ``add_layer`` event."""
    return TimelineEvent(
        bar_start=bar_start,
        bar_end=bar_end,
        action="add_layer",
        target_role=target_role,
        parameters={"fade_bars": fade_bars},
    )


def make_remove_layer(
    bar_start: int,
    bar_end: int,
    target_role: str,
    fade_bars: int = 1,
) -> TimelineEvent:
    """Create a ``remove_layer`` event."""
    return TimelineEvent(
        bar_start=bar_start,
        bar_end=bar_end,
        action="remove_layer",
        target_role=target_role,
        parameters={"fade_bars": fade_bars},
    )


def make_drop_kick(
    bar_start: int,
    intensity: float = 1.0,
) -> TimelineEvent:
    """Create a ``drop_kick`` event (single bar impact)."""
    return TimelineEvent(
        bar_start=bar_start,
        bar_end=bar_start,
        action="drop_kick",
        target_role="kick",
        parameters={"intensity": intensity},
    )


def make_add_percussion(
    bar_start: int,
    bar_end: int,
    target_role: str = "percussion",
    pattern: Optional[str] = None,
) -> TimelineEvent:
    """Create an ``add_percussion`` event."""
    params: dict = {}
    if pattern:
        params["pattern"] = pattern
    return TimelineEvent(
        bar_start=bar_start,
        bar_end=bar_end,
        action="add_percussion",
        target_role=target_role,
        parameters=params,
    )


def make_filter_sweep(
    bar_start: int,
    bar_end: int,
    direction: str = "low_to_high",
    cutoff_start: int = 200,
    cutoff_end: int = 18000,
) -> TimelineEvent:
    """Create a ``filter_sweep`` event."""
    return TimelineEvent(
        bar_start=bar_start,
        bar_end=bar_end,
        action="filter_sweep",
        target_role=None,
        parameters={
            "direction": direction,
            "cutoff_start": cutoff_start,
            "cutoff_end": cutoff_end,
        },
    )


def make_reverse_fx(
    bar_start: int,
    bar_end: int,
    target_role: Optional[str] = None,
) -> TimelineEvent:
    """Create a ``reverse_fx`` event."""
    return TimelineEvent(
        bar_start=bar_start,
        bar_end=bar_end,
        action="reverse_fx",
        target_role=target_role,
        parameters={},
    )


def make_drum_fill(
    bar_start: int,
    duration_bars: int = 1,
    intensity: float = 0.8,
) -> TimelineEvent:
    """Create a ``drum_fill`` event."""
    return TimelineEvent(
        bar_start=bar_start,
        bar_end=bar_start + duration_bars - 1,
        action="drum_fill",
        target_role="drums",
        parameters={"intensity": intensity},
    )


def make_pattern_change(
    bar_start: int,
    bar_end: int,
    target_role: str,
    new_pattern: str,
) -> TimelineEvent:
    """Create a ``pattern_change`` event."""
    return TimelineEvent(
        bar_start=bar_start,
        bar_end=bar_end,
        action="pattern_change",
        target_role=target_role,
        parameters={"new_pattern": new_pattern},
    )


def make_delayed_entry(
    bar_start: int,
    bar_end: int,
    target_role: str,
    delay_subdivision: str = "1/4",
) -> TimelineEvent:
    """Create a ``delayed_entry`` event."""
    return TimelineEvent(
        bar_start=bar_start,
        bar_end=bar_end,
        action="delayed_entry",
        target_role=target_role,
        parameters={"delay_subdivision": delay_subdivision},
    )


def make_silence_gap(
    bar_start: int,
    bar_end: int,
    target_role: Optional[str] = None,
) -> TimelineEvent:
    """Create a ``silence_gap`` event."""
    return TimelineEvent(
        bar_start=bar_start,
        bar_end=bar_end,
        action="silence_gap",
        target_role=target_role,
        parameters={},
    )
