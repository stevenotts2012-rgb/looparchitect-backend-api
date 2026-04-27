"""
Event generator for the Generative Producer System.

Converts a section template + genre profile into a list of ProducerEvents
using deterministic procedural generation (random.Random(seed) only).

Rules:
- Every section gets at least one meaningful event when material exists.
- Long sections (> 8 bars) get intra-section variation events.
- Repeated sections must differ from their prior occurrence.
- Hook must have the strongest payoff.
- Outro must simplify.
- Bridge/breakdown must reset.
"""

from __future__ import annotations

import random
from typing import Any

from app.services.generative_producer_system.types import ProducerEvent
from app.services.generative_producer_system.genre_profiles import GenreProducerProfile
from app.services.generative_producer_system.producer_rules import (
    is_hook_section,
    is_intro_section,
    is_outro_section,
    is_bridge_reset_section,
    is_pre_hook_section,
    should_add_intra_section_variation,
    min_events_for_section,
    must_differ_from_prior,
)
from app.services.generative_producer_system.renderer_mapping import resolve_render_action

# ---------------------------------------------------------------------------
# Role pools used for target selection
# ---------------------------------------------------------------------------

_DRUM_ROLES = ("drums", "percussion")
_BASS_ROLES = ("bass",)
_MELODY_ROLES = ("melody", "harmony", "pads")
_FX_ROLES = ("fx", "accent")
_ALL_ROLES = _DRUM_ROLES + _BASS_ROLES + _MELODY_ROLES + _FX_ROLES


def _pick_role(rng: random.Random, roles: tuple[str, ...], available: list[str]) -> str:
    """Pick a role from *roles* that is in *available*, or fall back to first *roles* item."""
    candidates = [r for r in roles if r in available]
    if candidates:
        return rng.choice(candidates)
    return rng.choice(list(roles))


# ---------------------------------------------------------------------------
# Event-type pools per behavior trigger
# ---------------------------------------------------------------------------

_DRUM_FILL_TYPES = ("drum_pattern_change", "drum_fill", "hat_roll")
_BASS_VAR_TYPES = ("bass_pattern_variation", "sliding_bass")
_MELODY_CHOP_TYPES = ("melody_chop", "melody_filter")
_PAD_TYPES = ("pad_expose", "counter_melody")
_FX_TYPES = ("fx_riser", "fx_impact")
_MUTE_TYPES = ("drum_dropout", "bass_dropout", "section_dropout")
_HOOK_PAYOFF_TYPES = ("hook_payoff", "hook_widen", "add_hat_roll")
_OUTRO_TYPES = ("automation_fade", "automation_reverb", "section_dropout")
_WIDEN_TYPES = ("automation_widen",)
_DELAY_TYPES = ("automation_delay",)
_REVERB_TYPES = ("automation_reverb",)


def _render_action_for(event_type: str) -> str:
    """Resolve render_action or fall back to a safe default."""
    resolved = resolve_render_action(event_type)
    return resolved or "add_drum_fill"


# ---------------------------------------------------------------------------
# Section-level event builders
# ---------------------------------------------------------------------------


def _make_event(
    *,
    rng: random.Random,
    section_name: str,
    occurrence_index: int,
    bar_start: int,
    bar_end: int,
    event_type: str,
    target_role: str,
    intensity: float,
    parameters: dict[str, Any] | None = None,
    reason: str,
) -> ProducerEvent:
    return ProducerEvent.make(
        section_name=section_name,
        occurrence_index=occurrence_index,
        bar_start=bar_start,
        bar_end=bar_end,
        target_role=target_role,
        event_type=event_type,
        intensity=intensity,
        parameters=parameters or {},
        render_action=_render_action_for(event_type),
        reason=reason,
    )


