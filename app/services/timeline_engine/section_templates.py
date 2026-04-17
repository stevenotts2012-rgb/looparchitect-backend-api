"""
Deterministic section templates for the timeline engine.

Each template returns a :class:`~app.services.timeline_engine.types.TimelineSection`
populated with sensible defaults and a baseline set of events.  Templates are
*deterministic* — given the same inputs they always produce the same output so
that the arrangement engine is reproducible.

Available templates
-------------------
- intro
- verse
- pre_hook
- hook
- bridge
- breakdown
- outro
"""

from typing import List, Optional

from app.services.timeline_engine.types import TimelineEvent, TimelineSection
from app.services.timeline_engine.event_engine import (
    make_add_layer,
    make_remove_layer,
    make_drop_kick,
    make_add_percussion,
    make_filter_sweep,
    make_drum_fill,
    make_pattern_change,
    make_delayed_entry,
    make_silence_gap,
    make_reverse_fx,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def build_intro_section(
    bars: int = 8,
    available_roles: Optional[List[str]] = None,
) -> TimelineSection:
    """Sparse intro — minimal layers, gradual entry.

    Energy is intentionally low to leave headroom for the build.
    """
    roles = available_roles or ["kick", "bass"]
    active_roles = roles[:2]  # intentionally sparse — max 2 roles at start

    events: List[TimelineEvent] = []

    if active_roles:
        # Bring in the first available role at bar 1
        events.append(make_add_layer(bar_start=1, bar_end=1, target_role=active_roles[0]))

    if len(active_roles) >= 2 and bars >= 4:
        # Bring in second role halfway through
        mid = bars // 2
        events.append(make_add_layer(bar_start=mid, bar_end=mid, target_role=active_roles[1]))

    if bars >= 6:
        # Optional delayed entry for texture
        events.append(make_delayed_entry(
            bar_start=bars - 1,
            bar_end=bars,
            target_role=active_roles[0],
            delay_subdivision="1/8",
        ))

    return TimelineSection(
        name="intro",
        bars=bars,
        target_energy=_clamp(0.2),
        target_density=_clamp(0.2),
        active_roles=list(active_roles),
        events=events,
    )


def build_verse_section(
    bars: int = 16,
    available_roles: Optional[List[str]] = None,
    occurrence: int = 1,
) -> TimelineSection:
    """Groove-focused verse — steady rhythm, moderate density.

    The *occurrence* parameter drives variation on repeated verses.
    """
    roles = available_roles or ["kick", "bass", "hats", "melody"]
    active_roles = roles[:4]

    events: List[TimelineEvent] = []

    # Establish groove at bar 1
    if active_roles:
        events.append(make_add_layer(bar_start=1, bar_end=1, target_role=active_roles[0]))

    # Pattern change partway through to keep interest
    change_bar = max(5, bars // 2)
    if len(active_roles) >= 2:
        events.append(make_pattern_change(
            bar_start=change_bar,
            bar_end=change_bar + 1,
            target_role=active_roles[1],
            new_pattern=f"verse_v{occurrence}_groove",
        ))

    # On repeated verses add a fill near the end
    if occurrence > 1 and bars >= 8:
        events.append(make_drum_fill(bar_start=bars - 1, duration_bars=1))

    # Ensure something changes every 4–8 bars
    if bars > 8:
        events.append(make_add_percussion(
            bar_start=5,
            bar_end=bars,
            target_role="percussion",
        ))

    return TimelineSection(
        name="verse",
        bars=bars,
        target_energy=_clamp(0.45 + 0.05 * (occurrence - 1)),
        target_density=_clamp(0.5),
        active_roles=list(active_roles),
        events=events,
    )


def build_pre_hook_section(
    bars: int = 8,
    available_roles: Optional[List[str]] = None,
) -> TimelineSection:
    """Tension-building pre-hook — filter sweep and rising energy."""
    roles = available_roles or ["kick", "bass", "hats", "synth", "melody"]
    active_roles = roles[:5]

    events: List[TimelineEvent] = []

    # Rising filter sweep across the whole section
    events.append(make_filter_sweep(
        bar_start=1,
        bar_end=bars,
        direction="low_to_high",
        cutoff_start=400,
        cutoff_end=16000,
    ))

    # Add percussion layer for tension
    if len(active_roles) >= 4:
        events.append(make_add_percussion(
            bar_start=1,
            bar_end=bars,
            target_role="percussion",
            pattern="build_eighth",
        ))

    # Drop kick on the last bar for impact
    events.append(make_drop_kick(bar_start=bars, intensity=1.0))

    # Reverse FX into the drop
    if bars >= 4:
        events.append(make_reverse_fx(bar_start=bars - 1, bar_end=bars))

    return TimelineSection(
        name="pre_hook",
        bars=bars,
        target_energy=_clamp(0.7),
        target_density=_clamp(0.65),
        active_roles=list(active_roles),
        events=events,
    )


def build_hook_section(
    bars: int = 16,
    available_roles: Optional[List[str]] = None,
    occurrence: int = 1,
) -> TimelineSection:
    """High-energy payoff hook — maximum layers, novelty required.

    Hooks must introduce novelty relative to previous occurrences.
    """
    roles = available_roles or ["kick", "bass", "hats", "melody", "synth", "pad"]
    active_roles = roles[:6]

    events: List[TimelineEvent] = []

    # Full drop at bar 1
    events.append(make_drop_kick(bar_start=1, intensity=1.0))

    # Ensure all layers are added immediately
    for i, role in enumerate(active_roles[1:], start=1):
        events.append(make_add_layer(bar_start=1, bar_end=1, target_role=role, fade_bars=0))

    # Add novelty on every occurrence
    novelty_bar = max(5, bars // 2)
    if occurrence == 1:
        # First hook: pattern change for freshness
        if active_roles:
            events.append(make_pattern_change(
                bar_start=novelty_bar,
                bar_end=novelty_bar + 2,
                target_role=active_roles[0],
                new_pattern="hook_variant_a",
            ))
    else:
        # Subsequent hooks: add percussion variation
        events.append(make_add_percussion(
            bar_start=novelty_bar,
            bar_end=bars,
            target_role="percussion",
            pattern=f"hook_perc_v{occurrence}",
        ))

    # Drum fill near the end of every hook
    if bars >= 8:
        events.append(make_drum_fill(bar_start=bars - 1, duration_bars=1, intensity=1.0))

    return TimelineSection(
        name="hook",
        bars=bars,
        target_energy=_clamp(0.9),
        target_density=_clamp(0.85),
        active_roles=list(active_roles),
        events=events,
    )


def build_bridge_section(
    bars: int = 8,
    available_roles: Optional[List[str]] = None,
) -> TimelineSection:
    """Contrast bridge — reduced density, textural shift."""
    roles = available_roles or ["kick", "bass", "pad"]
    active_roles = roles[:3]  # intentionally fewer roles

    events: List[TimelineEvent] = []

    # Remove layers for contrast
    if len(active_roles) >= 2:
        events.append(make_remove_layer(bar_start=1, bar_end=2, target_role=active_roles[-1]))

    # Silence gap for dramatic effect
    if bars >= 6:
        events.append(make_silence_gap(bar_start=3, bar_end=4, target_role=None))

    # Gradual re-introduction
    if active_roles:
        re_entry_bar = min(max(3, bars - 2), bars)
        events.append(make_add_layer(
            bar_start=re_entry_bar,
            bar_end=bars,
            target_role=active_roles[0],
            fade_bars=2,
        ))

    return TimelineSection(
        name="bridge",
        bars=bars,
        target_energy=_clamp(0.4),
        target_density=_clamp(0.3),
        active_roles=list(active_roles),
        events=events,
    )


def build_breakdown_section(
    bars: int = 8,
    available_roles: Optional[List[str]] = None,
) -> TimelineSection:
    """Stripped-back breakdown — maximum contrast with surrounding sections."""
    roles = available_roles or ["bass", "pad"]
    active_roles = roles[:2]

    events: List[TimelineEvent] = []

    # Silence gap at the start for impact
    events.append(make_silence_gap(bar_start=1, bar_end=2))

    # Low filter sweep downward
    events.append(make_filter_sweep(
        bar_start=1,
        bar_end=bars,
        direction="high_to_low",
        cutoff_start=16000,
        cutoff_end=300,
    ))

    # Delayed re-entry of remaining roles
    for role in active_roles:
        events.append(make_delayed_entry(
            bar_start=3,
            bar_end=bars,
            target_role=role,
            delay_subdivision="1/2",
        ))

    return TimelineSection(
        name="breakdown",
        bars=bars,
        target_energy=_clamp(0.2),
        target_density=_clamp(0.15),
        active_roles=list(active_roles),
        events=events,
    )


def build_outro_section(
    bars: int = 8,
    available_roles: Optional[List[str]] = None,
) -> TimelineSection:
    """Progressive outro — layers removed one by one until silence."""
    roles = available_roles or ["kick", "bass", "hats"]
    active_roles = list(roles[:4])

    events: List[TimelineEvent] = []

    # Progressively remove layers across the section
    step = max(1, bars // max(len(active_roles), 1))
    for i, role in enumerate(reversed(active_roles)):
        remove_bar = min(1 + i * step, bars)
        events.append(make_remove_layer(
            bar_start=remove_bar,
            bar_end=remove_bar + 1,
            target_role=role,
            fade_bars=2,
        ))

    # Optional final silence gap
    if bars >= 4:
        events.append(make_silence_gap(bar_start=bars - 1, bar_end=bars))

    return TimelineSection(
        name="outro",
        bars=bars,
        target_energy=_clamp(0.15),
        target_density=_clamp(0.1),
        active_roles=list(active_roles),
        events=events,
    )


# ---------------------------------------------------------------------------
# Dispatch helper
# ---------------------------------------------------------------------------

_TEMPLATE_MAP = {
    "intro": build_intro_section,
    "verse": build_verse_section,
    "pre_hook": build_pre_hook_section,
    "hook": build_hook_section,
    "bridge": build_bridge_section,
    "breakdown": build_breakdown_section,
    "outro": build_outro_section,
}


def get_section_template(section_type: str):
    """Return the template builder for *section_type*, or ``None`` if unknown."""
    return _TEMPLATE_MAP.get(section_type.lower())


def list_section_types():
    """Return the list of supported section type keys."""
    return list(_TEMPLATE_MAP.keys())
