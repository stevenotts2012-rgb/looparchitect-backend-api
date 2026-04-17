from app.services.transition_engine import build_transition_plan
from app.services.section_identity_engine import get_transition_events
from app.services.arrangement_jobs import (
    _apply_producer_move_effect,
    _build_render_spec_summary,
)
from pydub import AudioSegment


def test_build_transition_plan_creates_expected_hook_boundary_events() -> None:
    sections = [
        {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.58, "active_stem_roles": ["drums", "bass"]},
        {"name": "Hook", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.92, "active_stem_roles": ["drums", "bass", "melody", "fx"]},
    ]

    result = build_transition_plan(
        sections=sections,
        stem_metadata={"enabled": True, "succeeded": True, "roles_detected": ["drums", "bass", "melody", "fx"]},
    )

    assert len(result["boundaries"]) == 1
    boundary = result["boundaries"][0]
    assert boundary["boundary"] == "verse_to_hook"
    assert "pre_hook_silence_drop" in boundary["events"]
    assert "crash_hit" in boundary["events"]
    assert any(event["type"] == "drum_fill" for event in result["events"])


def test_build_transition_plan_marks_final_hook_as_strongest() -> None:
    sections = [
        {"name": "Verse 1", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.55, "active_stem_roles": ["drums", "bass"]},
        {"name": "Hook 1", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.84, "active_stem_roles": ["drums", "bass", "melody"]},
        {"name": "Bridge", "type": "bridge", "bar_start": 16, "bars": 8, "energy": 0.5, "active_stem_roles": ["melody", "fx"]},
        {"name": "Final Hook", "type": "hook", "bar_start": 24, "bars": 8, "energy": 1.0, "active_stem_roles": ["drums", "bass", "melody", "fx"]},
    ]

    result = build_transition_plan(
        sections=sections,
        stem_metadata={"enabled": True, "succeeded": True, "roles_detected": ["drums", "bass", "melody", "fx"]},
    )
    boundaries = {item["boundary"]: item for item in result["boundaries"]}

    assert len(boundaries["bridge_to_hook"]["events"]) > len(boundaries["verse_to_hook"]["events"])
    assert "riser_fx" in boundaries["bridge_to_hook"]["events"]
    assert "reverse_cymbal" in boundaries["bridge_to_hook"]["events"]


# ---------------------------------------------------------------------------
# Tests proving hook entry is different from verse entry
# ---------------------------------------------------------------------------

def test_hook_entry_has_stronger_events_than_verse_entry() -> None:
    """Hook boundary must produce more and stronger events than a plain verse entry."""
    hook_events = get_transition_events(
        prev_section_type="verse",
        next_section_type="hook",
        prev_end_bar=7,
        next_start_bar=8,
        available_roles=["drums", "bass", "melody", "fx"],
    )
    verse_events = get_transition_events(
        prev_section_type="intro",
        next_section_type="verse",
        prev_end_bar=7,
        next_start_bar=8,
        available_roles=["drums", "bass", "melody"],
    )

    hook_types = {e.event_type for e in hook_events}
    verse_types = {e.event_type for e in verse_events}

    # Hook entry must include a silence gap and a crash / re-entry accent.
    assert hook_types & {"silence_drop_before_hook", "crash_hit", "re_entry_accent"}, (
        f"Hook entry should have silence_drop_before_hook or crash/re_entry_accent, got {hook_types}"
    )
    # Hook entry produces more events than a simple verse entry.
    assert len(hook_events) > len(verse_events), (
        f"Hook entry ({len(hook_events)} events) should produce more events than "
        f"verse entry ({len(verse_events)} events)"
    )
    # Hook entry is more intense than verse entry.
    max_hook_intensity = max((e.intensity for e in hook_events), default=0.0)
    max_verse_intensity = max((e.intensity for e in verse_events), default=0.0)
    assert max_hook_intensity >= max_verse_intensity, (
        f"Hook entry max intensity ({max_hook_intensity}) should be >= verse entry ({max_verse_intensity})"
    )