def _generate_intro_events(
    rng: random.Random,
    section: dict[str, Any],
    profile: GenreProducerProfile,
    occurrence_index: int,
    available_roles: list[str],
) -> list[ProducerEvent]:
    name = section["name"]
    bar_start = section["bar_start"]
    bar_end = section["bar_end"]
    behavior = profile.behavior_for(name)
    events: list[ProducerEvent] = []

    # Always filter melody in intro
    events.append(
        _make_event(
            rng=rng,
            section_name=name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_end,
            event_type="melody_filter",
            target_role=_pick_role(rng, _MELODY_ROLES, available_roles),
            intensity=0.4,
            reason="Intro: filtered melody, sparse entry",
        )
    )

    # Mute drums if behavior says sparse
    if behavior.get("drum_density") in ("sparse", "none"):
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=bar_start,
                bar_end=bar_end,
                event_type="drum_dropout",
                target_role=_pick_role(rng, _DRUM_ROLES, available_roles),
                intensity=0.3,
                reason="Intro: sparse drums",
            )
        )

    return events


def _generate_verse_events(
    rng: random.Random,
    section: dict[str, Any],
    profile: GenreProducerProfile,
    occurrence_index: int,
    available_roles: list[str],
    prior_event_types: set[str],
) -> list[ProducerEvent]:
    name = section["name"]
    bar_start = section["bar_start"]
    bar_end = section["bar_end"]
    behavior = profile.behavior_for(name)
    events: list[ProducerEvent] = []

    # Base drum event
    drum_type = rng.choice(_DRUM_FILL_TYPES)
    events.append(
        _make_event(
            rng=rng,
            section_name=name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_end,
            event_type=drum_type,
            target_role=_pick_role(rng, _DRUM_ROLES, available_roles),
            intensity=0.5,
            reason=f"Verse: {drum_type}",
        )
    )

    # Bass event if active
    if behavior.get("bass_active", True):
        bass_type = rng.choice(_BASS_VAR_TYPES)
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=bar_start,
                bar_end=bar_end,
                event_type=bass_type,
                target_role=_pick_role(rng, _BASS_ROLES, available_roles),
                intensity=0.5,
                reason=f"Verse: {bass_type}",
            )
        )

    # On repeated verse: must differ — add extra variation
    if must_differ_from_prior(name, occurrence_index):
        # Pick an event type NOT used in prior occurrence
        candidates = [t for t in _DRUM_FILL_TYPES + _BASS_VAR_TYPES if t not in prior_event_types]
        if not candidates:
            candidates = list(_DRUM_FILL_TYPES + _MELODY_CHOP_TYPES)
        extra_type = rng.choice(candidates)
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=bar_start,
                bar_end=bar_end,
                event_type=extra_type,
                target_role=_pick_role(rng, _DRUM_ROLES + _MELODY_ROLES, available_roles),
                intensity=0.6,
                reason=f"Verse {occurrence_index + 1}: variation from prior occurrence",
            )
        )
        if behavior.get("bass_variation"):
            events.append(
                _make_event(
                    rng=rng,
                    section_name=name,
                    occurrence_index=occurrence_index,
                    bar_start=bar_start,
                    bar_end=bar_end,
                    event_type="sliding_bass",
                    target_role=_pick_role(rng, _BASS_ROLES, available_roles),
                    intensity=0.6,
                    reason="Verse 2: additional bass variation",
                )
            )

    # Intra-section variation for long verses
    for intra_bar in should_add_intra_section_variation(bar_start, bar_end):
        intra_type = rng.choice(_DRUM_FILL_TYPES + _MELODY_CHOP_TYPES)
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=intra_bar,
                bar_end=min(intra_bar + 4, bar_end),
                event_type=intra_type,
                target_role=_pick_role(rng, _DRUM_ROLES + _MELODY_ROLES, available_roles),
                intensity=0.45,
                reason=f"Intra-section variation at bar {intra_bar}",
            )
        )

    return events


