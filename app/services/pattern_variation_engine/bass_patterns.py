"""
Bass pattern variation logic for the Pattern Variation Engine.

Rules
-----
* intro         — bass hold (sustained root note only); no active movement.
* verse 1       — standard groove bass; no events needed.
* verse 2+      — syncopated bass push in second half for added energy.
* pre_hook      — bass dropout to create tension and space before the hook.
* hook 1        — full bass groove; 808-style re-entry on bar 1.
* hook 2        — octave lift on second half for added perceived energy.
* hook 3+       — syncopated push + octave lift for maximum payoff.
* bridge/breakdown — bass dropout; minimal activity.
* outro         — progressive bass dropout from mid-section.

Source quality affects bass richness:
    true_stems    — full rule set.
    zip_stems     — same as true_stems.
    ai_separated  — skip octave lift and syncopated push (low-end artefacts
                    cause mud); 808 re-entry and bass dropout are safe.
    stereo_fallback — no bass variation.
"""

from __future__ import annotations

import logging
from typing import List

from app.services.pattern_variation_engine.types import (
    PatternAction,
    PatternEvent,
)

logger = logging.getLogger(__name__)

_FULL_QUALITY = {"true_stems", "zip_stems"}
_REDUCED_QUALITY = {"ai_separated"}
_NO_VARIATION = {"stereo_fallback"}


def build_bass_plan(
    section_type: str,
    occurrence: int,
    bars: int,
    source_quality: str,
) -> List[PatternEvent]:
    """Return the bass :class:`PatternEvent` list for one section.

    Parameters
    ----------
    section_type:
        Canonical section type string.
    occurrence:
        1-based occurrence counter for this section type.
    bars:
        Total bar count of the section.
    source_quality:
        Source quality mode string.

    Returns
    -------
    list[PatternEvent]
        May be empty if no bass variation is appropriate.
    """
    sq = source_quality.lower()

    if sq in _NO_VARIATION:
        logger.debug(
            "bass_patterns: stereo_fallback — no bass variation for %s occ=%d",
            section_type, occurrence,
        )
        return []

    reduced = sq in _REDUCED_QUALITY

    builder_map = {
        "intro": _build_intro_bass,
        "verse": _build_verse_bass,
        "pre_hook": _build_pre_hook_bass,
        "hook": _build_hook_bass,
        "bridge": _build_bridge_bass,
        "breakdown": _build_breakdown_bass,
        "outro": _build_outro_bass,
    }

    builder = builder_map.get(section_type.lower())
    if builder is None:
        logger.debug(
            "bass_patterns: unknown section type '%s' — no bass events.", section_type
        )
        return []

    events = builder(occurrence=occurrence, bars=bars, reduced=reduced)
    logger.debug(
        "bass_patterns: %s occ=%d → %d events (sq=%s)",
        section_type, occurrence, len(events), source_quality,
    )
    return events


# ---------------------------------------------------------------------------
# Per-section builders (private)
# ---------------------------------------------------------------------------

