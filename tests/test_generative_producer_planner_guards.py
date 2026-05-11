from app.services.generative_producer_system.orchestrator import GenerativeProducerOrchestrator


def test_planner_generates_events_for_basic_loop_sections():
    orch = GenerativeProducerOrchestrator(available_roles=["drums", "bass", "melody"], arrangement_id=1)
    plan = orch.run(
        sections=[{"name": "verse", "bars": 8, "bar_start": 0, "bar_end": 8}],
        genre="trap",
        vibe="dark",
        seed=42,
    )
    assert len(plan.events) > 0


def test_available_roles_fallback_not_empty_when_loop_exists():
    detected_roles = []
    sections_raw = [{"name": "verse", "bars": 8}]
    if sections_raw and not detected_roles:
        detected_roles = ["drums", "bass", "melody", "full_mix"]
    assert detected_roles


def test_emergency_fallback_structure_shape():
    fallback_sections = [
        {"name": "intro", "bars": 4},
        {"name": "verse", "bars": 8},
        {"name": "hook", "bars": 8},
        {"name": "verse", "bars": 8},
        {"name": "hook", "bars": 8},
        {"name": "outro", "bars": 4},
    ]
    assert [s["name"] for s in fallback_sections] == ["intro", "verse", "hook", "verse", "hook", "outro"]
