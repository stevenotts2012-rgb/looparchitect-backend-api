"""
Drum pattern variation logic for the Pattern Variation Engine.

Rules
-----
* intro         — sparse groove; no busy kick; no fills.
* verse 1       — stable 4-on-the-floor or standard groove; no upgrades yet.
* verse 2+      — add one rhythmic upgrade (syncopated kick or hat density).
* pre_hook      — subtract energy / add tension (hat density down, pre-drop
                  silence, or a snare fill leading into the hook).
* hook 1        — full groove; hats up; standard kick.
* hook 2        — bigger than hook 1: add syncopated kick or snare fill.
* hook 3+       — maximum payoff: syncopated kick + snare fill + perc fill.
* bridge/breakdown — reduced groove; halftime possible; no busy patterns.
* outro         — progressive strip: kick drop → hat density down.

Source quality degrades the richness of variations:
    true_stems    — full rule set.
    zip_stems     — same as true_stems.
    ai_separated  — simpler patterns; skip fills that require fine-grained
                    drum isolation (perc_fill, add_syncopated_kick).
    stereo_fallback — no drum variation at all.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.services.pattern_variation_engine.types import (
    PatternAction,
    PatternEvent,
    PatternSectionPlan,
)

logger = logging.getLogger(__name__)

# Source quality tiers for drum variation
_FULL_QUALITY = {"true_stems", "zip_stems"}
_REDUCED_QUALITY = {"ai_separated"}
_NO_DRUM_VARIATION = {"stereo_fallback"}


def build_drum_plan(
    section_type: str,
    occurrence: int,
    bars: int,
    source_quality: str,
) -> List[PatternEvent]:
    """Return the drum :class:`PatternEvent` list for one section.

    Parameters
    ----------
    section_type:
        Canonical section type string (e.g. ``"verse"``, ``"hook"``).
    occurrence:
        1-based occurrence counter for this section type.
    bars:
        Total bar count of the section.
    source_quality:
        Source quality mode string.

    Returns
    -------
    list[PatternEvent]
        May be empty if no drum variation is appropriate.
    """
    sq = source_quality.lower()

    if sq in _NO_DRUM_VARIATION:
        logger.debug(
            "drum_patterns: stereo_fallback — skipping drum variation for %s occ=%d",
            section_type, occurrence,
        )
        return []

    reduced = sq in _REDUCED_QUALITY

    builder_map = {
        "intro": _build_intro_drums,
        "verse": _build_verse_drums,
        "pre_hook": _build_pre_hook_drums,
        "hook": _build_hook_drums,
        "bridge": _build_bridge_drums,
        "breakdown": _build_breakdown_drums,
        "outro": _build_outro_drums,
    }

    builder = builder_map.get(section_type.lower())
    if builder is None:
        logger.debug(
            "drum_patterns: unknown section type '%s' — no drum events.", section_type
        )
        return []

    events = builder(occurrence=occurrence, bars=bars, reduced=reduced)
    logger.debug(
        "drum_patterns: %s occ=%d → %d events (sq=%s)",
        section_type, occurrence, len(events), source_quality,
    )
    return events


# ---------------------------------------------------------------------------
# Per-section builders (private)
# ---------------------------------------------------------------------------

def _build_intro_drums(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Intro: sparse groove only; kick is dropped or sparse."""
    events: List[PatternEvent] = []
    # Kick is dropped on bar 1 to ease the listener in
    events.append(PatternEvent(
        bar_start=1,
        bar_end=min(2, bars),
        role="drums",
        pattern_action=PatternAction.DROP_KICK,
        intensity=0.4,
        notes="intro sparse entry — kick dropped on first 2 bars",
    ))
    # Hats stay low density throughout intro
    events.append(PatternEvent(
        bar_start=1,
        bar_end=bars,
        role="drums",
        pattern_action=PatternAction.HAT_DENSITY_DOWN,
        intensity=0.3,
        notes="intro hats sparse",
    ))
    return events


