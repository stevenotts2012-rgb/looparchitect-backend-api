from app.services.musical_evolution.orchestrator import MusicalEvolutionOrchestrator


def _plan(v=0):
    return {
        "genre": "trap",
        "sections": [
            {"name": "verse", "bar_start": 0, "bars": 8, "energy": 0.5, "active_stem_roles": ["drums", "bass", "melody"], "variations": []},
            {"name": "pre_hook", "bar_start": 8, "bars": 4, "energy": 0.6, "active_stem_roles": ["drums", "bass", "melody"], "variations": []},
            {"name": "hook", "bar_start": 12, "bars": 8, "energy": 0.8, "active_stem_roles": ["drums", "bass", "melody"], "variations": []},
            {"name": "verse_2", "bar_start": 20, "bars": 8, "energy": 0.55, "active_stem_roles": ["drums", "bass", "melody"], "variations": []},
            {"name": "hook_2", "bar_start": 28, "bars": 8, "energy": 0.9, "active_stem_roles": ["drums", "bass", "melody"], "variations": []},
            {"name": "bridge", "bar_start": 36, "bars": 8, "energy": 0.4, "active_stem_roles": ["drums", "bass", "melody"], "variations": []},
        ],
        "metadata": {"variation_index": v},
    }


def test_musical_evolution_core_events_and_metadata():
    out, sections, meta, events = MusicalEvolutionOrchestrator().apply(_plan(0), variation_index=0)
    all_events = {v["variation_type"] for s in sections for v in s.get("variations", [])}
    assert "melody_hook_lift" in all_events
    assert "bass_pause_pre_hook" in all_events
    assert "drum_pre_hook_fill" in all_events
    assert "hook2_bigger_payoff" in all_events
    assert "melody_bridge_reset" in all_events
    assert "micro_timing_variation" in all_events
    assert out["metadata"].get("musical_evolution")
    assert "events_by_section" in meta


def test_variation_profiles_differ():
    _, s0, _, _ = MusicalEvolutionOrchestrator().apply(_plan(0), variation_index=0)
    _, s1, _, _ = MusicalEvolutionOrchestrator().apply(_plan(1), variation_index=1)
    i0 = [v["intensity"] for sec in s0 for v in sec.get("variations", []) if "bass_" in v["variation_type"] or "drum_" in v["variation_type"]]
    i1 = [v["intensity"] for sec in s1 for v in sec.get("variations", []) if "bass_" in v["variation_type"] or "drum_" in v["variation_type"]]
    assert sum(i1) > sum(i0)
