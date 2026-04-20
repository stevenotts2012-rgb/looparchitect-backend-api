"""
Melodic pattern variation logic for the Pattern Variation Engine.

Rules
-----
* intro         — delayed melody entry; melody holds back or enters late to
                  build anticipation.
* verse 1       — melody plays in full from bar 1.
* verse 2+      — call-and-response or phrase trimming; melody gets more
                  expressive with each repetition.
* pre_hook      — melody dropout or severe phrase trim to create anticipation.
* hook 1        — full melody entry; no delay.
* hook 2        — counter-melody added on top of the lead.
* hook 3+       — counter-melody + call-and-response for maximum interest.
* bridge/breakdown — melody dropout or minimal call fragment only.
* outro         — progressive melody dropout as the track closes.

Source quality affects melodic richness:
    true_stems    — full rule set; counter-melody, call-response available.
    zip_stems     — same as true_stems.
    ai_separated  — simpler; skip counter-melody (bleed risk); delayed entry
                    and dropout are safe.
    stereo_fallback — no melodic variation.
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


def build_melodic_plan(
    section_type: str,
    occurrence: int,
    bars: int,
    source_quality: str,
) -> List[PatternEvent]:
    """Return the melodic :class:`PatternEvent` list for one section.

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
        May be empty if no melodic variation is appropriate.
    """
    sq = source_quality.lower()

    if sq in _NO_VARIATION:
        logger.debug(
            "melodic_patterns: stereo_fallback — no melody variation for %s occ=%d",
            section_type, occurrence,
        )
        return []

    reduced = sq in _REDUCED_QUALITY

    builder_map = {
        "intro": _build_intro_melody,
        "verse": _build_verse_melody,
        "pre_hook": _build_pre_hook_melody,
        "hook": _build_hook_melody,
        "bridge": _build_bridge_melody,
        "breakdown": _build_breakdown_melody,
        "outro": _build_outro_melody,
    }

    builder = builder_map.get(section_type.lower())
    if builder is None:
        logger.debug(
            "melodic_patterns: unknown section type '%s' — no melody events.",
            section_type,
        )
        return []

    events = builder(occurrence=occurrence, bars=bars, reduced=reduced)
    logger.debug(
        "melodic_patterns: %s occ=%d → %d events (sq=%s)",
        section_type, occurrence, len(events), source_quality,
    )
    return events


# ---------------------------------------------------------------------------
# Per-section builders (private)
# ---------------------------------------------------------------------------

def _build_intro_melody(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Intro: delayed melody entry to build anticipation."""
    delay_bars = max(2, bars // 2)
    return [
        PatternEvent(
            bar_start=delay_bars,
            bar_end=bars,
            role="melody",
            pattern_action=PatternAction.DELAYED_MELODY_ENTRY,
            intensity=0.5,
            parameters={"delay_bars": delay_bars - 1},
            notes=f"intro — melody delayed until bar {delay_bars}",
        )
    ]


def _build_verse_melody(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Verse: full entry on 1; call-and-response/phrase trim on 2+."""
    if occurrence == 1:
        return []  # Verse 1: straight melody, no variation events needed

    events: List[PatternEvent] = []

    if not reduced:
        # Verse 2+: call-and-response from midpoint
        mid = max(1, bars // 2)
        events.append(PatternEvent(
            bar_start=mid,
            bar_end=bars,
            role="melody",
            pattern_action=PatternAction.CALL_RESPONSE,
            intensity=0.6,
            parameters={"phrase_bars": bars - mid + 1},
            notes=f"verse {occurrence} — call-and-response in second half",
        ))
    else:
        # Reduced quality: safe phrase trim (dropout at end)
        last_bar = max(1, bars - 1)
        events.append(PatternEvent(
            bar_start=last_bar,
            bar_end=bars,
            role="melody",
            pattern_action=PatternAction.MELODY_DROPOUT,
            intensity=0.4,
            notes=f"verse {occurrence} — phrase trim (ai_separated safe)",
        ))

    return events


def _build_pre_hook_melody(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Pre-hook: melody dropout to create hook anticipation."""
    # Melody drops out for most of the pre-hook
    drop_start = max(1, bars // 2)
    return [
        PatternEvent(
            bar_start=drop_start,
            bar_end=bars,
            role="melody",
            pattern_action=PatternAction.MELODY_DROPOUT,
            intensity=0.75,
            notes="pre-hook — melody drops out to build hook anticipation",
        )
    ]


def _build_hook_melody(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Hook: full melody on 1; counter-melody on 2+."""
    events: List[PatternEvent] = []

    if occurrence == 1:
        # Hook 1: straight full melody — no variation events needed
        return events

    if occurrence == 2:
        if not reduced:
            # Hook 2: add counter-melody
            mid = max(1, bars // 2)
            events.append(PatternEvent(
                bar_start=mid,
                bar_end=bars,
                role="melody",
                pattern_action=PatternAction.COUNTER_MELODY_ADD,
                intensity=0.7,
                notes="hook 2 — counter-melody added in second half",
            ))
        else:
            # Reduced: call-and-response safer than counter-melody
            mid = max(1, bars // 2)
            events.append(PatternEvent(
                bar_start=mid,
                bar_end=bars,
                role="melody",
                pattern_action=PatternAction.CALL_RESPONSE,
                intensity=0.6,
                notes="hook 2 — call-response (ai_separated, no counter-melody)",
            ))
    else:
        # Hook 3+: counter-melody from bar 1 + call-response
        if not reduced:
            events.append(PatternEvent(
                bar_start=1,
                bar_end=bars,
                role="melody",
                pattern_action=PatternAction.COUNTER_MELODY_ADD,
                intensity=0.8,
                notes=f"hook {occurrence} — counter-melody full section",
            ))
            mid = max(1, bars // 2)
            events.append(PatternEvent(
                bar_start=mid,
                bar_end=bars,
                role="melody",
                pattern_action=PatternAction.CALL_RESPONSE,
                intensity=0.75,
                notes=f"hook {occurrence} — call-response layered over counter",
            ))
        else:
            events.append(PatternEvent(
                bar_start=1,
                bar_end=bars,
                role="melody",
                pattern_action=PatternAction.CALL_RESPONSE,
                intensity=0.65,
                notes=f"hook {occurrence} — call-response only (ai_separated)",
            ))

    return events


def _build_bridge_melody(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Bridge: melody dropout or minimal fragment only."""
    mid = max(1, bars // 2)
    return [
        PatternEvent(
            bar_start=1,
            bar_end=mid,
            role="melody",
            pattern_action=PatternAction.MELODY_DROPOUT,
            intensity=0.65,
            notes="bridge — melody drops first half, fragment only",
        )
    ]


def _build_breakdown_melody(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Breakdown: full melody dropout for maximum contrast."""
    return [
        PatternEvent(
            bar_start=1,
            bar_end=bars,
            role="melody",
            pattern_action=PatternAction.MELODY_DROPOUT,
            intensity=0.8,
            notes="breakdown — melody fully dropped",
        )
    ]


def _build_outro_melody(*, occurrence: int, bars: int, reduced: bool) -> List[PatternEvent]:
    """Outro: progressive melody dropout."""
    mid = max(1, bars // 2)
    return [
        PatternEvent(
            bar_start=mid,
            bar_end=bars,
            role="melody",
            pattern_action=PatternAction.MELODY_DROPOUT,
            intensity=0.6,
            notes="outro — melody fades second half",
        )
    ]