def _build_verse_drums(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Verse: stable groove on occurrence 1; upgrade on 2+."""
    events: List[PatternEvent] = []

    if occurrence == 1:
        # Verse 1: straight groove — hat density stays neutral; no fills.
        return events  # No events = stable/default groove

    # Verse 2+: add one rhythmic upgrade
    if not reduced:
        # Full quality: syncopated kick in the second half
        half = max(1, bars // 2)
        events.append(PatternEvent(
            bar_start=half,
            bar_end=bars,
            role="drums",
            pattern_action=PatternAction.ADD_SYNCOPATED_KICK,
            intensity=0.6,
            notes=f"verse {occurrence} — syncopated kick upgrade in second half",
        ))
    else:
        # Reduced quality: safe hat density up instead
        events.append(PatternEvent(
            bar_start=1,
            bar_end=bars,
            role="drums",
            pattern_action=PatternAction.HAT_DENSITY_UP,
            intensity=0.5,
            notes=f"verse {occurrence} — hat density up (ai_separated safe upgrade)",
        ))

    return events


def _build_pre_hook_drums(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Pre-hook: subtract energy / build tension into the hook drop."""
    events: List[PatternEvent] = []

    # Hat density down to pull energy back before the hook
    events.append(PatternEvent(
        bar_start=1,
        bar_end=max(1, bars - 2),
        role="drums",
        pattern_action=PatternAction.HAT_DENSITY_DOWN,
        intensity=0.6,
        notes="pre-hook hat pullback — tension build",
    ))

    if not reduced:
        # Pre-drop silence or snare fill on the last bar(s)
        last_bar = max(1, bars - 1)
        events.append(PatternEvent(
            bar_start=last_bar,
            bar_end=bars,
            role="drums",
            pattern_action=PatternAction.PRE_DROP_SILENCE,
            intensity=0.8,
            notes="pre-hook silence drop before hook entry",
        ))
    else:
        # Reduced: use a snare fill instead of silence (safer with AI stems)
        last_bar = max(1, bars - 1)
        events.append(PatternEvent(
            bar_start=last_bar,
            bar_end=bars,
            role="drums",
            pattern_action=PatternAction.SNARE_FILL,
            intensity=0.7,
            notes="pre-hook snare fill (ai_separated — no silence)",
        ))

    return events


def _build_hook_drums(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Hook: full groove on 1, escalate on 2, maximum payoff on 3+."""
    events: List[PatternEvent] = []

    if occurrence == 1:
        # Hook 1: full groove, hats up
        events.append(PatternEvent(
            bar_start=1,
            bar_end=bars,
            role="drums",
            pattern_action=PatternAction.HAT_DENSITY_UP,
            intensity=0.8,
            notes="hook 1 — full groove, hats open",
        ))

    elif occurrence == 2:
        # Hook 2: bigger than hook 1
        events.append(PatternEvent(
            bar_start=1,
            bar_end=bars,
            role="drums",
            pattern_action=PatternAction.HAT_DENSITY_UP,
            intensity=0.85,
            notes="hook 2 — hats higher than hook 1",
        ))
        if not reduced:
            half = max(1, bars // 2)
            events.append(PatternEvent(
                bar_start=half,
                bar_end=bars,
                role="drums",
                pattern_action=PatternAction.ADD_SYNCOPATED_KICK,
                intensity=0.75,
                notes="hook 2 — syncopated kick escalation",
            ))

    else:
        # Hook 3+: maximum payoff
        events.append(PatternEvent(
            bar_start=1,
            bar_end=bars,
            role="drums",
            pattern_action=PatternAction.HAT_DENSITY_UP,
            intensity=0.9,
            notes=f"hook {occurrence} — maximum payoff, hats full open",
        ))
        if not reduced:
            events.append(PatternEvent(
                bar_start=1,
                bar_end=bars,
                role="drums",
                pattern_action=PatternAction.ADD_SYNCOPATED_KICK,
                intensity=0.85,
                notes=f"hook {occurrence} — syncopated kick maximum",
            ))
            # Snare fill on last two bars
            fill_start = max(1, bars - 1)
            events.append(PatternEvent(
                bar_start=fill_start,
                bar_end=bars,
                role="drums",
                pattern_action=PatternAction.SNARE_FILL,
                intensity=0.9,
                notes=f"hook {occurrence} — snare fill maximum payoff",
            ))
            # Perc fill from midpoint
            mid = max(1, bars // 2)
            events.append(PatternEvent(
                bar_start=mid,
                bar_end=bars,
                role="percussion",
                pattern_action=PatternAction.PERC_FILL,
                intensity=0.8,
                notes=f"hook {occurrence} — perc fill layered in",
            ))

    return events


def _build_bridge_drums(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Bridge: significantly reduced groove; halftime possible."""
    events: List[PatternEvent] = []

    # Drop kick for most of the bridge
    events.append(PatternEvent(
        bar_start=1,
        bar_end=max(1, bars - 1),
        role="drums",
        pattern_action=PatternAction.DROP_KICK,
        intensity=0.5,
        notes="bridge — kick stripped for contrast",
    ))

    # Halftime if the section is long enough
    if bars >= 8 and not reduced:
        events.append(PatternEvent(
            bar_start=1,
            bar_end=bars,
            role="drums",
            pattern_action=PatternAction.HALF_TIME_SWITCH,
            intensity=0.6,
            notes="bridge — halftime feel applied",
        ))

    # Hats sparse throughout
    events.append(PatternEvent(
        bar_start=1,
        bar_end=bars,
        role="drums",
        pattern_action=PatternAction.HAT_DENSITY_DOWN,
        intensity=0.5,
        notes="bridge — hat density reduced",
    ))

    return events


def _build_breakdown_drums(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Breakdown: minimal drums; halftime or full strip."""
    events: List[PatternEvent] = []

    # Full kick drop in breakdown
    events.append(PatternEvent(
        bar_start=1,
        bar_end=bars,
        role="drums",
        pattern_action=PatternAction.DROP_KICK,
        intensity=0.7,
        notes="breakdown — kick fully dropped",
    ))

    # Hats very sparse
    events.append(PatternEvent(
        bar_start=1,
        bar_end=bars,
        role="drums",
        pattern_action=PatternAction.HAT_DENSITY_DOWN,
        intensity=0.8,
        notes="breakdown — hats stripped",
    ))

    if bars >= 8 and not reduced:
        events.append(PatternEvent(
            bar_start=1,
            bar_end=bars,
            role="drums",
            pattern_action=PatternAction.HALF_TIME_SWITCH,
            intensity=0.7,
            notes="breakdown — halftime applied if long enough",
        ))

    return events


def _build_outro_drums(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Outro: progressive strip — kick drops first, then hats thin out."""
    events: List[PatternEvent] = []
    mid = max(1, bars // 2)

    # Kick drops in second half of outro
    events.append(PatternEvent(
        bar_start=mid,
        bar_end=bars,
        role="drums",
        pattern_action=PatternAction.DROP_KICK,
        intensity=0.6,
        notes="outro — kick fades mid-section",
    ))

    # Hats thin out through the whole outro
    events.append(PatternEvent(
        bar_start=1,
        bar_end=bars,
        role="drums",
        pattern_action=PatternAction.HAT_DENSITY_DOWN,
        intensity=0.5,
        notes="outro — hat density progressively reduced",
    ))

    return events
