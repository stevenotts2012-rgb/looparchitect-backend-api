from app.services.transition_engine import build_transition_plan


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