def _generate_pre_hook_events(
    rng: random.Random,
    section: dict[str, Any],
    profile: GenreProducerProfile,
    occurrence_index: int,
    available_roles: list[str],
) -> list[ProducerEvent]:
    name = section["name"]
    bar_start = section["bar_start"]
    bar_end = section["bar_end"]
    behavior = profile.behavior_for(name)
    events: list[ProducerEvent] = []

    # Drop/anchor role
    dropout_roles = behavior.get("dropout_roles") or ["drums"]
    for role in dropout_roles[:1]:
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=bar_start,
                bar_end=bar_end,
                event_type="section_dropout",
                target_role=role if role in available_roles else _pick_role(rng, _DRUM_ROLES, available_roles),
                intensity=0.7,
                reason="Pre-hook: drop anchor role for tension",
            )
        )

    # FX riser if profile says so
    if behavior.get("fx_riser"):
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=max(bar_start, bar_end - 2),
                bar_end=bar_end,
                event_type="fx_riser",
                target_role=_pick_role(rng, _FX_ROLES, available_roles),
                intensity=0.8,
                reason="Pre-hook: FX riser into hook",
            )
        )

    return events


def _generate_hook_events(
    rng: random.Random,
    section: dict[str, Any],
    profile: GenreProducerProfile,
    occurrence_index: int,
    available_roles: list[str],
    prior_event_types: set[str],
) -> list[ProducerEvent]:
    name = section["name"]
    bar_start = section["bar_start"]
    bar_end = section["bar_end"]
    behavior = profile.behavior_for(name)
    events: list[ProducerEvent] = []

    # Impact at start
    events.append(
        _make_event(
            rng=rng,
            section_name=name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_start + 2,
            event_type="fx_impact",
            target_role=_pick_role(rng, _FX_ROLES, available_roles),
            intensity=0.9,
            reason="Hook: impact at entry",
        )
    )

    # Full drums unmute
    events.append(
        _make_event(
            rng=rng,
            section_name=name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_end,
            event_type="drum_reentry",
            target_role=_pick_role(rng, _DRUM_ROLES, available_roles),
            intensity=0.9,
            reason="Hook: full drums re-entry",
        )
    )

    # Hat roll
    if behavior.get("hat_roll"):
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=bar_start + (bar_end - bar_start) // 2,
                bar_end=bar_end,
                event_type="hat_roll",
                target_role=_pick_role(rng, _DRUM_ROLES, available_roles),
                intensity=0.85,
                reason="Hook: hi-hat roll in second half",
            )
        )

    # Bass active
    if behavior.get("bass_active"):
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=bar_start,
                bar_end=bar_end,
                event_type="bass_pattern_variation",
                target_role=_pick_role(rng, _BASS_ROLES, available_roles),
                intensity=0.85,
                reason="Hook: active bass/808",
            )
        )

    # Widen if profile says so
    if behavior.get("widen"):
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=bar_start,
                bar_end=bar_end,
                event_type="automation_widen",
                target_role=_pick_role(rng, _MELODY_ROLES, available_roles),
                intensity=0.8,
                reason="Hook: stereo widen for payoff",
            )
        )

    # Hook 2 payoff: chop melody for extra energy
    if behavior.get("chop_melody") or occurrence_index > 0:
        candidates = [t for t in _MELODY_CHOP_TYPES if t not in prior_event_types]
        if not candidates:
            candidates = list(_MELODY_CHOP_TYPES)
        chop_type = rng.choice(candidates)
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=bar_start,
                bar_end=bar_end,
                event_type=chop_type,
                target_role=_pick_role(rng, _MELODY_ROLES, available_roles),
                intensity=0.9 + 0.05 * occurrence_index,
                reason=f"Hook {occurrence_index + 1}: melody chop for bigger payoff",
            )
        )

    # Intra-section variation for long hooks
    for intra_bar in should_add_intra_section_variation(bar_start, bar_end):
        events.append(
            _make_event(
                rng=rng,
                section_name=name,
                occurrence_index=occurrence_index,
                bar_start=intra_bar,
                bar_end=min(intra_bar + 4, bar_end),
                event_type=rng.choice(_DRUM_FILL_TYPES),
                target_role=_pick_role(rng, _DRUM_ROLES, available_roles),
                intensity=0.7,
                reason=f"Hook: intra-section fill at bar {intra_bar}",
            )
        )

    return events


