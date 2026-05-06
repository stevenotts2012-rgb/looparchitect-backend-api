from app.services.arrangement_jobs import _build_render_spec_summary


def test_render_spec_summary_emits_producer_metrics():
    sections = [
        {
            "name": "hook_1",
            "type": "hook",
            "runtime_active_stems": ["drums", "bass", "melody"],
            "phrase_plan_used": True,
            "energy_level": 0.7,
            "hook_evolution": {"stage": "hook_1"},
            "applied_events": ["transition:riser", "delay_throw"],
            "boundary_events": [{"type": "transition:riser"}],
        },
        {
            "name": "hook_2",
            "type": "hook",
            "runtime_active_stems": ["drums", "bass", "melody", "fx"],
            "phrase_plan_used": True,
            "energy_level": 0.9,
            "hook_evolution": {"stage": "hook_2"},
            "applied_events": ["transition:downlifter", "silence_window"],
            "boundary_events": [{"type": "transition:downlifter"}],
        },
    ]

    summary = _build_render_spec_summary(sections)

    assert summary["phrase_split_count"] == 2
    assert summary["hook_escalation_applied"] is True
    assert summary["transition_overlap_rendered"] is True
    assert summary["variation_uniqueness_score"] > 0
    assert summary["final_producer_score"] > 0
    assert summary["producer_memory_state"]["unique_render_signature_count"] == 2


def test_render_spec_summary_detects_static_sections():
    sections = [
        {
            "name": "verse_1",
            "type": "verse",
            "runtime_active_stems": ["drums", "bass"],
            "energy_level": 0.5,
            "applied_events": [],
            "boundary_events": [],
        },
        {
            "name": "verse_2",
            "type": "verse",
            "runtime_active_stems": ["drums", "bass"],
            "energy_level": 0.5,
            "applied_events": [],
            "boundary_events": [],
        },
    ]

    summary = _build_render_spec_summary(sections)

    assert summary["section_similarity_score"] >= 0.4
    assert summary["event_repetition_score"] >= 0.9
