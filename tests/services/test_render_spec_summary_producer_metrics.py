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
    assert "HOOK_PAYOFF_SCORE" in summary
    assert "TRANSITION_SMOOTHNESS_SCORE" in summary
    assert "BRIDGE_CONTRAST_SCORE" in summary
    assert "PRODUCER_TASTE_SCORE" in summary


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


def test_hook_2_scores_bigger_than_hook_1_and_bridge_is_lower_but_not_dead():
    sections = [
        {"name": "verse_1", "type": "verse", "runtime_active_stems": ["drums", "bass"], "energy_level": 0.52, "applied_events": ["transition:reverse_tail"]},
        {"name": "hook_1", "type": "hook", "runtime_active_stems": ["drums", "bass", "melody"], "energy_level": 0.76, "hook_evolution": {"stage": "hook_1"}, "applied_events": ["transition:riser", "pre_hook_silence"]},
        {"name": "bridge", "type": "bridge", "runtime_active_stems": ["pad"], "energy_level": 0.34, "applied_events": ["delay_throw"]},
        {"name": "hook_2", "type": "hook", "runtime_active_stems": ["drums", "bass", "melody", "fx"], "energy_level": 0.91, "hook_evolution": {"stage": "hook_2"}, "applied_events": ["transition:riser", "transition:downlifter", "bass_pause", "silence_window"]},
    ]
    summary = _build_render_spec_summary(sections)
    assert summary["HOOK_PAYOFF_SCORE"] > 0.30
    assert summary["BRIDGE_CONTRAST_SCORE"] > 0.20
    assert summary["TRANSITION_SMOOTHNESS_SCORE"] > 0.20
    assert summary["DROP_INTELLIGENCE_APPLIED"] is True


def test_dynamic_arrangement_scores_higher_than_static_arrangement():
    static_sections = [
        {"name": "verse_1", "type": "verse", "runtime_active_stems": ["drums", "bass"], "energy_level": 0.5, "applied_events": []},
        {"name": "verse_2", "type": "verse", "runtime_active_stems": ["drums", "bass"], "energy_level": 0.5, "applied_events": []},
    ]
    dynamic_sections = [
        {"name": "verse_1", "type": "verse", "runtime_active_stems": ["drums", "bass"], "energy_level": 0.52, "applied_events": ["transition:reverse_tail"]},
        {"name": "hook_1", "type": "hook", "runtime_active_stems": ["drums", "bass", "melody"], "energy_level": 0.80, "hook_evolution": {"stage": "hook_1"}, "applied_events": ["pre_hook_silence", "transition:riser"]},
        {"name": "hook_2", "type": "hook", "runtime_active_stems": ["drums", "bass", "melody", "fx"], "energy_level": 0.90, "hook_evolution": {"stage": "hook_2"}, "applied_events": ["transition:downlifter", "bass_pause", "silence_window"]},
    ]

    static_summary = _build_render_spec_summary(static_sections)
    dynamic_summary = _build_render_spec_summary(dynamic_sections)

    assert dynamic_summary["final_producer_score"] > static_summary["final_producer_score"]
    assert len(dynamic_summary["VARIATION_PERSONALITY_ASSIGNED"]) == 3