def _generate_bridge_events(
    rng: random.Random,
    section: dict[str, Any],
    profile: GenreProducerProfile,
    occurrence_index: int,
    available_roles: list[str],
) -> list[ProducerEvent]:
    name = section["name"]
    bar_start = section["bar_start"]
    bar_end = section["bar_end"]
    behavior = profile.behavior_for(name)
    events: list[ProducerEvent] = []

    # Reset: mute drums
    events.append(
        _make_event(
            rng=rng,
            section_name=name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_end,
            event_type="drum_dropout",
            target_role=_pick_role(rng, _DRUM_ROLES, available_roles),
            intensity=0.4,
            reason="Bridge: drum reset",
        )
    )

    # Reverb tail or delay on melody
    reverb_type = "automation_reverb" if behavior.get("reverb_tail") else "automation_delay"
    events.append(
        _make_event(
            rng=rng,
            section_name=name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_end,
            event_type=reverb_type,
            target_role=_pick_role(rng, _MELODY_ROLES, available_roles),
            intensity=0.5,
            reason="Bridge: space/reverb reset",
        )
    )

    return events


def _generate_outro_events(
    rng: random.Random,
    section: dict[str, Any],
    profile: GenreProducerProfile,
    occurrence_index: int,
    available_roles: list[str],
) -> list[ProducerEvent]:
    name = section["name"]
    bar_start = section["bar_start"]
    bar_end = section["bar_end"]
    events: list[ProducerEvent] = []

    # Fade drums
    events.append(
        _make_event(
            rng=rng,
            section_name=name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_end,
            event_type="drum_dropout",
            target_role=_pick_role(rng, _DRUM_ROLES, available_roles),
            intensity=0.2,
            reason="Outro: remove drums",
        )
    )

    # Fade bass
    events.append(
        _make_event(
            rng=rng,
            section_name=name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_end,
            event_type="bass_dropout",
            target_role=_pick_role(rng, _BASS_ROLES, available_roles),
            intensity=0.2,
            reason="Outro: remove bass/808",
        )
    )

    # Reverb tail on melody
    events.append(
        _make_event(
            rng=rng,
            section_name=name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_end,
            event_type="automation_reverb",
            target_role=_pick_role(rng, _MELODY_ROLES, available_roles),
            intensity=0.3,
            reason="Outro: melody tail / reverb",
        )
    )

    return events


def _generate_generic_section_events(
    rng: random.Random,
    section: dict[str, Any],
    profile: GenreProducerProfile,
    occurrence_index: int,
    available_roles: list[str],
    prior_event_types: set[str],
) -> list[ProducerEvent]:
    """Fallback generator for any unrecognised section type."""
    name = section["name"]
    bar_start = section["bar_start"]
    bar_end = section["bar_end"]
    behavior = profile.behavior_for(name)
    events: list[ProducerEvent] = []

    event_pool = _DRUM_FILL_TYPES + _BASS_VAR_TYPES + _MELODY_CHOP_TYPES
    candidates = [t for t in event_pool if t not in prior_event_types] or list(event_pool)
    chosen = rng.choice(candidates)
    events.append(
        _make_event(
            rng=rng,
            section_name=name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_end,
            event_type=chosen,
            target_role=_pick_role(rng, _ALL_ROLES, available_roles),
            intensity=behavior.get("energy", 0.5),
            reason=f"{name}: generic section event",
        )
    )
    return events


# ---------------------------------------------------------------------------
# Section dispatcher
# ---------------------------------------------------------------------------