# ---------------------------------------------------------------------------
# Tests proving bridge/breakdown has a real density drop
# ---------------------------------------------------------------------------

def test_bridge_breakdown_entry_has_drop_events() -> None:
    """Bridge/breakdown boundary must produce events signalling density reduction."""
    for sparse_type in ("bridge", "breakdown"):
        events = get_transition_events(
            prev_section_type="hook",
            next_section_type=sparse_type,
            prev_end_bar=15,
            next_start_bar=16,
            available_roles=["drums", "bass", "melody", "fx"],
        )
        event_types = {e.event_type for e in events}
        assert event_types & {"silence_gap", "reverse_fx", "subtractive_entry"}, (
            f"{sparse_type} entry should have silence_gap/reverse_fx/subtractive_entry, got {event_types}"
        )
        # At least one start_of_section event should be present for the actual entry.
        start_events = [e for e in events if e.placement == "start_of_section"]
        assert start_events, (
            f"{sparse_type} entry should have a start_of_section event to smooth entry"
        )


# ---------------------------------------------------------------------------
# Tests proving outro resolves smoothly
# ---------------------------------------------------------------------------

def test_outro_entry_has_subtractive_entry() -> None:
    """Outro must open with a subtractive entry for natural resolution."""
    events = get_transition_events(
        prev_section_type="hook",
        next_section_type="outro",
        prev_end_bar=31,
        next_start_bar=32,
        available_roles=["drums", "bass", "melody"],
    )
    event_types = {e.event_type for e in events}
    assert "subtractive_entry" in event_types, (
        f"Outro should have subtractive_entry, got {event_types}"
    )
    start_events = [e for e in events if e.placement == "start_of_section"]
    assert any(e.event_type == "subtractive_entry" for e in start_events), (
        "subtractive_entry must be a start_of_section event so it's applied to the outro's opening"
    )


# ---------------------------------------------------------------------------
# Tests proving repeated sections use different transition types
# ---------------------------------------------------------------------------

def test_repeated_hook_uses_re_entry_accent_not_crash() -> None:
    """Second hook occurrence should use re_entry_accent to avoid same-entry recycling."""
    first_hook_events = get_transition_events(
        prev_section_type="verse",
        next_section_type="hook",
        prev_end_bar=7,
        next_start_bar=8,
        occurrence_of_next=1,
        is_repeat=False,
        available_roles=["drums", "bass", "melody", "fx"],
    )
    second_hook_events = get_transition_events(
        prev_section_type="bridge",
        next_section_type="hook",
        prev_end_bar=23,
        next_start_bar=24,
        occurrence_of_next=2,
        is_repeat=True,
        available_roles=["drums", "bass", "melody", "fx"],
    )

    first_start_types = {e.event_type for e in first_hook_events if e.placement == "start_of_section"}
    second_start_types = {e.event_type for e in second_hook_events if e.placement == "start_of_section"}

    assert "crash_hit" in first_start_types, (
        f"First hook entry should use crash_hit, got {first_start_types}"
    )
    assert "re_entry_accent" in second_start_types, (
        f"Second hook entry should use re_entry_accent, got {second_start_types}"
    )
    # The two sets of start-of-section event types must differ.
    assert first_start_types != second_start_types, (
        "Repeated hooks should use different entry event types to avoid recycled entries"
    )


# ---------------------------------------------------------------------------
# Tests proving transitions survive from plan to render (render enforcement)
# ---------------------------------------------------------------------------