def _build_intro_bass(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Intro: bass hold only — no active movement."""
    # Dropout / hold: bass plays root note only, no rhythmic activity
    return [
        PatternEvent(
            bar_start=1,
            bar_end=bars,
            role="bass",
            pattern_action=PatternAction.BASS_DROPOUT,
            intensity=0.35,
            parameters={"hold_root": True},
            notes="intro — bass hold (root-only, no movement)",
        )
    ]


def _build_verse_bass(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Verse: standard bass on 1; syncopated push on 2+."""
    if occurrence == 1:
        return []  # Verse 1: no events; standard groove

    events: List[PatternEvent] = []

    if not reduced:
        # Verse 2+: syncopated push in second half
        half = max(1, bars // 2)
        events.append(PatternEvent(
            bar_start=half,
            bar_end=bars,
            role="bass",
            pattern_action=PatternAction.SYNCOPATED_BASS_PUSH,
            intensity=0.6,
            notes=f"verse {occurrence} — syncopated bass push (second half)",
        ))
    else:
        # Reduced: simple 808 re-entry accent — safe with AI stems
        mid = max(1, bars // 2)
        events.append(PatternEvent(
            bar_start=mid,
            bar_end=mid,
            role="bass",
            pattern_action=PatternAction.REENTRY_808,
            intensity=0.5,
            notes=f"verse {occurrence} — 808 re-entry accent (ai_separated safe)",
        ))

    return events


def _build_pre_hook_bass(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Pre-hook: bass dropout to create space before the hook drop."""
    return [
        PatternEvent(
            bar_start=max(1, bars // 2),
            bar_end=bars,
            role="bass",
            pattern_action=PatternAction.BASS_DROPOUT,
            intensity=0.8,
            notes="pre-hook — bass drops out to create tension before hook",
        )
    ]


def _build_hook_bass(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Hook: 808 re-entry on 1; octave lift on 2+; syncopated push on 3+."""
    events: List[PatternEvent] = []

    if occurrence == 1:
        # Hook 1: 808-style re-entry punch on bar 1
        events.append(PatternEvent(
            bar_start=1,
            bar_end=1,
            role="bass",
            pattern_action=PatternAction.REENTRY_808,
            intensity=0.85,
            notes="hook 1 — 808 re-entry punch on drop",
        ))

    elif occurrence == 2:
        # Hook 2: re-entry + octave lift in second half
        events.append(PatternEvent(
            bar_start=1,
            bar_end=1,
            role="bass",
            pattern_action=PatternAction.REENTRY_808,
            intensity=0.85,
            notes="hook 2 — 808 re-entry",
        ))
        if not reduced:
            half = max(1, bars // 2)
            events.append(PatternEvent(
                bar_start=half,
                bar_end=bars,
                role="bass",
                pattern_action=PatternAction.OCTAVE_LIFT,
                intensity=0.75,
                notes="hook 2 — octave lift second half",
            ))

    else:
        # Hook 3+: all three — re-entry, octave lift, syncopated push
        events.append(PatternEvent(
            bar_start=1,
            bar_end=1,
            role="bass",
            pattern_action=PatternAction.REENTRY_808,
            intensity=0.9,
            notes=f"hook {occurrence} — 808 re-entry maximum",
        ))
        if not reduced:
            events.append(PatternEvent(
                bar_start=1,
                bar_end=bars,
                role="bass",
                pattern_action=PatternAction.OCTAVE_LIFT,
                intensity=0.8,
                notes=f"hook {occurrence} — octave lift full section",
            ))
            half = max(1, bars // 2)
            events.append(PatternEvent(
                bar_start=half,
                bar_end=bars,
                role="bass",
                pattern_action=PatternAction.SYNCOPATED_BASS_PUSH,
                intensity=0.85,
                notes=f"hook {occurrence} — syncopated bass push maximum payoff",
            ))

    return events


def _build_bridge_bass(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Bridge: bass dropout — contrast after hook intensity."""
    return [
        PatternEvent(
            bar_start=1,
            bar_end=bars,
            role="bass",
            pattern_action=PatternAction.BASS_DROPOUT,
            intensity=0.6,
            notes="bridge — bass dropout for contrast",
        )
    ]


def _build_breakdown_bass(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Breakdown: full bass dropout."""
    return [
        PatternEvent(
            bar_start=1,
            bar_end=bars,
            role="bass",
            pattern_action=PatternAction.BASS_DROPOUT,
            intensity=0.75,
            notes="breakdown — bass fully dropped",
        )
    ]


def _build_outro_bass(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Outro: progressive bass dropout from mid-section."""
    mid = max(1, bars // 2)
    return [
        PatternEvent(
            bar_start=mid,
            bar_end=bars,
            role="bass",
            pattern_action=PatternAction.BASS_DROPOUT,
            intensity=0.55,
            notes="outro — bass fades from mid-section",
        )
    ]
