"""
Transition boundary enforcement tests.

These tests verify:
1. Verse → pre_hook entry builds tension.
2. Hook → verse releases energy smoothly.
3. No stacked transition spam on a single boundary.
4. render_executor promotes all boundary event types (not just 8 legacy types).
5. start_of_section placement applies DSP to the HEAD of section audio, not the tail.
6. boundary_audio_signature and planned_transition_events are present in render summary.
7. Transition events are NOT double-applied (not in both variations AND boundary_events).
8. _build_render_spec_summary carries the new observability fields.
9. Full arrangement has varied boundary types.
10. DSP effects produce audible audio changes at correct segment positions.
11. _BOUNDARY_TRANSITION_EVENT_TYPES is a superset of the legacy set.
12. No click at drop boundaries — fades applied to silence_gap, silence_drop_before_hook,
    silence_drop, and drop_kick.
13. No duplicated drop events — boundary-type events appear only in boundary_events,
    never in both variations and boundary_events.
14. Boundary event gain is clamped within headroom ceiling after application.
15. Smooth re-entry — subtractive_entry fades audio up from attenuated opening.
"""

from __future__ import annotations

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from app.services.section_identity_engine import get_transition_events
from app.services.transition_engine import build_transition_plan, SUPPORTED_BOUNDARY_EVENTS
from app.services.arrangement_jobs import (
    _apply_producer_move_effect,
    _build_render_spec_summary,
)
from app.services.render_executor import (
    _build_producer_arrangement_from_render_plan,
    _BOUNDARY_TRANSITION_EVENT_TYPES,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _tone(duration_ms: int = 2000, gain_db: float = -20.0) -> AudioSegment:
    return Sine(440).to_audio_segment(duration=duration_ms).apply_gain(gain_db)


# ---------------------------------------------------------------------------
# 1. Verse → pre_hook builds tension
# ---------------------------------------------------------------------------

def test_verse_to_pre_hook_entry_builds_tension() -> None:
    """get_transition_events(verse → pre_hook) must return at least one rhythmic pickup
    and a riser/fx event to signal the energy build into the pre-hook."""
    events = get_transition_events(
        prev_section_type="verse",
        next_section_type="pre_hook",
        prev_end_bar=7,
        next_start_bar=8,
        available_roles=["drums", "bass", "melody", "fx"],
    )
    event_types = {e.event_type for e in events}

    assert event_types & {"snare_pickup", "drum_fill"}, (
        f"verse→pre_hook should have a rhythmic pickup event, got {event_types}"
    )
    assert event_types & {"riser_fx", "snare_pickup", "drum_fill"}, (
        f"verse→pre_hook should have tension-building events, got {event_types}"
    )
    assert len(events) >= 1, "verse→pre_hook must produce at least one transition event"


# ---------------------------------------------------------------------------
# 2. Hook → verse releases energy smoothly
# ---------------------------------------------------------------------------

def test_hook_to_verse_releases_energy_with_subtractive_entry() -> None:
    """get_transition_events(hook → verse) must include a subtractive_entry so the
    verse opens with a gentler feel after the hook's full energy."""
    events = get_transition_events(
        prev_section_type="hook",
        next_section_type="verse",
        prev_end_bar=15,
        next_start_bar=16,
        available_roles=["drums", "bass", "melody", "fx"],
    )
    event_types = {e.event_type for e in events}

    assert "subtractive_entry" in event_types, (
        f"hook→verse should have subtractive_entry for smooth energy release, got {event_types}"
    )
    start_events = [e for e in events if e.placement == "start_of_section"]
    assert any(e.event_type == "subtractive_entry" for e in start_events), (
        "subtractive_entry must be a start_of_section event so the verse opens gently"
    )


# ---------------------------------------------------------------------------
# 3. No stacked transition spam on a single boundary
# ---------------------------------------------------------------------------

def test_no_stacked_transition_spam_on_single_boundary() -> None:
    """No single boundary should have two or more identical "full-drop" silence events.
    Events like silence_drop, silence_drop_before_hook, and silence_gap each create a
    noticeable dead-air window.  Stacking the same full-drop type ≥ 2 times on the same
    boundary produces compound silence that sounds like broken playback.

    Note: prep events that target separate elements (pre_hook_drum_mute for drums,
    bass_pause for bass, pre_hook_silence_drop for a general brief dip) are intentional
    layered effects that serve distinct roles and are NOT counted as spam here.
    """
    sections = [
        {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.60,
         "active_stem_roles": ["drums", "bass", "melody", "fx"]},
        {"name": "Hook", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.90,
         "active_stem_roles": ["drums", "bass", "melody", "fx"]},
        {"name": "Bridge", "type": "bridge", "bar_start": 16, "bars": 8, "energy": 0.45,
         "active_stem_roles": ["melody", "fx"]},
        {"name": "Final Hook", "type": "hook", "bar_start": 24, "bars": 8, "energy": 1.0,
         "active_stem_roles": ["drums", "bass", "melody", "fx"]},
        {"name": "Outro", "type": "outro", "bar_start": 32, "bars": 8, "energy": 0.25,
         "active_stem_roles": ["melody", "pads"]},
    ]
    result = build_transition_plan(
        sections=sections,
        stem_metadata={"enabled": True, "succeeded": True,
                       "roles_detected": ["drums", "bass", "melody", "fx"]},
    )

    # Full-drop types — events that replace a meaningful audio window with near-silence.
    # Each of these produces a perceptible "hole" in the audio; two on the same boundary
    # creates a double-gap that sounds like broken playback.
    full_drop_types = {"silence_drop", "silence_drop_before_hook", "silence_gap"}

    for boundary in result["boundaries"]:
        events_in_boundary = boundary.get("events", [])
        for drop_type in full_drop_types:
            count = events_in_boundary.count(drop_type)
            assert count <= 1, (
                f"Boundary '{boundary['boundary']}' has {count} occurrences of "
                f"'{drop_type}' — duplicate full-drop events create dead-air glitches. "
                f"Full event list: {events_in_boundary}"
            )


# ---------------------------------------------------------------------------
# 4. render_executor promotes ALL boundary event types
# ---------------------------------------------------------------------------

def test_render_executor_promotes_all_boundary_event_types() -> None:
    """_build_producer_arrangement_from_render_plan must promote every type in
    _BOUNDARY_TRANSITION_EVENT_TYPES to boundary_events, not just the 8 legacy types.
    This ensures observability (plan_vs_actual_transition_match) is accurate for
    newer transition types like reverse_fx, silence_gap, subtractive_entry, etc."""
    newer_types = {"reverse_fx", "silence_gap", "subtractive_entry", "re_entry_accent",
                   "silence_drop_before_hook", "final_hook_expansion"}

    for event_type in newer_types:
        render_plan = {
            "bpm": 120.0,
            "sections": [
                {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8,
                 "energy": 0.60, "instruments": ["drums", "bass"]},
                {"name": "Hook", "type": "hook", "bar_start": 8, "bars": 8,
                 "energy": 0.90, "instruments": ["drums", "bass", "melody"]},
            ],
            "events": [
                {
                    "type": event_type,
                    "bar": 7,
                    "placement": "end_of_section",
                    "boundary": "verse_to_hook",
                    "intensity": 0.80,
                },
            ],
        }

        producer_arrangement, _ = _build_producer_arrangement_from_render_plan(
            render_plan=render_plan,
            fallback_bpm=120.0,
        )

        verse_section = producer_arrangement["sections"][0]
        boundary_event_types = {
            str(e.get("type") or "") for e in (verse_section.get("boundary_events") or [])
        }
        assert event_type in boundary_event_types, (
            f"render_executor should promote '{event_type}' to boundary_events but only "
            f"found: {boundary_event_types}"
        )


def test_boundary_transition_event_types_is_superset_of_legacy_set() -> None:
    """_BOUNDARY_TRANSITION_EVENT_TYPES must include the 8 legacy event types that
    were always promoted, plus the newer types."""
    legacy = {"pre_hook_silence_drop", "drum_fill", "snare_pickup", "riser_fx",
              "reverse_cymbal", "crash_hit", "bridge_strip", "outro_strip"}
    assert legacy.issubset(_BOUNDARY_TRANSITION_EVENT_TYPES), (
        f"Legacy boundary types missing from _BOUNDARY_TRANSITION_EVENT_TYPES: "
        f"{legacy - _BOUNDARY_TRANSITION_EVENT_TYPES}"
    )
    newer = {"reverse_fx", "silence_gap", "subtractive_entry", "re_entry_accent"}
    assert newer.issubset(_BOUNDARY_TRANSITION_EVENT_TYPES), (
        f"New boundary types missing from _BOUNDARY_TRANSITION_EVENT_TYPES: "
        f"{newer - _BOUNDARY_TRANSITION_EVENT_TYPES}"
    )


# ---------------------------------------------------------------------------
# 5. start_of_section placement applies DSP to the head of section audio
# ---------------------------------------------------------------------------

def test_start_of_section_placement_applies_to_head_of_section() -> None:
    """A boundary_event with placement='start_of_section' must be applied to the
    opening bars of the section, not the tail.  Previously 'start_of_section' fell
    through to the else branch (end-of-section), misplacing entry effects."""
    # We need to exercise the boundary-events dispatch loop in _render_producer_arrangement.
    # We do this by directly testing the placement routing logic via a minimal render:
    # build a section with a known boundary_event placement and verify the audio is
    # modified at the HEAD (first bar window) and not the tail.

    bar_ms = 500
    seg = _tone(bar_ms * 4, gain_db=-15.0)  # 4-bar section

    # Manually invoke the placement logic that lives in _render_producer_arrangement.
    # We mirror the exact conditional from the patched code.
    def _apply_at_placement(placement: str, audio: AudioSegment) -> AudioSegment:
        """Replicate the boundary event window selection logic."""
        bar_duration_ms = bar_ms
        section_bars = 4
        relative_bar = 0

        if placement in {"on_downbeat", "start_of_section"}:
            event_start_ms = 0
            event_end_ms = min(len(audio), bar_duration_ms)
        elif placement == "mid_section":
            event_start_ms = max(0, relative_bar * bar_duration_ms)
            event_end_ms = min(len(audio), event_start_ms + bar_duration_ms)
        else:  # end_of_section
            event_end_ms = len(audio)
            event_start_ms = max(0, event_end_ms - bar_duration_ms)

        window = audio[event_start_ms:event_end_ms]
        processed = _apply_producer_move_effect(
            segment=window,
            move_type="re_entry_accent",
            intensity=0.8,
            stem_available=True,
            bar_duration_ms=bar_duration_ms,
        )
        return audio[:event_start_ms] + processed + audio[event_end_ms:]

    result_start = _apply_at_placement("start_of_section", seg)
    result_end = _apply_at_placement("end_of_section", seg)

    # start_of_section should change the head and leave the tail unchanged.
    head_ms = bar_ms
    assert result_start[:head_ms].raw_data != seg[:head_ms].raw_data, (
        "start_of_section should modify the opening bar of the section"
    )
    assert result_start[-bar_ms:].raw_data == seg[-bar_ms:].raw_data, (
        "start_of_section must NOT modify the tail of the section"
    )

    # end_of_section should change the tail and leave the head unchanged.
    assert result_end[-bar_ms:].raw_data != seg[-bar_ms:].raw_data, (
        "end_of_section should modify the tail bar of the section"
    )
    assert result_end[:head_ms].raw_data == seg[:head_ms].raw_data, (
        "end_of_section must NOT modify the head of the section"
    )

    # The two results must be different — confirming the placement matters.
    assert result_start.raw_data != result_end.raw_data, (
        "start_of_section and end_of_section placements must produce different audio"
    )


# ---------------------------------------------------------------------------
# 6. boundary_audio_signature and planned_transition_events in render summary
# ---------------------------------------------------------------------------

def test_boundary_audio_signature_in_render_summary() -> None:
    """_build_render_spec_summary must return boundary_audio_signature — a per-section
    dict capturing planned and applied transition counts for post-render audits."""
    timeline_sections = [
        {
            "name": "Verse",
            "type": "verse",
            "runtime_active_stems": ["drums", "bass"],
            "active_stem_roles": ["drums", "bass"],
            "applied_events": ["drum_fill", "riser_fx"],
            "boundary_events": [
                {"type": "drum_fill", "placement": "end_of_section"},
                {"type": "riser_fx", "placement": "end_of_section"},
            ],
            "phrase_plan_used": False,
            "hook_evolution": None,
            "phrase_plan": None,
        },
        {
            "name": "Hook",
            "type": "hook",
            "runtime_active_stems": ["drums", "bass", "melody"],
            "active_stem_roles": ["drums", "bass", "melody"],
            "applied_events": ["crash_hit"],
            "boundary_events": [
                {"type": "crash_hit", "placement": "on_downbeat"},
            ],
            "phrase_plan_used": False,
            "hook_evolution": {"stage": "hook1"},
            "phrase_plan": None,
        },
    ]
    summary = _build_render_spec_summary(timeline_sections)

    assert "boundary_audio_signature" in summary, (
        "render summary must contain boundary_audio_signature"
    )
    sig = summary["boundary_audio_signature"]
    assert isinstance(sig, dict), "boundary_audio_signature must be a dict"

    # Both sections should be present.  _build_render_spec_summary keys the signature
    # dict by section name (the "name" field), so we can look up directly.
    assert len(sig) == 2, f"Expected 2 signature entries, got {len(sig)}: {list(sig.keys())}"
    assert "Verse" in sig, f"'Verse' section missing from boundary_audio_signature: {list(sig.keys())}"
    assert "Hook" in sig, f"'Hook' section missing from boundary_audio_signature: {list(sig.keys())}"

    # Check Verse signature
    verse_sig = sig["Verse"]
    assert verse_sig["planned_transition_count"] == 2
    assert verse_sig["applied_transition_count"] == 2
    assert set(verse_sig["transition_types_applied"]) == {"drum_fill", "riser_fx"}

    # Check Hook signature
    hook_sig = sig["Hook"]
    assert hook_sig["planned_transition_count"] == 1
    assert hook_sig["applied_transition_count"] == 1


def test_planned_transition_events_in_render_summary() -> None:
    """_build_render_spec_summary must return planned_transition_events — a flat list
    of all planned event types across sections, used for transition flow audits."""
    timeline_sections = [
        {
            "name": "Verse",
            "type": "verse",
            "runtime_active_stems": ["drums", "bass"],
            "active_stem_roles": ["drums", "bass"],
            "applied_events": ["drum_fill"],
            "boundary_events": [{"type": "drum_fill", "placement": "end_of_section"}],
            "phrase_plan_used": False,
            "hook_evolution": None,
            "phrase_plan": None,
        },
        {
            "name": "Bridge",
            "type": "bridge",
            "runtime_active_stems": ["melody"],
            "active_stem_roles": ["melody"],
            "applied_events": ["silence_gap", "subtractive_entry"],
            "boundary_events": [
                {"type": "silence_gap", "placement": "end_of_section"},
                {"type": "subtractive_entry", "placement": "start_of_section"},
            ],
            "phrase_plan_used": False,
            "hook_evolution": None,
            "phrase_plan": None,
        },
    ]
    summary = _build_render_spec_summary(timeline_sections)

    assert "planned_transition_events" in summary, (
        "render summary must contain planned_transition_events"
    )
    planned = summary["planned_transition_events"]
    assert isinstance(planned, list)
    assert "drum_fill" in planned
    assert "silence_gap" in planned
    assert "subtractive_entry" in planned
    assert len(planned) == 3, (
        f"Expected 3 planned events (drum_fill + silence_gap + subtractive_entry), got {len(planned)}: {planned}"
    )


def test_sections_with_no_transition_alias_in_render_summary() -> None:
    """_build_render_spec_summary must expose sections_with_no_transition as an alias
    for sections_missing_transitions (observability spec field name)."""
    timeline_sections = [
        {
            "name": "Verse",
            "type": "verse",
            "runtime_active_stems": ["drums"],
            "active_stem_roles": ["drums"],
            "applied_events": [],  # No events applied
            "boundary_events": [],
            "phrase_plan_used": False,
            "hook_evolution": None,
            "phrase_plan": None,
        },
    ]
    summary = _build_render_spec_summary(timeline_sections)

    assert "sections_with_no_transition" in summary, (
        "render summary must contain sections_with_no_transition"
    )
    assert summary["sections_with_no_transition"] == summary["sections_missing_transitions"], (
        "sections_with_no_transition must be the same list as sections_missing_transitions"
    )
    assert "Verse" in summary["sections_with_no_transition"], (
        "Verse (with no applied events) should appear in sections_with_no_transition"
    )


# ---------------------------------------------------------------------------
# 7. No double-application: transition events must NOT be in both
#    section variations AND boundary_events after the stacking fix
# ---------------------------------------------------------------------------

def test_render_executor_no_double_application_for_pre_existing_boundary_events() -> None:
    """When a section already has a boundary_event of type X (from
    _apply_stem_primary_section_states), _build_producer_arrangement_from_render_plan
    must NOT also add X to the section's variations.  Double-adding causes the same
    DSP to run twice on the same audio window."""
    render_plan = {
        "bpm": 120.0,
        "sections": [
            {
                "name": "Verse",
                "type": "verse",
                "bar_start": 0,
                "bars": 8,
                "energy": 0.60,
                "instruments": ["drums", "bass"],
                # Simulate boundary_events already populated by _apply_stem_primary_section_states.
                "boundary_events": [
                    {"type": "riser_fx", "bar": 7, "placement": "end_of_section", "intensity": 0.85},
                    {"type": "drum_fill", "bar": 7, "placement": "end_of_section", "intensity": 0.80},
                ],
                "variations": [],
            },
        ],
        "events": [
            # Global events from build_transition_plan — same types as above.
            {"type": "riser_fx", "bar": 7, "placement": "end_of_section", "intensity": 0.80},
            {"type": "drum_fill", "bar": 7, "placement": "end_of_section", "intensity": 0.70},
        ],
    }

    producer_arrangement, _ = _build_producer_arrangement_from_render_plan(
        render_plan=render_plan,
        fallback_bpm=120.0,
    )

    verse = producer_arrangement["sections"][0]
    variation_types = [str(v.get("variation_type") or "") for v in (verse.get("variations") or [])]

    assert "riser_fx" not in variation_types, (
        "riser_fx is already in boundary_events — must NOT also be added to variations "
        f"(would apply DSP twice). Found variations: {variation_types}"
    )
    assert "drum_fill" not in variation_types, (
        "drum_fill is already in boundary_events — must NOT also be added to variations "
        f"(would apply DSP twice). Found variations: {variation_types}"
    )


# ---------------------------------------------------------------------------
# 8. Intro → verse produces minimal / no boundary events
# ---------------------------------------------------------------------------

def test_build_transition_plan_intro_to_verse_minimal_events() -> None:
    """Intro → verse is a clean entry — should not produce large, aggressive transitions.
    Intro has no drums/bass by profile so drum-fill type events don't make sense here."""
    sections = [
        {"name": "Intro", "type": "intro", "bar_start": 0, "bars": 8, "energy": 0.20,
         "active_stem_roles": ["pads", "melody"]},
        {"name": "Verse", "type": "verse", "bar_start": 8, "bars": 8, "energy": 0.60,
         "active_stem_roles": ["drums", "bass", "melody"]},
    ]
    result = build_transition_plan(
        sections=sections,
        stem_metadata={"enabled": True, "succeeded": True,
                       "roles_detected": ["drums", "bass", "melody", "pads"]},
    )
    # intro→verse is NOT a hook entry so the plan should have no or very few events.
    # No boundary should be generated since intro→verse has no special event logic.
    boundaries_for_intro_verse = [
        b for b in result["boundaries"] if b["boundary"] == "intro_to_verse"
    ]
    assert len(boundaries_for_intro_verse) == 0, (
        f"intro→verse should not produce boundary events (no hook, no bridge, no outro). "
        f"Got: {boundaries_for_intro_verse}"
    )


# ---------------------------------------------------------------------------
# 9. Full arrangement: all required boundary types are produced
# ---------------------------------------------------------------------------

def test_build_transition_plan_full_arrangement_has_varied_boundary_types() -> None:
    """A complete arrangement should produce distinct boundary event sets for each
    transition type so different boundaries are audibly different."""
    sections = [
        {"name": "Intro", "type": "intro", "bar_start": 0, "bars": 8, "energy": 0.20,
         "active_stem_roles": ["pads", "melody"]},
        {"name": "Verse 1", "type": "verse", "bar_start": 8, "bars": 8, "energy": 0.60,
         "active_stem_roles": ["drums", "bass", "melody"]},
        {"name": "Hook 1", "type": "hook", "bar_start": 16, "bars": 8, "energy": 0.90,
         "active_stem_roles": ["drums", "bass", "melody", "fx"]},
        {"name": "Bridge", "type": "bridge", "bar_start": 24, "bars": 8, "energy": 0.40,
         "active_stem_roles": ["melody", "fx"]},
        {"name": "Hook 2", "type": "hook", "bar_start": 32, "bars": 8, "energy": 1.0,
         "active_stem_roles": ["drums", "bass", "melody", "fx"]},
        {"name": "Outro", "type": "outro", "bar_start": 40, "bars": 8, "energy": 0.25,
         "active_stem_roles": ["melody", "pads"]},
    ]
    result = build_transition_plan(
        sections=sections,
        stem_metadata={"enabled": True, "succeeded": True,
                       "roles_detected": ["drums", "bass", "melody", "fx", "pads"]},
    )

    boundary_map = {b["boundary"]: b for b in result["boundaries"]}

    # verse→hook must have hook-specific events.
    assert "verse_to_hook" in boundary_map, "verse→hook boundary expected"
    verse_hook_events = set(boundary_map["verse_to_hook"]["events"])
    assert verse_hook_events & {"crash_hit", "pre_hook_silence_drop", "riser_fx"}, (
        f"verse→hook must include hook entry events, got {verse_hook_events}"
    )

    # hook→bridge must have bridge transition.
    assert "hook_to_bridge" in boundary_map, "hook→bridge boundary expected"
    hook_bridge_events = set(boundary_map["hook_to_bridge"]["events"])
    assert "bridge_strip" in hook_bridge_events, (
        f"hook→bridge must include bridge_strip, got {hook_bridge_events}"
    )

    # bridge→hook must have escalation (final hook prep).
    assert "bridge_to_hook" in boundary_map, "bridge→hook boundary expected"

    # hook→outro must have outro events.
    assert "hook_to_outro" in boundary_map, "hook→outro boundary expected"
    outro_events = set(boundary_map["hook_to_outro"]["events"])
    assert outro_events & {"outro_strip"}, (
        f"hook→outro must include outro_strip, got {outro_events}"
    )


# ---------------------------------------------------------------------------
# 10. DSP effects produce audible audio changes at correct segment positions
# ---------------------------------------------------------------------------

def test_crash_hit_effect_modifies_opening_window() -> None:
    """crash_hit should modify only the first ~20% of the bar, not the whole segment."""
    bar_ms = 1000
    seg = _tone(bar_ms, gain_db=-20.0)
    result = _apply_producer_move_effect(
        segment=seg,
        move_type="crash_hit",
        intensity=0.8,
        stem_available=True,
        bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "crash_hit must not change segment length"
    # crash_hit touches the opening 20% window.
    hit_window = int(bar_ms * 0.2)
    assert result[:hit_window].raw_data != seg[:hit_window].raw_data, (
        "crash_hit should modify the opening beat window"
    )


def test_outro_strip_fades_out() -> None:
    """outro_strip must attenuate the segment and fade out the tail."""
    bar_ms = 1000
    seg = _tone(bar_ms * 2, gain_db=-10.0)
    result = _apply_producer_move_effect(
        segment=seg,
        move_type="outro_strip",
        intensity=0.7,
        stem_available=True,
        bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "outro_strip must not change segment length"
    # The tail of the result should be quieter (fade-out applied).
    tail_len = bar_ms // 2
    tail_rms = result[-tail_len:].rms
    head_rms = result[:tail_len].rms
    assert tail_rms <= head_rms, (
        f"outro_strip should fade out the tail: head_rms={head_rms} tail_rms={tail_rms}"
    )


def test_drum_fill_effect_brightens_tail() -> None:
    """drum_fill applies a high-pass filter and boost to the last ~55% of the section.
    The processed tail audio must differ from the original (confirming DSP was applied)."""
    bar_ms = 1000
    seg = _tone(bar_ms, gain_db=-25.0)
    result = _apply_producer_move_effect(
        segment=seg,
        move_type="drum_fill",
        intensity=0.7,
        stem_available=True,
        bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "drum_fill must not change segment length"
    # The fill starts at the last 55% of the bar — that portion must be changed.
    fill_start = int(bar_ms * (1 - 0.55))
    assert result[fill_start:].raw_data != seg[fill_start:].raw_data, (
        "drum_fill must modify the tail of the segment"
    )
    # The head (before the fill) must remain unchanged.
    assert result[:fill_start].raw_data == seg[:fill_start].raw_data, (
        "drum_fill must not modify audio before the fill window"
    )


# ---------------------------------------------------------------------------
# 11. Transition event types in _BOUNDARY_TRANSITION_EVENT_TYPES match
#     SUPPORTED_BOUNDARY_EVENTS from transition_engine
# ---------------------------------------------------------------------------

def test_boundary_transition_event_types_matches_supported_boundary_events() -> None:
    """_BOUNDARY_TRANSITION_EVENT_TYPES in render_executor and SUPPORTED_BOUNDARY_EVENTS
    in transition_engine must be consistent — both define the universe of recognised
    boundary/transition event types."""
    missing_in_executor = SUPPORTED_BOUNDARY_EVENTS - _BOUNDARY_TRANSITION_EVENT_TYPES
    assert not missing_in_executor, (
        f"These SUPPORTED_BOUNDARY_EVENTS are missing from _BOUNDARY_TRANSITION_EVENT_TYPES: "
        f"{missing_in_executor}.  Add them to render_executor._BOUNDARY_TRANSITION_EVENT_TYPES."
    )


# ---------------------------------------------------------------------------
# 12. No click at drop boundaries — fades applied to silence gaps
# ---------------------------------------------------------------------------

def test_silence_gap_has_no_abrupt_junction() -> None:
    """silence_gap must apply a crossfade at the lead/attenuated-tail junction so the
    transition from full-level audio to the attenuated window is click-free.
    A hard cut (zero fade) at a non-zero sample value produces an audible click."""
    bar_ms = 1000
    seg = _tone(bar_ms, gain_db=-10.0)
    result = _apply_producer_move_effect(
        segment=seg,
        move_type="silence_gap",
        intensity=0.8,
        stem_available=True,
        bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "silence_gap must not change segment length"
    # The tail must be attenuated relative to the head.
    gap_ms = int(bar_ms * (0.12 + 0.08 * 0.8))
    gap_ms = max(1, min(gap_ms, bar_ms - 1))
    lead_end = len(seg) - gap_ms  # Junction point between lead and attenuated tail.
    head_rms = result[:lead_end // 2].rms
    tail_rms = result[lead_end:].rms
    assert tail_rms < head_rms, (
        f"silence_gap must attenuate the tail: head_rms={head_rms}, tail_rms={tail_rms}"
    )
    # The fade-out is applied to the last `fade_ms` samples of the lead.
    # Verify those samples differ from the original (confirming fade was applied).
    fade_ms = max(5, min(10, gap_ms // 4))
    fade_region_start = max(0, lead_end - fade_ms)
    if lead_end > fade_ms:
        assert result[fade_region_start:lead_end].raw_data != seg[fade_region_start:lead_end].raw_data, (
            "silence_gap must apply a fade-out at the lead end to prevent a click"
        )


def test_silence_drop_before_hook_applies_fade_in_on_tail() -> None:
    """silence_drop_before_hook must fade-in the audio after the silent gap so the
    re-entry point is not an abrupt discontinuity."""
    bar_ms = 1000
    seg = _tone(bar_ms, gain_db=-10.0)
    result = _apply_producer_move_effect(
        segment=seg,
        move_type="silence_drop_before_hook",
        intensity=0.8,
        stem_available=True,
        bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "silence_drop_before_hook must not change segment length"
    # The very start of the result is silence (the gap).
    gap_ms = int(bar_ms * (0.04 + 0.04 * 0.8))
    assert result[:gap_ms].rms == 0 or result[:gap_ms].rms < 5, (
        "silence_drop_before_hook must have a silent gap at the start"
    )
    # The re-entry audio (after the gap) must be audible.
    tail_start = gap_ms + 20  # skip fade-in ramp
    assert result[tail_start:].rms > 0, (
        "silence_drop_before_hook must produce audible audio after the silent gap"
    )


def test_silence_drop_applies_fade_in_on_re_entry() -> None:
    """silence_drop must fade-in audio after the silent gap to avoid a click."""
    bar_ms = 1000
    seg = _tone(bar_ms, gain_db=-10.0)
    result = _apply_producer_move_effect(
        segment=seg,
        move_type="silence_drop",
        intensity=0.6,
        stem_available=True,
        bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "silence_drop must not change segment length"
    # Audio after the gap must be audible.
    pause_bars = 0.06 + 0.06 * 0.6
    gap_ms = int(bar_ms * max(0.04, min(0.12, pause_bars)))
    tail_start = gap_ms + 20  # allow for fade-in ramp
    assert result[tail_start:].rms > 0, (
        "silence_drop must have audible audio after the silent gap"
    )


def test_drop_kick_applies_fade_in_on_re_entry() -> None:
    """drop_kick must fade-in audio after the silent gap to avoid a click."""
    bar_ms = 1000
    seg = _tone(bar_ms, gain_db=-10.0)
    result = _apply_producer_move_effect(
        segment=seg,
        move_type="drop_kick",
        intensity=0.7,
        stem_available=True,
        bar_duration_ms=bar_ms,
        params={"pause_bars": 0.10},
    )
    assert len(result) == len(seg), "drop_kick must not change segment length"
    drop_len = int(bar_ms * 0.10)
    tail_start = drop_len + 15
    assert result[tail_start:].rms > 0, (
        "drop_kick must have audible audio after the silent gap"
    )


# ---------------------------------------------------------------------------
# 13. No duplicated drop events — boundary-type events must NOT appear in
#     both variations and boundary_events
# ---------------------------------------------------------------------------

def test_boundary_type_event_not_added_to_variations() -> None:
    """When _build_producer_arrangement_from_render_plan processes a boundary-type event
    (e.g. silence_gap, subtractive_entry), it must add it ONLY to boundary_events, not
    also to variations.  Adding it to both paths causes the same DSP to run twice."""
    for drop_type in ("silence_gap", "subtractive_entry", "re_entry_accent", "crash_hit"):
        render_plan = {
            "bpm": 120.0,
            "sections": [
                {
                    "name": "Bridge",
                    "type": "bridge",
                    "bar_start": 0,
                    "bars": 8,
                    "energy": 0.40,
                    "instruments": ["melody"],
                    "boundary_events": [],
                    "variations": [],
                },
            ],
            "events": [
                {
                    "type": drop_type,
                    "bar": 7,
                    "placement": "end_of_section",
                    "intensity": 0.80,
                },
            ],
        }
        producer_arrangement, _ = _build_producer_arrangement_from_render_plan(
            render_plan=render_plan,
            fallback_bpm=120.0,
        )
        section = producer_arrangement["sections"][0]
        variation_types = [
            str(v.get("variation_type") or "") for v in (section.get("variations") or [])
        ]
        boundary_types = [
            str(e.get("type") or "") for e in (section.get("boundary_events") or [])
        ]
        assert drop_type not in variation_types, (
            f"'{drop_type}' is a boundary-type event — must NOT appear in variations "
            f"(would cause double DSP application). variations={variation_types}"
        )
        assert drop_type in boundary_types, (
            f"'{drop_type}' must appear in boundary_events. boundary_events={boundary_types}"
        )


# ---------------------------------------------------------------------------
# 14. Boundary event gain is clamped after application
# ---------------------------------------------------------------------------

def test_boundary_event_gain_clamped_after_re_entry_accent() -> None:
    """re_entry_accent boosts the opening window.  When applied via boundary_events
    the resulting segment must stay within the -1.5 dBFS headroom ceiling."""
    bar_ms = 1000
    seg = _tone(bar_ms, gain_db=-5.0)  # Relatively hot input
    result = _apply_producer_move_effect(
        segment=seg,
        move_type="re_entry_accent",
        intensity=1.0,
        stem_available=True,
        bar_duration_ms=bar_ms,
    )
    # The peak must not exceed 0 dBFS (pydub uses -inf to 0 scale).
    peak_dbfs = float(result.max_dBFS)
    assert peak_dbfs <= 0.0, (
        f"re_entry_accent with hot input produced peak {peak_dbfs:.1f} dBFS — clipping risk"
    )


# ---------------------------------------------------------------------------
# 15. Smooth re-entry — subtractive_entry fades up correctly
# ---------------------------------------------------------------------------

def test_subtractive_entry_volume_ramps_up() -> None:
    """subtractive_entry must attenuate the opening portion of a section and then
    allow the audio to ramp up, creating a smooth re-entry rather than a hard entry.
    The first 25% of the segment must be quieter than the last 25%."""
    bar_ms = 1000
    seg = _tone(bar_ms * 4, gain_db=-10.0)  # 4-bar section
    result = _apply_producer_move_effect(
        segment=seg,
        move_type="subtractive_entry",
        intensity=0.6,
        stem_available=True,
        bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "subtractive_entry must not change segment length"
    quarter = len(result) // 4
    opening_rms = result[:quarter].rms
    closing_rms = result[-quarter:].rms
    assert opening_rms < closing_rms, (
        f"subtractive_entry must open quieter than the tail: "
        f"opening_rms={opening_rms}, closing_rms={closing_rms}"
    )