def test_transitions_survive_plan_to_render_in_spec_summary() -> None:
    """Transition events planned in boundary_events must appear in the render spec summary."""
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
            "runtime_active_stems": ["drums", "bass", "melody", "fx"],
            "active_stem_roles": ["drums", "bass", "melody", "fx"],
            "applied_events": ["crash_hit", "silence_drop_before_hook"],
            "boundary_events": [
                {"type": "crash_hit", "placement": "on_downbeat"},
                {"type": "silence_drop_before_hook", "placement": "end_of_section"},
            ],
            "phrase_plan_used": False,
            "hook_evolution": {"stage": "hook1"},
            "phrase_plan": None,
        },
    ]

    summary = _build_render_spec_summary(timeline_sections)

    assert "transition_plan_by_section" in summary
    assert "actual_transition_events_used" in summary
    assert "transition_type_count" in summary
    assert "sections_missing_transitions" in summary
    assert "plan_vs_actual_transition_match" in summary

    # Both sections had transitions applied.
    assert summary["sections_missing_transitions"] == [], (
        f"No section should be missing transitions, got: {summary['sections_missing_transitions']}"
    )

    # The actual events used should include all events we injected.
    actual = set(summary["actual_transition_events_used"])
    assert "drum_fill" in actual
    assert "crash_hit" in actual
    assert "silence_drop_before_hook" in actual

    # Plan-to-actual match should be 1.0 since all planned events appear in applied_events.
    assert summary["plan_vs_actual_transition_match"] == 1.0, (
        f"Expected 1.0 plan match when all events are applied, got {summary['plan_vs_actual_transition_match']}"
    )

    # Type counts should reflect event totals.
    assert summary["transition_type_count"]["drum_fill"] == 1
    assert summary["transition_type_count"]["crash_hit"] == 1


# ---------------------------------------------------------------------------
# Tests proving new DSP effect handlers produce audible changes
# ---------------------------------------------------------------------------

def _make_test_segment(duration_ms: int = 2000, gain_db: float = -20.0) -> AudioSegment:
    """Create a test segment with known content."""
    from pydub.generators import Sine
    tone = Sine(440).to_audio_segment(duration=duration_ms).apply_gain(gain_db)
    return tone


def test_reverse_fx_effect_changes_segment() -> None:
    seg = _make_test_segment(2000)
    bar_ms = 500
    result = _apply_producer_move_effect(
        segment=seg, move_type="reverse_fx", intensity=0.8,
        stem_available=True, bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "reverse_fx must not change segment length"
    # The tail should be reversed — raw bytes should differ from the original tail.
    assert result.raw_data != seg.raw_data, "reverse_fx must mutate segment content"


def test_silence_gap_effect_attenuates_tail() -> None:
    seg = _make_test_segment(2000, gain_db=-10.0)
    bar_ms = 500
    result = _apply_producer_move_effect(
        segment=seg, move_type="silence_gap", intensity=0.8,
        stem_available=True, bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "silence_gap must not change segment length"
    # The tail of the result should be quieter than the original.
    tail_len = min(len(seg), int(bar_ms * 0.2))
    orig_tail_rms = seg[-tail_len:].rms
    result_tail_rms = result[-tail_len:].rms
    assert result_tail_rms < orig_tail_rms, (
        f"silence_gap tail should be quieter: orig={orig_tail_rms} result={result_tail_rms}"
    )


def test_subtractive_entry_attenuates_start() -> None:
    seg = _make_test_segment(2000, gain_db=-10.0)
    bar_ms = 500
    result = _apply_producer_move_effect(
        segment=seg, move_type="subtractive_entry", intensity=0.5,
        stem_available=True, bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "subtractive_entry must not change segment length"
    # The head of the result should be quieter than the original.
    head_len = min(len(seg), int(bar_ms * 0.25))
    orig_head_rms = seg[:head_len].rms
    result_head_rms = result[:head_len].rms
    assert result_head_rms <= orig_head_rms, (
        f"subtractive_entry head should be <= original: orig={orig_head_rms} result={result_head_rms}"
    )


def test_re_entry_accent_brightens_start() -> None:
    seg = _make_test_segment(2000, gain_db=-20.0)
    bar_ms = 500
    result = _apply_producer_move_effect(
        segment=seg, move_type="re_entry_accent", intensity=0.8,
        stem_available=True, bar_duration_ms=bar_ms,
    )
    assert len(result) == len(seg), "re_entry_accent must not change segment length"
    # The segment should have changed vs the original.
    assert result.raw_data != seg.raw_data, "re_entry_accent must mutate segment content"