def _normalise_section_name(raw: str) -> str:
    """Lower-case and strip name; map common aliases."""
    name = raw.strip().lower()
    _ALIASES = {
        "chorus": "hook",
        "chorus_2": "hook_2",
        "prehook": "pre_hook",
        "pre-hook": "pre_hook",
    }
    return _ALIASES.get(name, name)


def generate_section_events(
    rng: random.Random,
    section: dict[str, Any],
    profile: GenreProducerProfile,
    occurrence_index: int,
    available_roles: list[str],
    prior_event_types: set[str],
) -> list[ProducerEvent]:
    """Generate producer events for a single section."""
    name = _normalise_section_name(section.get("name", "verse"))
    normalised_section = dict(section, name=name)

    if is_intro_section(name):
        return _generate_intro_events(rng, normalised_section, profile, occurrence_index, available_roles)
    if is_outro_section(name):
        return _generate_outro_events(rng, normalised_section, profile, occurrence_index, available_roles)
    if is_bridge_reset_section(name):
        return _generate_bridge_events(rng, normalised_section, profile, occurrence_index, available_roles)
    if is_pre_hook_section(name):
        return _generate_pre_hook_events(rng, normalised_section, profile, occurrence_index, available_roles)
    if is_hook_section(name):
        return _generate_hook_events(rng, normalised_section, profile, occurrence_index, available_roles, prior_event_types)
    # verse, verse_2, and everything else
    return _generate_verse_events(rng, normalised_section, profile, occurrence_index, available_roles, prior_event_types)


# ---------------------------------------------------------------------------
# Full arrangement event generation
# ---------------------------------------------------------------------------


def generate_events(
    *,
    sections: list[dict[str, Any]],
    profile: GenreProducerProfile,
    available_roles: list[str],
    seed: int,
) -> list[ProducerEvent]:
    """Generate all producer events for an arrangement.

    Parameters
    ----------
    sections:
        List of section dicts, each with at least ``name``, ``bar_start``,
        ``bar_end`` (or ``bars`` from which bar_end is derived), and
        optional ``occurrence_index``.
    profile:
        The GenreProducerProfile for the target genre.
    available_roles:
        Stem roles available in the source material.
    seed:
        Deterministic random seed.

    Returns
    -------
    list[ProducerEvent]
        All generated events in section order.
    """
    rng = random.Random(seed)

    # Track occurrence counts per section base-name
    occurrence_counters: dict[str, int] = {}
    # Track event types used per section to enforce variation on repeats
    prior_types_by_section: dict[str, set[str]] = {}

    all_events: list[ProducerEvent] = []

    # Build bar positions if missing
    current_bar = 0
    normalised_sections: list[dict[str, Any]] = []
    for s in sections:
        name = _normalise_section_name(str(s.get("name") or s.get("type") or "verse"))
        bars = int(s.get("bars") or 8)
        bar_start = int(s.get("bar_start", current_bar))
        bar_end = int(s.get("bar_end", bar_start + bars))
        normalised_sections.append({
            **s,
            "name": name,
            "bar_start": bar_start,
            "bar_end": bar_end,
        })
        current_bar = bar_end

    for section in normalised_sections:
        name = section["name"]
        base_name = name.rstrip("_0123456789")  # strip numeric suffix for occurrence tracking
        occ_idx = occurrence_counters.get(base_name, 0)
        occurrence_counters[base_name] = occ_idx + 1

        prior_types = prior_types_by_section.get(base_name, set())

        events = generate_section_events(
            rng=rng,
            section=section,
            profile=profile,
            occurrence_index=occ_idx,
            available_roles=available_roles or list(_ALL_ROLES),
            prior_event_types=prior_types,
        )

        # Update prior event types for this base section
        new_types = {e.event_type for e in events}
        prior_types_by_section[base_name] = prior_types | new_types

        all_events.extend(events)

    return all_events
