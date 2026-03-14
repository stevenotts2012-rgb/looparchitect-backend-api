from app.services.arrangement_jobs import (
    _apply_stem_primary_section_states,
    _build_section_audio_from_stems,
    _build_pre_render_plan,
    _render_producer_arrangement,
    _validate_render_plan_quality,
)
from pydub import AudioSegment
from pydub.generators import Sine
import json


def test_build_pre_render_plan_assigns_loop_variants_to_sections() -> None:
    loop_variation_manifest = {
        "active": True,
        "count": 5,
        "names": ["intro", "verse", "hook", "bridge", "outro"],
        "files": {
            "intro": "loop_intro.wav",
            "verse": "loop_verse.wav",
            "hook": "loop_hook.wav",
            "bridge": "loop_bridge.wav",
            "outro": "loop_outro.wav",
        },
        "stems_used": True,
    }

    producer_arrangement = {
        "total_bars": 24,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Intro", "type": "intro", "bar_start": 0, "bars": 4, "energy": 0.3, "instruments": ["melody"]},
            {"name": "Verse", "type": "verse", "bar_start": 4, "bars": 8, "energy": 0.6, "instruments": ["kick", "bass"]},
            {"name": "Hook", "type": "hook", "bar_start": 12, "bars": 8, "energy": 0.9, "instruments": ["kick", "snare", "bass", "melody"]},
            {"name": "Outro", "type": "outro", "bar_start": 20, "bars": 4, "energy": 0.4, "instruments": ["melody"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=123,
        bpm=120.0,
        target_seconds=90,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={"enabled": True, "succeeded": True},
        loop_variation_manifest=loop_variation_manifest,
    )

    section_variants = {str(section.get("loop_variant")) for section in render_plan["sections"]}

    assert render_plan["loop_variations"]["active"] is True
    assert render_plan["loop_variations"]["count"] == 5
    assert len(section_variants) >= 3
    assert any(section.get("loop_variant_file") == "loop_hook.wav" for section in render_plan["sections"])


def test_render_plan_quality_fails_when_all_sections_share_one_variant() -> None:
    render_plan = {
        "sections": [
            {"name": "A", "type": "verse", "bars": 4, "loop_variant": "verse"},
            {"name": "B", "type": "hook", "bars": 4, "loop_variant": "verse"},
            {"name": "C", "type": "outro", "bars": 4, "loop_variant": "verse"},
        ],
        "events": [{"type": "variation"} for _ in range(12)],
    }

    try:
        _validate_render_plan_quality(render_plan)
        assert False, "Expected repeated-loop guard to fail"
    except ValueError as exc:
        assert "exact same audio loop" in str(exc)


def test_apply_stem_primary_section_states_assigns_role_sets_by_section() -> None:
    sections = [
        {"name": "Intro", "type": "intro", "bars": 4},
        {"name": "Verse 1", "type": "verse", "bars": 8},
        {"name": "Verse 2", "type": "verse", "bars": 8},
        {"name": "Hook 1", "type": "hook", "bars": 8},
        {"name": "Hook 2", "type": "hook", "bars": 8},
        {"name": "Bridge", "type": "bridge", "bars": 4},
        {"name": "Outro", "type": "outro", "bars": 4},
    ]
    stem_metadata = {
        "enabled": True,
        "succeeded": True,
        "roles_detected": ["full_mix", "drums", "bass", "melody", "pads"],
    }

    updated = _apply_stem_primary_section_states(sections, stem_metadata)

    assert updated[0]["active_stem_roles"] == ["melody", "pads"]
    assert updated[1]["active_stem_roles"] == ["drums", "bass"]
    assert updated[2]["active_stem_roles"] == ["drums", "bass", "melody"]
    assert updated[3]["active_stem_roles"] == ["drums", "bass", "melody", "pads"]
    assert updated[4]["active_stem_roles"] == ["drums", "bass", "melody", "pads"]
    assert updated[5]["active_stem_roles"] == ["pads", "melody"]
    assert updated[6]["active_stem_roles"] == ["melody", "pads"]
    assert all("full_mix" not in section["active_stem_roles"] for section in updated)
    assert all(section["stem_primary"] is True for section in updated)


def test_build_pre_render_plan_marks_stem_primary_mode() -> None:
    producer_arrangement = {
        "total_bars": 16,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Intro", "type": "intro", "bar_start": 0, "bars": 4, "energy": 0.25, "instruments": ["melody"]},
            {"name": "Verse", "type": "verse", "bar_start": 4, "bars": 4, "energy": 0.55, "instruments": ["bass"]},
            {"name": "Hook", "type": "hook", "bar_start": 8, "bars": 4, "energy": 0.85, "instruments": ["melody"]},
            {"name": "Outro", "type": "outro", "bar_start": 12, "bars": 4, "energy": 0.35, "instruments": ["fx"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=999,
        bpm=128.0,
        target_seconds=32,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={
            "enabled": True,
            "succeeded": True,
            "roles_detected": ["full_mix", "drums", "bass", "melody", "pads"],
        },
        loop_variation_manifest=None,
    )

    assert render_plan["render_profile"]["stem_primary_mode"] is True
    assert render_plan["sections"][0]["active_stem_roles"] == ["melody", "pads"]
    assert render_plan["sections"][1]["active_stem_roles"] == ["drums", "bass"]


def test_build_section_audio_from_stems_applies_headroom() -> None:
    stems = {
        "drums": Sine(80).to_audio_segment(duration=1000).apply_gain(-1),
        "bass": Sine(120).to_audio_segment(duration=1000).apply_gain(-1),
        "melody": Sine(440).to_audio_segment(duration=1000).apply_gain(-1),
        "pads": Sine(660).to_audio_segment(duration=1000).apply_gain(-1),
    }

    section_audio = _build_section_audio_from_stems(
        stems=stems,
        section_bars=1,
        bar_duration_ms=1000,
        section_idx=0,
    )

    assert section_audio.max_dBFS <= -5.5


def test_apply_stem_primary_section_states_marks_hook_evolution_stages() -> None:
    sections = [
        {"name": "Hook 1", "type": "hook", "bars": 8},
        {"name": "Hook 2", "type": "hook", "bars": 8},
        {"name": "Hook 3", "type": "hook", "bars": 8},
    ]
    stem_metadata = {
        "enabled": True,
        "succeeded": True,
        "roles_detected": ["drums", "bass", "melody", "harmony", "fx"],
    }

    updated = _apply_stem_primary_section_states(sections, stem_metadata)

    assert updated[0]["hook_evolution"]["stage"] == "hook1"
    assert updated[1]["hook_evolution"]["stage"] == "hook2"
    assert updated[2]["hook_evolution"]["stage"] == "hook3"
    assert updated[0]["hook_evolution"]["density"] < updated[1]["hook_evolution"]["density"]
    assert updated[1]["hook_evolution"]["density"] <= updated[2]["hook_evolution"]["density"]


def test_render_producer_arrangement_prefers_stems_over_loop_variations(monkeypatch) -> None:
    producer_arrangement = {
        "sections": [
            {
                "name": "Hook",
                "type": "hook",
                "bar_start": 0,
                "bars": 2,
                "energy": 0.9,
                "instruments": ["drums", "bass", "melody"],
                "loop_variant": "hook",
            }
        ],
        "tracks": [],
        "transitions": [],
        "energy_curve": [],
        "total_bars": 2,
    }

    monkeypatch.setattr(
        "app.services.arrangement_jobs._build_section_audio_from_stems",
        lambda **_: AudioSegment.silent(duration=2000),
    )
    monkeypatch.setattr(
        "app.services.arrangement_jobs._repeat_to_duration",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("loop variations should not be used when stems are present")),
    )

    arranged, _timeline = _render_producer_arrangement(
        loop_audio=AudioSegment.silent(duration=1000),
        producer_arrangement=producer_arrangement,
        bpm=120.0,
        stems={
            "drums": AudioSegment.silent(duration=1000),
            "bass": AudioSegment.silent(duration=1000),
            "melody": AudioSegment.silent(duration=1000),
        },
        loop_variations={"hook": AudioSegment.silent(duration=1000)},
    )

    assert len(arranged) > 0


def test_render_producer_arrangement_falls_back_to_loop_variations_without_stems(monkeypatch) -> None:
    producer_arrangement = {
        "sections": [
            {
                "name": "Verse",
                "type": "verse",
                "bar_start": 0,
                "bars": 2,
                "energy": 0.6,
                "instruments": ["drums", "bass"],
                "loop_variant": "verse",
            }
        ],
        "tracks": [],
        "transitions": [],
        "energy_curve": [],
        "total_bars": 2,
    }

    monkeypatch.setattr(
        "app.services.arrangement_jobs._build_varied_section_audio",
        lambda **_: (_ for _ in ()).throw(AssertionError("stereo fallback should not run when loop variation exists")),
    )

    arranged, _timeline = _render_producer_arrangement(
        loop_audio=AudioSegment.silent(duration=1000),
        producer_arrangement=producer_arrangement,
        bpm=120.0,
        stems=None,
        loop_variations={"verse": AudioSegment.silent(duration=1000)},
    )

    assert len(arranged) > 0


def test_build_pre_render_plan_adds_transition_boundaries_for_verse_to_hook() -> None:
    producer_arrangement = {
        "total_bars": 16,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.6, "instruments": ["kick", "bass"]},
            {"name": "Hook", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.95, "instruments": ["kick", "snare", "bass", "melody"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=7,
        bpm=120.0,
        target_seconds=32,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={"enabled": True, "succeeded": True, "roles_detected": ["drums", "bass", "melody", "fx"]},
        loop_variation_manifest=None,
    )

    boundary = render_plan["section_boundaries"][0]
    assert boundary["boundary"] == "verse_to_hook"
    assert "pre_hook_silence_drop" in boundary["events"]
    assert "crash_hit" in boundary["events"]
    assert any(event["type"] in {"drum_fill", "snare_pickup"} for event in render_plan["events"])


def test_final_hook_gets_stronger_transition_than_first_hook() -> None:
    producer_arrangement = {
        "total_bars": 40,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Verse 1", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.55, "instruments": ["kick", "bass"]},
            {"name": "Hook 1", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.85, "instruments": ["kick", "snare", "bass", "melody"]},
            {"name": "Bridge", "type": "bridge", "bar_start": 16, "bars": 8, "energy": 0.5, "instruments": ["bass", "melody"]},
            {"name": "Final Hook", "type": "hook", "bar_start": 24, "bars": 8, "energy": 1.0, "instruments": ["kick", "snare", "bass", "melody", "fx"]},
            {"name": "Outro", "type": "outro", "bar_start": 32, "bars": 8, "energy": 0.35, "instruments": ["melody"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=8,
        bpm=120.0,
        target_seconds=80,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={"enabled": True, "succeeded": True, "roles_detected": ["drums", "bass", "melody", "fx"]},
        loop_variation_manifest=None,
    )

    boundaries = {item["boundary"]: item for item in render_plan["section_boundaries"]}
    first = boundaries["verse_to_hook"]
    final = boundaries["bridge_to_hook"]

    assert len(final["events"]) > len(first["events"])
    assert "riser_fx" in final["events"]
    assert "reverse_cymbal" in final["events"]


def test_bridge_and_outro_receive_strip_transitions() -> None:
    producer_arrangement = {
        "total_bars": 24,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.6, "instruments": ["kick", "bass"]},
            {"name": "Bridge", "type": "bridge", "bar_start": 8, "bars": 8, "energy": 0.45, "instruments": ["melody"]},
            {"name": "Outro", "type": "outro", "bar_start": 16, "bars": 8, "energy": 0.25, "instruments": ["melody"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=9,
        bpm=120.0,
        target_seconds=48,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={"enabled": False, "succeeded": False},
        loop_variation_manifest=None,
    )

    boundaries = {item["boundary"]: item for item in render_plan["section_boundaries"]}
    assert "bridge_strip" in boundaries["verse_to_bridge"]["events"]
    assert "outro_strip" in boundaries["bridge_to_outro"]["events"]


def test_runtime_applies_transition_events_and_exposes_them_in_timeline() -> None:
    tone = Sine(220).to_audio_segment(duration=8000).set_channels(2) - 8
    producer_arrangement = {
        "sections": [
            {
                "name": "Verse",
                "type": "verse",
                "bar_start": 0,
                "bars": 2,
                "energy": 0.55,
                "instruments": ["drums", "bass"],
                "boundary_events": [
                    {"type": "pre_hook_silence_drop", "bar": 1, "placement": "end_of_section", "intensity": 0.9, "params": {"stems_exist": False}},
                ],
            },
            {
                "name": "Hook",
                "type": "hook",
                "bar_start": 2,
                "bars": 2,
                "energy": 0.95,
                "instruments": ["drums", "bass", "melody"],
                "boundary_events": [
                    {"type": "crash_hit", "bar": 2, "placement": "on_downbeat", "intensity": 0.9, "params": {"stems_exist": False}},
                ],
            },
        ],
        "tracks": [],
        "transitions": [],
        "energy_curve": [],
        "total_bars": 4,
        "section_boundaries": [
            {"boundary": "verse_to_hook", "events": ["pre_hook_silence_drop", "crash_hit"]},
        ],
    }

    arranged, timeline_json = _render_producer_arrangement(
        loop_audio=tone,
        producer_arrangement=producer_arrangement,
        bpm=120.0,
        stems=None,
        loop_variations=None,
    )

    payload = json.loads(timeline_json)
    assert payload["section_boundaries"][0]["boundary"] == "verse_to_hook"
    assert payload["sections"][0]["boundary_events"][0]["type"] == "pre_hook_silence_drop"
    assert payload["sections"][1]["boundary_events"][0]["type"] == "crash_hit"

    verse_tail = arranged[3000:3950]
    hook_head = arranged[5000:5500]
    assert verse_tail.rms < tone[3000:3950].rms
    assert hook_head.rms >= tone[0:500].rms
