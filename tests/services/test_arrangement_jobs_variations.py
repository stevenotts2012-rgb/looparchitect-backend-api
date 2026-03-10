from app.services.arrangement_jobs import (
    _apply_stem_primary_section_states,
    _build_pre_render_plan,
    _render_producer_arrangement,
    _validate_render_plan_quality,
)
from pydub import AudioSegment


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
        "roles_detected": ["drums", "bass", "melody", "harmony", "fx"],
    }

    updated = _apply_stem_primary_section_states(sections, stem_metadata)

    assert updated[0]["active_stem_roles"] == ["melody", "harmony", "fx"]
    assert updated[1]["active_stem_roles"] == ["drums", "bass"]
    assert updated[2]["active_stem_roles"] == ["drums", "bass", "harmony"]
    assert updated[3]["active_stem_roles"] == ["drums", "bass", "melody", "harmony"]
    assert updated[4]["active_stem_roles"] == ["drums", "bass", "melody", "harmony", "fx"]
    assert updated[5]["active_stem_roles"] == ["harmony", "fx", "melody"]
    assert updated[6]["active_stem_roles"] == ["melody", "harmony", "fx"]
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
            "roles_detected": ["drums", "bass", "melody", "harmony", "fx"],
        },
        loop_variation_manifest=None,
    )

    assert render_plan["render_profile"]["stem_primary_mode"] is True
    assert render_plan["sections"][0]["active_stem_roles"] == ["melody", "harmony", "fx"]
    assert render_plan["sections"][1]["active_stem_roles"] == ["drums", "bass"]


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
