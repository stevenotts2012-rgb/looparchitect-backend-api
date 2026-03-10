from app.services.arrangement_jobs import _build_pre_render_plan



def _evolution_plan() -> dict:
    producer_arrangement = {
        "tempo": 96.0,
        "key": "C",
        "total_bars": 64,
        "sections": [
            {"name": "Intro", "type": "intro", "bar_start": 0, "bars": 8, "energy": 0.4, "instruments": ["pad", "melody", "fx"]},
            {"name": "Verse 1", "type": "verse", "bar_start": 8, "bars": 8, "energy": 0.58, "instruments": ["kick", "snare", "bass", "melody"]},
            {"name": "Pre-Hook", "type": "verse", "bar_start": 16, "bars": 8, "energy": 0.62, "instruments": ["kick", "snare", "bass", "pad"]},
            {"name": "Hook 1", "type": "hook", "bar_start": 24, "bars": 8, "energy": 0.82, "instruments": ["kick", "snare", "hats", "bass", "melody"]},
            {"name": "Verse 2", "type": "verse", "bar_start": 32, "bars": 8, "energy": 0.6, "instruments": ["kick", "snare", "bass", "pad"]},
            {"name": "Hook 2", "type": "hook", "bar_start": 40, "bars": 8, "energy": 0.86, "instruments": ["kick", "snare", "hats", "bass", "melody", "fx"]},
            {"name": "Bridge", "type": "bridge", "bar_start": 48, "bars": 8, "energy": 0.48, "instruments": ["pad", "melody", "bass"]},
            {"name": "Hook 3", "type": "hook", "bar_start": 56, "bars": 8, "energy": 0.9, "instruments": ["kick", "snare", "hats", "bass", "melody", "fx", "strings"]},
        ],
        "tracks": [],
    }

    return _build_pre_render_plan(
        arrangement_id=1001,
        bpm=96.0,
        target_seconds=160,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={"enabled": True, "succeeded": True},
        loop_variation_manifest={"active": True, "count": 4, "names": ["intro", "verse", "hook", "bridge"], "files": {}},
    )



def test_hook2_is_bigger_than_hook1_and_hook3_is_biggest():
    plan = _evolution_plan()
    hook_sections = [s for s in plan["sections"] if str(s.get("type", "")).lower() == "hook"]
    assert len(hook_sections) == 3

    hook_energies = [float(s.get("energy", 0.0) or 0.0) for s in hook_sections]
    assert hook_energies[1] > hook_energies[0]
    assert hook_energies[2] > hook_energies[1]

    hook_expansion_events = [
        event for event in plan.get("events", [])
        if event.get("type") == "hook_expansion"
    ]
    expansion_intensities = [float(e.get("intensity", 0.0) or 0.0) for e in hook_expansion_events]
    assert len(expansion_intensities) >= 3
    assert max(expansion_intensities) == expansion_intensities[-1]



def test_verse_has_less_active_layers_than_hook():
    plan = _evolution_plan()
    verse_targets = [int(s.get("active_layers_target", 0) or 0) for s in plan["sections"] if s.get("type") == "verse"]
    hook_targets = [int(s.get("active_layers_target", 0) or 0) for s in plan["sections"] if s.get("type") == "hook"]

    assert verse_targets
    assert hook_targets
    assert max(verse_targets) < min(hook_targets)



def test_bridge_contrasts_with_hook_and_resets_energy():
    plan = _evolution_plan()
    bridge = next(s for s in plan["sections"] if s.get("type") == "bridge")
    hook_sections = [s for s in plan["sections"] if s.get("type") == "hook"]

    assert float(bridge.get("energy", 1.0) or 1.0) < min(float(h.get("energy", 0.0) or 0.0) for h in hook_sections)

    bridge_events = [
        event.get("type") for event in plan.get("events", [])
        if event.get("section_type") == "bridge"
    ]
    assert "bridge_strip" in bridge_events
    assert "stem_filter" in bridge_events



def test_meaningful_changes_exist_every_4_to_8_bars():
    plan = _evolution_plan()
    meaningful = {
        "texture_lift",
        "fill_event",
        "hook_expansion",
        "pre_hook_mute",
        "silence_drop",
        "bridge_strip",
        "outro_strip",
        "call_response_variation",
    }
    bars = sorted({int(e.get("bar", 0) or 0) for e in plan.get("events", []) if e.get("type") in meaningful})
    assert bars

    all_points = [0] + bars + [int(plan.get("total_bars", 64) or 64)]
    max_gap = max(all_points[i + 1] - all_points[i] for i in range(len(all_points) - 1))
    assert max_gap <= 8



def test_repeated_loop_behavior_reduced_with_scorecard_signal():
    plan = _evolution_plan()
    scorecard = plan.get("producer_scorecard") or {}
    metrics = scorecard.get("metrics") or {}

    assert scorecard.get("total", 0) >= 75
    assert metrics.get("repetition_avoidance", 0) >= 70
    assert metrics.get("movement_4_8", 0) >= 70
    assert scorecard.get("verdict") in {"pass", "warn"}
