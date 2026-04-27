"""
Producer rules engine for the Generative Producer System.

Encodes high-level producer logic:
- Every section must differ from its previous occurrence.
- Hook must have the strongest energy/event payoff.
- Outro must simplify.
- Bridge/breakdown must reset.
- Long sections must change every 4–8 bars.
- Repeated sections must differ from prior occurrences.
- Intro must be sparse.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Section classification helpers
# ---------------------------------------------------------------------------

_HOOK_NAMES = frozenset({"hook", "chorus", "hook_2", "chorus_2"})
_INTRO_NAMES = frozenset({"intro"})
_OUTRO_NAMES = frozenset({"outro"})
_BRIDGE_RESET_NAMES = frozenset({"bridge", "breakdown"})
_PRE_HOOK_NAMES = frozenset({"pre_hook", "prehook", "pre-hook"})


def is_hook_section(section_name: str) -> bool:
    return section_name.lower() in _HOOK_NAMES


def is_intro_section(section_name: str) -> bool:
    return section_name.lower() in _INTRO_NAMES


def is_outro_section(section_name: str) -> bool:
    return section_name.lower() in _OUTRO_NAMES


def is_bridge_reset_section(section_name: str) -> bool:
    return section_name.lower() in _BRIDGE_RESET_NAMES


def is_pre_hook_section(section_name: str) -> bool:
    return section_name.lower() in _PRE_HOOK_NAMES


# ---------------------------------------------------------------------------
# Event-density rules
# ---------------------------------------------------------------------------

# Minimum number of producer events required for each section type.
_SECTION_MIN_EVENTS: dict[str, int] = {
    "intro": 1,
    "verse": 1,
    "verse_2": 2,
    "pre_hook": 1,
    "hook": 2,
    "hook_2": 3,
    "bridge": 1,
    "breakdown": 1,
    "outro": 1,
}

# Energy floors/ceilings per section type for validation.
_SECTION_ENERGY_FLOOR: dict[str, float] = {
    "hook": 0.7,
    "hook_2": 0.8,
}
_SECTION_ENERGY_CEILING: dict[str, float] = {
    "intro": 0.5,
    "outro": 0.45,
    "bridge": 0.65,
    "breakdown": 0.55,
}

# Maximum allowed bars before a new intra-section event should be inserted.
INTRA_SECTION_MAX_BARS = 8


def min_events_for_section(section_name: str) -> int:
    return _SECTION_MIN_EVENTS.get(section_name.lower(), 1)


def energy_floor_for_section(section_name: str) -> float | None:
    return _SECTION_ENERGY_FLOOR.get(section_name.lower())


def energy_ceiling_for_section(section_name: str) -> float | None:
    return _SECTION_ENERGY_CEILING.get(section_name.lower())


# ---------------------------------------------------------------------------
# Variation contracts
# ---------------------------------------------------------------------------


def must_differ_from_prior(
    section_name: str,
    occurrence_index: int,
) -> bool:
    """Return True if this section occurrence must differ from the previous one."""
    return occurrence_index > 0


def should_add_intra_section_variation(
    bar_start: int,
    bar_end: int,
) -> list[int]:
    """Return a list of bar positions at which intra-section events should fire.

    Fires every INTRA_SECTION_MAX_BARS bars inside the section window.
    Returns an empty list for sections ≤ INTRA_SECTION_MAX_BARS bars long.
    """
    length = bar_end - bar_start
    if length <= INTRA_SECTION_MAX_BARS:
        return []
    positions: list[int] = []
    pos = bar_start + INTRA_SECTION_MAX_BARS
    while pos < bar_end:
        positions.append(pos)
        pos += INTRA_SECTION_MAX_BARS
    return positions


# ---------------------------------------------------------------------------
# Destructive-event clash detection
# ---------------------------------------------------------------------------

# These event types are "destructive" — running two of the same type on the
# same role within the same 4-bar window creates an unrecoverable conflict.
_DESTRUCTIVE_TYPES = frozenset({"mute_role", "fade_role", "chop_role"})


def is_destructive_event_type(event_type: str) -> bool:
    return event_type in _DESTRUCTIVE_TYPES


def events_clash(
    event_a: dict[str, Any],
    event_b: dict[str, Any],
    clash_window_bars: int = 4,
) -> bool:
    """Return True if two events create a destructive clash.

    Clash conditions:
    - same target_role
    - both event_types are destructive
    - bar windows overlap within clash_window_bars
    """
    if event_a["target_role"] != event_b["target_role"]:
        return False
    if not (
        is_destructive_event_type(event_a["event_type"])
        and is_destructive_event_type(event_b["event_type"])
    ):
        return False
    # Check for bar-range overlap (inclusive) within the clash window
    a_start, a_end = event_a["bar_start"], event_a["bar_end"]
    b_start, b_end = event_b["bar_start"], event_b["bar_end"]
    # Expand the window by clash_window_bars
    return not (a_end + clash_window_bars < b_start or b_end + clash_window_bars < a_start)
