from types import SimpleNamespace

from app.routes.render_jobs import _producer_plan_to_render_plan


def test_producer_events_convert_to_absolute_bars_across_sections():
    producer_plan = SimpleNamespace(
        events=[
            SimpleNamespace(
                section_name="verse",
                bar_start=1,
                bar_end=2,
                render_action="drum_fill",
                intensity=0.8,
                reason="Verse pickup",
                parameters={},
            ),
            SimpleNamespace(
                section_name="hook",
                bar_start=0,
                bar_end=2,
                render_action="add_impact",
                intensity=0.9,
                reason="Hook downbeat",
                parameters={},
            ),
        ],
        section_variation_score=0.67,
        warnings=[],
        to_dict=lambda: {"events": []},
    )

    section_templates = [
        {"name": "verse", "bar_start": 0, "bars": 8},
        {"name": "hook", "bar_start": 8, "bars": 8},
    ]

    render_plan = _producer_plan_to_render_plan(
        producer_plan=producer_plan,
        section_templates=section_templates,
        available_roles=["drums", "bass"],
        role_groups={"drums": ["drums"], "bass": ["bass"], "melody": [], "harmony": [], "fx": []},
        bpm=120.0,
        loop_id=123,
        genre="trap",
    )

    verse_variation = render_plan["sections"][0]["variations"][0]
    hook_variation = render_plan["sections"][1]["variations"][0]
    assert verse_variation["bar"] == 1
    assert hook_variation["bar"] == 8

    top_level_events = render_plan["events"]
    assert top_level_events[0]["bar"] == 1
    assert top_level_events[1]["bar"] == 8
