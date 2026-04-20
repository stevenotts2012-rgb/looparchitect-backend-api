"""
Accent Engine for the Groove Engine.

Generates deterministic accent events for:
- Hi-hat accent cycles
- Snare emphasis
- Kick emphasis
- Bass attack emphasis
- Turnaround emphasis near section ends

All accent logic is bar-position based — no random values are used.
Accents affect perceived groove, section confidence, and re-entry impact.
"""

from __future__ import annotations

from typing import List

from app.services.groove_engine.types import GrooveEvent, GrooveProfile


# ---------------------------------------------------------------------------
# Accent cycle helpers
# ---------------------------------------------------------------------------

def _hat_accent_bars(bars: int, density: float, occurrence: int) -> List[int]:
    """Return a deterministic list of bars where hat accents occur.

    Parameters
    ----------
    bars:
        Total bar count of the section.
    density:
        Accent density from the groove profile [0.0, 1.0].
    occurrence:
        1-based section occurrence.  Shifts the cycle phase for repeated sections.
    """
    if density <= 0.05 or bars < 1:
        return []

    # Base cycle: accent every N bars depending on density
    # density 0.0 → no accents; density 1.0 → every bar
    if density >= 0.8:
        step = 1
    elif density >= 0.6:
        step = 2
    elif density >= 0.4:
        step = 4
    elif density >= 0.2:
        step = 8
    else:
        step = 16

    # Phase shift by occurrence so repeated sections feel different
    phase = (occurrence - 1) % step

    accent_bars = []
    for bar in range(1, bars + 1):
        if (bar - 1 - phase) % step == 0:
            accent_bars.append(bar)

    return accent_bars


def _snare_emphasis_bars(bars: int, section_type: str, occurrence: int) -> List[int]:
    """Return bars where snare receives extra emphasis.

    Snare emphasis follows a downbeat-of-phrase pattern — every 4 bars,
    shifted by section type and occurrence for variation.
    """
    emphasis_bars = []
    # Standard snare accent every 4 bars starting at bar 3 or 4
    base_bar = 3 if section_type in ("hook", "pre_hook") else 4
    offset = (occurrence - 1) % 4

    for bar in range(1, bars + 1):
        adjusted = bar - offset
        if adjusted > 0 and (adjusted - base_bar) % 4 == 0:
            emphasis_bars.append(bar)

    return emphasis_bars


def _kick_emphasis_bars(bars: int, section_type: str) -> List[int]:
    """Return bars where kick receives extra emphasis.

    Kick emphasis is minimal and only on strong structural beats
    (bar 1 and the midpoint).
    """
    emphasis_bars = [1]
    midpoint = bars // 2
    if midpoint > 1:
        emphasis_bars.append(midpoint)
    # Add final bar for hooks (re-entry impact)
    if section_type == "hook" and bars > 1:
        emphasis_bars.append(bars)
    return sorted(set(emphasis_bars))


def _turnaround_bars(bars: int) -> List[int]:
    """Return bars near the section end where turnaround accents occur.

    Typically the last 1–2 bars of a section.
    """
    if bars <= 2:
        return [bars]
    return [bars - 1, bars]


# ---------------------------------------------------------------------------
# Accent event builders
# ---------------------------------------------------------------------------

def build_hat_accents(
    profile: GrooveProfile,
    bars: int,
    energy: float,
    occurrence: int,
    source_quality: str,
) -> List[GrooveEvent]:
    """Build deterministic hat accent events for a section.

    Returns an empty list for stereo_fallback or very sparse sections.
    """
    if source_quality == "stereo_fallback":
        return []

    density = profile.accent_density
    # Scale density by energy — high-energy sections get more accents
    effective_density = min(1.0, density * (0.8 + energy * 0.4))

    accent_bars = _hat_accent_bars(bars, effective_density, occurrence)
    if not accent_bars:
        return []

    events = []
    for bar in accent_bars:
        intensity = min(1.0, 0.6 + energy * 0.3)
        # ai_separated: reduce intensity
        if source_quality == "ai_separated":
            intensity *= 0.7
        events.append(GrooveEvent(
            bar_start=bar,
            bar_end=bar,
            role="drums",
            groove_type="hat_accent",
            intensity=round(intensity, 3),
            parameters={"accent_target": "hi_hat"},
        ))

    return events


def build_snare_emphasis(
    profile: GrooveProfile,
    bars: int,
    energy: float,
    section_type: str,
    occurrence: int,
    source_quality: str,
) -> List[GrooveEvent]:
    """Build deterministic snare emphasis events for a section."""
    if source_quality == "stereo_fallback":
        return []
    if profile.accent_density < 0.15:
        return []

    emphasis_bars = _snare_emphasis_bars(bars, section_type, occurrence)
    if not emphasis_bars:
        return []

    events = []
    for bar in emphasis_bars:
        intensity = min(1.0, 0.55 + energy * 0.35)
        if source_quality == "ai_separated":
            intensity *= 0.75
        events.append(GrooveEvent(
            bar_start=bar,
            bar_end=bar,
            role="drums",
            groove_type="snare_emphasis",
            intensity=round(intensity, 3),
            parameters={"accent_target": "snare"},
        ))

    return events


