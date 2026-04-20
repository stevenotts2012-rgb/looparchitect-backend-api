"""
Deterministic drop templates for the Drop Engine.

Each template encodes a named drop strategy suited to a specific section
transition scenario.  Templates are selected deterministically based on:

- The ``from_section`` → ``to_section`` boundary type
- The ``occurrence_index`` (how many times this boundary has been seen)
- The ``source_quality`` of the arrangement
- Available roles in the source material
- Prior boundary usage tracked in :class:`~app.services.drop_engine.state.DropEngineState`

Templates never raise — a well-behaved template always returns at least a
minimal :class:`~app.services.drop_engine.types.DropBoundaryPlan`.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.services.drop_engine.types import (
    DropBoundaryPlan,
    DropEvent,
    STRONG_EVENT_TYPES,
    SUPPORTED_DROP_EVENT_TYPES,
)
from app.services.drop_engine.state import DropEngineState


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_event(
    boundary_name: str,
    from_section: str,
    to_section: str,
    placement: str,
    event_type: str,
    intensity: float,
    parameters: Optional[Dict] = None,
    notes: Optional[str] = None,
) -> DropEvent:
    """Construct a :class:`DropEvent` with safe intensity clamping."""
    return DropEvent(
        boundary_name=boundary_name,
        from_section=from_section,
        to_section=to_section,
        placement=placement,
        event_type=event_type,
        intensity=max(0.0, min(1.0, float(intensity))),
        parameters=parameters or {},
        notes=notes,
    )


def _pick_non_repeating(
    candidates: List[str],
    state: DropEngineState,
    fallback: str,
) -> str:
    """Pick the first candidate not yet used as a primary event.

    Falls back to *fallback* when all candidates have been used.
    """
    for candidate in candidates:
        if not state.event_type_used(candidate):
            return candidate
    return fallback


# ---------------------------------------------------------------------------
# Named templates
# ---------------------------------------------------------------------------

def standard_hook_entry(
    boundary_name: str,
    from_section: str,
    to_section: str,
    occurrence_index: int,
    source_quality: str,
    available_roles: List[str],
    state: DropEngineState,
) -> DropBoundaryPlan:
    """Classic pre-hook tension → hook payoff.

    Occurrence 0: bass dropout before + re-entry accent on landing.
    Occurrence 1+: riser build before + crash hit on landing.
    """
    has_bass = any(r in available_roles for r in ("bass", "808"))
    has_drums = any(r in available_roles for r in ("drums", "percussion"))
    is_weak_source = source_quality in ("stereo_fallback", "ai_separated")

    if occurrence_index == 0:
        primary_type = (
            "bass_dropout" if has_bass and not state.event_type_used("bass_dropout")
            else "filtered_pre_drop"
        )
        primary_intensity = 0.75 if not is_weak_source else 0.55
        support_events = []
        if has_drums and not is_weak_source:
            support_events.append(
                _make_event(
                    boundary_name, from_section, to_section,
                    "post_boundary", "re_entry_accent", 0.7,
                    notes="standard hook entry re-entry accent",
                )
            )
        tension_score = 0.75 if not is_weak_source else 0.50
        payoff_score = 0.80 if not is_weak_source else 0.55
    else:
        primary_type = (
            "riser_build" if not state.event_type_used("riser_build")
            else "snare_pickup"
        )
        primary_intensity = 0.80 if not is_weak_source else 0.60
        support_events = []
        if has_drums and not is_weak_source:
            support_events.append(
                _make_event(
                    boundary_name, from_section, to_section,
                    "boundary", "crash_hit", 0.75,
                    notes="standard hook entry crash hit",
                )
            )
        tension_score = 0.80 if not is_weak_source else 0.55
        payoff_score = 0.85 if not is_weak_source else 0.60

    primary_event = _make_event(
        boundary_name, from_section, to_section,
        "pre_boundary", primary_type, primary_intensity,
        notes="standard hook entry primary",
    )

    return DropBoundaryPlan(
        from_section=from_section,
        to_section=to_section,
        occurrence_index=occurrence_index,
        tension_score=tension_score,
        payoff_score=payoff_score,
        primary_drop_event=primary_event,
        support_events=support_events,
        notes=["standard_hook_entry template"],
    )


def fakeout_hook_entry(
    boundary_name: str,
    from_section: str,
    to_section: str,
    occurrence_index: int,
    source_quality: str,
    available_roles: List[str],
    state: DropEngineState,
) -> DropBoundaryPlan:
    """Fakeout before the real hook drop.

    Places a ``kick_fakeout`` just before the boundary, then a real
    ``re_entry_accent`` post-boundary to confirm the landing.
    """
    is_weak_source = source_quality in ("stereo_fallback", "ai_separated")
    has_drums = any(r in available_roles for r in ("drums", "percussion"))

    primary_event = _make_event(
        boundary_name, from_section, to_section,
        "pre_boundary", "kick_fakeout",
        0.70 if not is_weak_source else 0.50,
        notes="fakeout hook entry primary",
    )

    support_events = []
    if has_drums and not is_weak_source:
        support_events.append(
            _make_event(
                boundary_name, from_section, to_section,
                "post_boundary", "re_entry_accent", 0.75,
                notes="fakeout hook entry re-entry payoff",
            )
        )

    return DropBoundaryPlan(
        from_section=from_section,
        to_section=to_section,
        occurrence_index=occurrence_index,
        tension_score=0.65 if not is_weak_source else 0.45,
        payoff_score=0.80 if not is_weak_source else 0.55,
        primary_drop_event=primary_event,
        support_events=support_events,
        notes=["fakeout_hook_entry template"],
    )


def delayed_hook_entry(
    boundary_name: str,
    from_section: str,
    to_section: str,
    occurrence_index: int,
    source_quality: str,
    available_roles: List[str],
    state: DropEngineState,
) -> DropBoundaryPlan:
    """Delayed drop — silence teases then staggered re-entry.

    Used to give later hook repetitions a more surprising feel.  Only
    applied when source quality allows silence-based events.
    """
    is_weak_source = source_quality in ("stereo_fallback", "ai_separated")

    if is_weak_source or state.silence_overused():
        # Downgrade to a riser build when silence is overused or source is weak.
        primary_type = "riser_build"
        payoff = 0.55
        tension = 0.50
        post_type: Optional[str] = None
    else:
        primary_type = "silence_tease"
        payoff = 0.90
        tension = 0.85
        post_type = "staggered_reentry"

    primary_event = _make_event(
        boundary_name, from_section, to_section,
        "pre_boundary", primary_type,
        0.80 if not is_weak_source else 0.55,
        notes="delayed hook entry primary",
    )

    support_events = []
    if post_type is not None:
        support_events.append(
            _make_event(
                boundary_name, from_section, to_section,
                "post_boundary", post_type, 0.80,
                notes="delayed hook entry staggered re-entry",
            )
        )

    return DropBoundaryPlan(
        from_section=from_section,
        to_section=to_section,
        occurrence_index=occurrence_index,
        tension_score=tension,
        payoff_score=payoff,
        primary_drop_event=primary_event,
        support_events=support_events,
        notes=["delayed_hook_entry template"],
    )


def sparse_bridge_return(
    boundary_name: str,
    from_section: str,
    to_section: str,
    occurrence_index: int,
    source_quality: str,
    available_roles: List[str],
    state: DropEngineState,
) -> DropBoundaryPlan:
    """Bridge or breakdown → hook: delayed re-entry for return impact.

    Uses ``delayed_drop`` primary + optional ``crash_hit`` or
    ``re_entry_accent`` support.
    """
    is_weak_source = source_quality in ("stereo_fallback", "ai_separated")
    has_drums = any(r in available_roles for r in ("drums", "percussion"))

    primary_type = _pick_non_repeating(
        ["delayed_drop", "staggered_reentry", "re_entry_accent"],
        state,
        fallback="riser_build",
    )
    primary_event = _make_event(
        boundary_name, from_section, to_section,
        "boundary", primary_type,
        0.75 if not is_weak_source else 0.50,
        notes="sparse bridge return primary",
    )

    support_events = []
    if has_drums and not is_weak_source:
        crash_type = (
            "crash_hit" if not state.event_type_used("crash_hit")
            else "re_entry_accent"
        )
        support_events.append(
            _make_event(
                boundary_name, from_section, to_section,
                "post_boundary", crash_type, 0.70,
                notes="sparse bridge return crash/accent",
            )
        )

    return DropBoundaryPlan(
        from_section=from_section,
        to_section=to_section,
        occurrence_index=occurrence_index,
        tension_score=0.60 if not is_weak_source else 0.40,
        payoff_score=0.75 if not is_weak_source else 0.50,
        primary_drop_event=primary_event,
        support_events=support_events,
        notes=["sparse_bridge_return template"],
    )


def smooth_hook_release(
    boundary_name: str,
    from_section: str,
    to_section: str,
    occurrence_index: int,
    source_quality: str,
    available_roles: List[str],
    state: DropEngineState,
) -> DropBoundaryPlan:
    """Hook → verse: controlled energy release without hard-stopping.

    No silence events.  Uses ``filtered_pre_drop`` or ``snare_pickup`` to
    taper energy gently.
    """
    is_weak_source = source_quality in ("stereo_fallback", "ai_separated")

    primary_type = _pick_non_repeating(
        ["filtered_pre_drop", "snare_pickup", "bass_dropout"],
        state,
        fallback="filtered_pre_drop",
    )
    primary_event = _make_event(
        boundary_name, from_section, to_section,
        "post_boundary", primary_type,
        0.55 if not is_weak_source else 0.35,
        notes="smooth hook release primary",
    )

    return DropBoundaryPlan(
        from_section=from_section,
        to_section=to_section,
        occurrence_index=occurrence_index,
        tension_score=0.40 if not is_weak_source else 0.25,
        payoff_score=0.50 if not is_weak_source else 0.30,
        primary_drop_event=primary_event,
        support_events=[],
        notes=["smooth_hook_release template"],
    )


def breakdown_rebuild(
    boundary_name: str,
    from_section: str,
    to_section: str,
    occurrence_index: int,
    source_quality: str,
    available_roles: List[str],
    state: DropEngineState,
) -> DropBoundaryPlan:
    """Breakdown → hook: rebuild tension and then re-enter with impact.

    Uses ``riser_build`` → ``crash_hit`` or ``re_entry_accent``.
    """
    is_weak_source = source_quality in ("stereo_fallback", "ai_separated")
    has_drums = any(r in available_roles for r in ("drums", "percussion"))

    primary_event = _make_event(
        boundary_name, from_section, to_section,
        "pre_boundary", "riser_build",
        0.80 if not is_weak_source else 0.55,
        notes="breakdown rebuild primary",
    )

    support_events = []
    if has_drums and not is_weak_source:
        support_type = (
            "crash_hit" if not state.event_type_used("crash_hit") else "re_entry_accent"
        )
        support_events.append(
            _make_event(
                boundary_name, from_section, to_section,
                "post_boundary", support_type, 0.80,
                notes="breakdown rebuild crash/re-entry",
            )
        )

    return DropBoundaryPlan(
        from_section=from_section,
        to_section=to_section,
        occurrence_index=occurrence_index,
        tension_score=0.75 if not is_weak_source else 0.50,
        payoff_score=0.80 if not is_weak_source else 0.55,
        primary_drop_event=primary_event,
        support_events=support_events,
        notes=["breakdown_rebuild template"],
    )


def outro_resolve(
    boundary_name: str,
    from_section: str,
    to_section: str,
    occurrence_index: int,
    source_quality: str,
    available_roles: List[str],
    state: DropEngineState,
) -> DropBoundaryPlan:
    """Any → outro: natural resolution, no hard stops.

    Uses ``filtered_pre_drop`` or ``reverse_fx_entry`` for a fading,
    conclusive feel.  No silence-based events.
    """
    is_weak_source = source_quality in ("stereo_fallback", "ai_separated")

    primary_type = (
        "reverse_fx_entry"
        if not is_weak_source and not state.event_type_used("reverse_fx_entry")
        else "filtered_pre_drop"
    )
    primary_event = _make_event(
        boundary_name, from_section, to_section,
        "boundary", primary_type,
        0.50 if not is_weak_source else 0.30,
        notes="outro resolve primary",
    )

    return DropBoundaryPlan(
        from_section=from_section,
        to_section=to_section,
        occurrence_index=occurrence_index,
        tension_score=0.25 if not is_weak_source else 0.15,
        payoff_score=0.40 if not is_weak_source else 0.25,
        primary_drop_event=primary_event,
        support_events=[],
        notes=["outro_resolve template"],
    )


# ---------------------------------------------------------------------------
# Template selector
# ---------------------------------------------------------------------------

def select_template(
    from_section: str,
    to_section: str,
    occurrence_index: int,
    source_quality: str,
    available_roles: List[str],
    state: DropEngineState,
) -> DropBoundaryPlan:
    """Select and apply the most appropriate drop template for a boundary.

    Parameters
    ----------
    from_section:
        Canonical section type being left (e.g. ``"pre_hook"``).
    to_section:
        Canonical section type being entered (e.g. ``"hook"``).
    occurrence_index:
        0-based occurrence counter for this boundary type in this run.
    source_quality:
        Source quality mode string.
    available_roles:
        Instrument roles present in the source material.
    state:
        Current :class:`~app.services.drop_engine.state.DropEngineState`.

    Returns
    -------
    DropBoundaryPlan
        A fully populated boundary plan.
    """
    boundary_name = f"{from_section} -> {to_section}"
    if occurrence_index > 0:
        boundary_name = f"{from_section} -> {to_section}_{occurrence_index + 1}"

    kwargs = dict(
        boundary_name=boundary_name,
        from_section=from_section,
        to_section=to_section,
        occurrence_index=occurrence_index,
        source_quality=source_quality,
        available_roles=available_roles,
        state=state,
    )

    # -----------------------------------------------------------------------
    # Outro transition — resolve naturally regardless of from_section.
    # -----------------------------------------------------------------------
    if to_section == "outro":
        return outro_resolve(**kwargs)

    # -----------------------------------------------------------------------
    # Hook-entry boundaries (pre_hook → hook).
    # -----------------------------------------------------------------------
    if from_section == "pre_hook" and to_section == "hook":
        if occurrence_index == 0:
            return standard_hook_entry(**kwargs)
        elif occurrence_index == 1:
            # Second hook entry: use fakeout for surprise.
            return fakeout_hook_entry(**kwargs)
        else:
            # Third+ hook entry: maximum payoff with delayed drop.
            return delayed_hook_entry(**kwargs)

    # -----------------------------------------------------------------------
    # Bridge / breakdown → hook: treat as rebuild return.
    # -----------------------------------------------------------------------
    if from_section in ("bridge", "breakdown") and to_section == "hook":
        return sparse_bridge_return(**kwargs)

    # -----------------------------------------------------------------------
    # Verse → pre_hook: begin tightening energy.
    # -----------------------------------------------------------------------
    if from_section == "verse" and to_section == "pre_hook":
        primary_type = _pick_non_repeating(
            ["snare_pickup", "bass_dropout", "filtered_pre_drop"],
            state,
            fallback="snare_pickup",
        )
        is_weak = source_quality in ("stereo_fallback", "ai_separated")
        primary_event = _make_event(
            boundary_name, from_section, to_section,
            "post_boundary", primary_type,
            0.60 if not is_weak else 0.40,
            notes="verse → pre_hook energy tightening",
        )
        return DropBoundaryPlan(
            from_section=from_section,
            to_section=to_section,
            occurrence_index=occurrence_index,
            tension_score=0.50 if not is_weak else 0.30,
            payoff_score=0.40 if not is_weak else 0.25,
            primary_drop_event=primary_event,
            support_events=[],
            notes=["verse_to_pre_hook tightening"],
        )

    # -----------------------------------------------------------------------
    # Hook → verse: smooth energy release.
    # -----------------------------------------------------------------------
    if from_section == "hook" and to_section == "verse":
        return smooth_hook_release(**kwargs)

    # -----------------------------------------------------------------------
    # Breakdown internal (verse/bridge → breakdown or breakdown → verse).
    # -----------------------------------------------------------------------
    if to_section in ("breakdown", "bridge"):
        is_weak = source_quality in ("stereo_fallback", "ai_separated")
        primary_type = _pick_non_repeating(
            ["bass_dropout", "filtered_pre_drop", "snare_pickup"],
            state,
            fallback="filtered_pre_drop",
        )
        primary_event = _make_event(
            boundary_name, from_section, to_section,
            "boundary", primary_type,
            0.55 if not is_weak else 0.35,
            notes="breakdown/bridge entry",
        )
        return DropBoundaryPlan(
            from_section=from_section,
            to_section=to_section,
            occurrence_index=occurrence_index,
            tension_score=0.45 if not is_weak else 0.25,
            payoff_score=0.50 if not is_weak else 0.30,
            primary_drop_event=primary_event,
            support_events=[],
            notes=["breakdown_entry template"],
        )

    # -----------------------------------------------------------------------
    # Fallback: minimal riser build with low scores.
    # -----------------------------------------------------------------------
    is_weak = source_quality in ("stereo_fallback", "ai_separated")
    primary_event = _make_event(
        boundary_name, from_section, to_section,
        "pre_boundary", "riser_build",
        0.45 if not is_weak else 0.25,
        notes="generic boundary fallback",
    )
    return DropBoundaryPlan(
        from_section=from_section,
        to_section=to_section,
        occurrence_index=occurrence_index,
        tension_score=0.35 if not is_weak else 0.20,
        payoff_score=0.35 if not is_weak else 0.20,
        primary_drop_event=primary_event,
        support_events=[],
        notes=["generic_fallback template"],
    )
