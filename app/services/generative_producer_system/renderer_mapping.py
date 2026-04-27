"""
Renderer action mapping for the Generative Producer System.

Maps ProducerEvent.event_type strings to supported render_action strings.
Events with no supported mapping are NOT silently ignored — they are
returned as SkippedEvent records.
"""

from __future__ import annotations

from app.services.generative_producer_system.types import (
    ProducerEvent,
    SkippedEvent,
    SUPPORTED_RENDER_ACTIONS,
)

# ---------------------------------------------------------------------------
# Event-type → render_action mapping
# ---------------------------------------------------------------------------
# Each event_type maps to the primary render_action that a renderer can
# execute.  render_action values must be members of SUPPORTED_RENDER_ACTIONS.

EVENT_TYPE_TO_RENDER_ACTION: dict[str, str] = {
    # Drum pattern changes
    "drum_pattern_change": "add_drum_fill",
    "drum_dropout": "mute_role",
    "drum_reentry": "unmute_role",
    "drum_fill": "add_drum_fill",
    # 808 / bass
    "bass_pattern_variation": "bass_pattern_variation",
    "bass_dropout": "mute_role",
    "bass_reentry": "unmute_role",
    "sliding_bass": "bass_pattern_variation",
    # Hi-hat rolls / stutters
    "hat_roll": "add_hat_roll",
    "hat_stutter": "add_hat_roll",
    # Melody chops
    "melody_chop": "chop_role",
    "melody_reverse": "reverse_slice",
    # Melody filter moves
    "melody_filter": "filter_role",
    "filter_open": "filter_role",
    "filter_close": "filter_role",
    # Counter-melody / pad exposure
    "pad_expose": "unmute_role",
    "pad_mute": "mute_role",
    "counter_melody": "unmute_role",
    # FX transitions
    "fx_riser": "add_fx_riser",
    "fx_impact": "add_impact",
    "fx_dropout": "mute_role",
    # Automation events
    "automation_widen": "widen_role",
    "automation_fade": "fade_role",
    "automation_delay": "delay_role",
    "automation_reverb": "reverb_tail",
    # Section-specific dropouts
    "section_dropout": "mute_role",
    # Hook payoff boosts
    "hook_payoff": "add_impact",
    "hook_widen": "widen_role",
    # Generic role control
    "mute_role": "mute_role",
    "unmute_role": "unmute_role",
}


def resolve_render_action(event_type: str) -> str | None:
    """Return the render_action for event_type, or None if unsupported."""
    return EVENT_TYPE_TO_RENDER_ACTION.get(event_type)


def map_event(event: ProducerEvent) -> tuple[ProducerEvent | None, SkippedEvent | None]:
    """Resolve render_action for *event*.

    Returns (event_with_action, None) when supported.
    Returns (None, skipped_event) when not supported.

    The caller should already have set render_action during construction;
    this function validates that it is in SUPPORTED_RENDER_ACTIONS and
    repairs it via the mapping when possible.
    """
    action = event.render_action
    if action in SUPPORTED_RENDER_ACTIONS:
        return event, None

    # Try to resolve via event_type
    resolved = resolve_render_action(event.event_type)
    if resolved and resolved in SUPPORTED_RENDER_ACTIONS:
        from dataclasses import replace
        return replace(event, render_action=resolved), None

    skipped = SkippedEvent(
        event_id=event.event_id,
        section_name=event.section_name,
        event_type=event.event_type,
        skipped_reason=(
            f"No supported render_action for event_type={event.event_type!r} "
            f"(render_action={action!r})"
        ),
    )
    return None, skipped


def validate_render_action(render_action: str) -> bool:
    """Return True if render_action is in the supported set."""
    return render_action in SUPPORTED_RENDER_ACTIONS