def build_kick_emphasis(
    profile: GrooveProfile,
    bars: int,
    energy: float,
    section_type: str,
    source_quality: str,
) -> List[GrooveEvent]:
    """Build deterministic kick emphasis events for a section."""
    if source_quality == "stereo_fallback":
        return []
    # Only add kick emphasis when energy is meaningful
    if energy < 0.4 and section_type not in ("hook", "pre_hook"):
        return []

    emphasis_bars = _kick_emphasis_bars(bars, section_type)
    events = []
    for bar in emphasis_bars:
        intensity = min(1.0, 0.5 + energy * 0.4)
        if source_quality == "ai_separated":
            intensity *= 0.7
        events.append(GrooveEvent(
            bar_start=bar,
            bar_end=bar,
            role="drums",
            groove_type="kick_emphasis",
            intensity=round(intensity, 3),
            parameters={"accent_target": "kick"},
        ))

    return events


def build_bass_attack_emphasis(
    profile: GrooveProfile,
    bars: int,
    energy: float,
    section_type: str,
    occurrence: int,
    source_quality: str,
) -> List[GrooveEvent]:
    """Build bass attack emphasis events — emphasises re-entry moments."""
    if source_quality == "stereo_fallback":
        return []
    if profile.bass_lag_ms < 1.0:
        return []
    # Bass emphasis at bar 1 (re-entry) and optionally after the midpoint
    emphasis_bars = [1]
    midpoint = bars // 2
    if midpoint > 2 and section_type in ("hook", "verse") and occurrence > 1:
        emphasis_bars.append(midpoint + 1)

    events = []
    for bar in emphasis_bars:
        intensity = min(1.0, 0.5 + energy * 0.35)
        if source_quality == "ai_separated":
            intensity *= 0.7
        events.append(GrooveEvent(
            bar_start=bar,
            bar_end=bar,
            role="bass",
            groove_type="bass_attack_emphasis",
            intensity=round(intensity, 3),
            parameters={"accent_target": "bass_attack"},
        ))

    return events


def build_turnaround_accents(
    bars: int,
    energy: float,
    section_type: str,
    source_quality: str,
) -> List[GrooveEvent]:
    """Build turnaround accent events near the section end.

    These signal the section boundary and prepare the listener for re-entry.
    """
    if source_quality == "stereo_fallback":
        return []
    # Only add turnaround in high-energy sections
    if energy < 0.5 and section_type not in ("hook", "pre_hook"):
        return []

    turnaround_bars = _turnaround_bars(bars)
    events = []
    for bar in turnaround_bars:
        intensity = min(1.0, 0.45 + energy * 0.40)
        if source_quality == "ai_separated":
            intensity *= 0.7
        events.append(GrooveEvent(
            bar_start=bar,
            bar_end=bar,
            role="drums",
            groove_type="turnaround_accent",
            intensity=round(intensity, 3),
            parameters={"accent_target": "turnaround"},
        ))

    return events


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_accent_events(
    profile: GrooveProfile,
    bars: int,
    energy: float,
    section_type: str,
    occurrence: int,
    source_quality: str,
    active_roles: List[str],
) -> List[GrooveEvent]:
    """Build all accent events for a section.

    Parameters
    ----------
    profile:
        Active groove profile.
    bars:
        Bar count of the section.
    energy:
        Section energy [0.0, 1.0].
    section_type:
        Canonical section type.
    occurrence:
        1-based occurrence index within section type.
    source_quality:
        Source quality mode string.
    active_roles:
        Instrument roles active in this section.

    Returns
    -------
    list[GrooveEvent]
        All accent events in order (hats → snare → kick → bass → turnaround).
    """
    events: List[GrooveEvent] = []

    has_drums = any(r in ("drums", "percussion") for r in active_roles)
    has_bass = "bass" in active_roles

    if has_drums:
        events.extend(build_hat_accents(profile, bars, energy, occurrence, source_quality))
        events.extend(build_snare_emphasis(profile, bars, energy, section_type, occurrence, source_quality))
        events.extend(build_kick_emphasis(profile, bars, energy, section_type, source_quality))
        events.extend(build_turnaround_accents(bars, energy, section_type, source_quality))

    if has_bass:
        events.extend(build_bass_attack_emphasis(profile, bars, energy, section_type, occurrence, source_quality))

    return events
