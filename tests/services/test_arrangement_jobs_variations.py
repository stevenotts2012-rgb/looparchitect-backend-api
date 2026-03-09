from app.services.arrangement_jobs import _build_pre_render_plan, _validate_render_plan_quality


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
