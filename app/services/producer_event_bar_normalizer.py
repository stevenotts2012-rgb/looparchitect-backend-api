"""Shared producer-event bar normalization utilities."""

from __future__ import annotations


def normalize_producer_event_bar(
    event_bar: int,
    section_start: int,
    section_end: int,
    section_bars: int,
) -> tuple[int, bool]:
    """Normalize producer event bars against a section.

    Returns ``(normalized_bar, invalid_event_bar)``.
    """
    event_bar = int(event_bar)
    section_start = int(section_start)
    section_end = int(section_end)
    section_bars = max(1, int(section_bars))

    if section_start <= event_bar < section_end:
        return event_bar, False
    if 0 <= event_bar < section_bars:
        return section_start + event_bar, False
    return event_bar, True
