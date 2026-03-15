import json

from pydub import AudioSegment
from pydub.generators import Sine

from app.services.arrangement_jobs import (
    _apply_stem_primary_section_states,
    _build_pre_render_plan,
    _render_producer_arrangement,
)


def _difference_ratio(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 0.0
    return 1.0 - (len(left_set & right_set) / len(union))


def test_section_active_stems_show_producer_contrast_rules() -> None:
    sections = [
        {"name": "Intro", "type": "intro", "bars": 4, "bar_start": 0},
        {"name": "Verse", "type": "verse", "bars": 8, "bar_start": 4},
        {"name": "Pre-Hook", "type": "pre_hook", "bars": 4, "bar_start": 12},
        {"name": "Hook", "type": "hook", "bars": 8, "bar_start": 16},
        {"name": "Bridge", "type": "bridge", "bars": 8, "bar_start": 24},
        {"name": "Outro", "type": "outro", "bars": 4, "bar_start": 32},
    ]
    stem_metadata = {
        "enabled": True,
        "succeeded": True,
        "roles_detected": ["drums", "bass", "melody", "pads", "fx"],
    }

    updated = _apply_stem_primary_section_states(sections, stem_metadata)

    by_name = {section["name"]: section["active_stem_roles"] for section in updated}

    assert _difference_ratio(by_name["Intro"], by_name["Verse"]) >= 0.4
    assert _difference_ratio(by_name["Verse"], by_name["Hook"]) >= 0.25
    assert _difference_ratio(by_name["Bridge"], by_name["Hook"]) >= 0.5


def test_transition_events_exist_before_hook() -> None:
    producer_arrangement = {
        "total_bars": 20,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.55, "instruments": ["kick", "bass"]},
            {"name": "Pre-Hook", "type": "pre_hook", "bar_start": 8, "bars": 4, "energy": 0.68, "instruments": ["percussion", "bass", "fx"]},
            {"name": "Hook", "type": "hook", "bar_start": 12, "bars": 8, "energy": 0.95, "instruments": ["kick", "snare", "bass", "melody", "fx"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=9001,
        bpm=120.0,
        target_seconds=40,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={"enabled": True, "succeeded": True, "roles_detected": ["drums", "bass", "melody", "fx"]},
        loop_variation_manifest=None,
    )

    hook_bar = 12
    pre_hook_events = [
        event for event in render_plan.get("events", [])
        if int(event.get("bar", 0) or 0) == hook_bar - 1
    ]

    assert any(event.get("type") in {"pre_hook_silence_drop", "pre_hook_drum_mute", "snare_pickup", "drum_fill"} for event in pre_hook_events)


def test_runtime_timeline_contains_section_debug_report() -> None:
    tone = Sine(220).to_audio_segment(duration=8000).set_channels(2) - 10
    producer_arrangement = {
        "sections": [
            {
                "name": "Verse",
                "type": "verse",
                "bar_start": 0,
                "bars": 2,
                "energy": 0.55,
                "instruments": ["drums", "bass"],
                "variations": [{"variation_type": "drum_fill", "bar": 1, "intensity": 0.7}],
            },
            {
                "name": "Hook",
                "type": "hook",
                "bar_start": 2,
                "bars": 2,
                "energy": 0.92,
                "instruments": ["drums", "bass", "melody", "fx"],
                "variations": [{"variation_type": "crash_hit", "bar": 2, "intensity": 0.8}],
            },
        ],
        "tracks": [],
        "transitions": [{"from_section": 0, "type": "impact", "duration_bars": 1}],
        "energy_curve": [],
        "total_bars": 4,
    }

    _audio, timeline_json = _render_producer_arrangement(
        loop_audio=tone,
        producer_arrangement=producer_arrangement,
        bpm=120.0,
        stems=None,
        loop_variations=None,
    )

    payload = json.loads(timeline_json)
    report = payload.get("producer_debug_report") or []

    assert len(report) == 2
    assert report[1].get("active_stems")
    assert isinstance(report[1].get("transition_events_inserted"), list)
    assert isinstance(report[1].get("difference_from_previous"), list)
