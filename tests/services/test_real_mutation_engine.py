from app.services.arrangement_jobs import _apply_producer_taste_decisions, _build_render_spec_summary


def _var_types(section):
    return {str(v.get('variation_type') or v.get('type') or '') for v in section.get('variations', [])}


def test_mutation_events_and_phrase_plan_for_long_sections():
    verse = {"type": "verse", "bars": 8, "bar_start": 0, "active_stem_roles": ["drums", "bass", "melody"]}
    pre = {"type": "pre_hook", "bars": 8, "bar_start": 8, "active_stem_roles": ["drums", "bass", "melody"]}
    hook = {"type": "hook", "bars": 8, "bar_start": 16, "active_stem_roles": ["drums", "bass", "melody"]}
    bridge = {"type": "bridge", "bars": 8, "bar_start": 24, "active_stem_roles": ["drums", "bass", "pads"]}

    _apply_producer_taste_decisions(verse, prev_section=None, next_section=pre, variation_index=1)
    _apply_producer_taste_decisions(pre, prev_section=verse, next_section=hook, variation_index=1)
    _apply_producer_taste_decisions(hook, prev_section=pre, next_section=bridge, variation_index=1)
    _apply_producer_taste_decisions(bridge, prev_section=hook, next_section=hook, variation_index=1)

    assert verse.get("phrase_plan") is not None
    assert pre.get("phrase_plan") is not None
    assert hook.get("phrase_plan") is not None
    assert bridge.get("phrase_plan") is not None
    assert verse["phrase_plan"]["split_bar"] == 4
    assert bridge["phrase_plan"]["split_bar"] == 4
    assert set(bridge["phrase_plan"]["first_phrase_roles"]).isdisjoint({"drums", "bass"})

    assert "hat_density_variation" in _var_types(verse)
    assert "pre_hook_fill" in _var_types(pre)
    assert "bass_pause" in _var_types(pre)
    assert "melody_octave_response" in _var_types(hook)
    assert "bridge_drum_dropout" in _var_types(bridge)
    assert "bridge_bass_dropout" in _var_types(bridge)


def test_variation_personalities_diverge_in_mutation_maps():
    base = {"type": "pre_hook", "bars": 8, "bar_start": 0, "active_stem_roles": ["drums", "bass", "melody"]}
    s1 = dict(base)
    s2 = dict(base)
    s3 = dict(base)
    _apply_producer_taste_decisions(s1, prev_section=None, next_section={"type": "hook"}, variation_index=1)
    _apply_producer_taste_decisions(s2, prev_section=None, next_section={"type": "hook"}, variation_index=2)
    _apply_producer_taste_decisions(s3, prev_section=None, next_section={"type": "hook"}, variation_index=3)

    v1, v2, v3 = _var_types(s1), _var_types(s2), _var_types(s3)
    assert "restrained_mutation_profile" in v1
    assert "dark_filtered_phrase" in v2
    assert "phrase_chop_variation" in v3
    assert v1 != v2 != v3


def test_render_spec_phrase_evolution_and_hook_difference_and_bridge_dropout():
    timeline = [
        {"name": "Verse", "type": "verse", "runtime_active_stems": ["drums", "bass"], "phrase_plan_used": True,
         "hook_evolution": {}, "applied_events": ["drum_density_down", "melody_filter_phrase"], "boundary_events": [] ,"energy_level":0.52},
        {"name": "Hook 1", "type": "hook", "runtime_active_stems": ["drums", "bass", "melody"], "phrase_plan_used": True,
         "hook_evolution": {"stage": "hook_1"}, "applied_events": ["drum_density_up", "melody_octave_response"], "boundary_events": [],"energy_level":0.78},
        {"name": "Bridge", "type": "bridge", "runtime_active_stems": ["pads"], "phrase_plan_used": True,
         "hook_evolution": {}, "applied_events": ["bridge_drum_dropout", "bridge_bass_dropout"], "boundary_events": [],"energy_level":0.33},
        {"name": "Hook 2", "type": "hook", "runtime_active_stems": ["drums", "bass", "melody", "perc"], "phrase_plan_used": True,
         "hook_evolution": {"stage": "hook_2"}, "applied_events": ["final_hook_drum_lift", "final_hook_bass_lift", "melody_octave_response"], "boundary_events": [],"energy_level":0.9},
    ]
    summary = _build_render_spec_summary(timeline)
    assert summary["phrase_evolution_score"] > 0.35
    assert set(summary["hook_stages"]) == {"hook_1", "hook_2"}
    assert any("bridge_drum_dropout" in e for e in summary["actual_transition_events_used"])
    assert any("bridge_bass_dropout" in e for e in summary["actual_transition_events_used"])


def test_hook_2_differs_from_hook_1_and_transition_count_restrained():
    hook1 = {"type": "hook", "bars": 8, "bar_start": 16, "active_stem_roles": ["drums", "bass", "melody"]}
    hook2 = {"type": "hook", "bars": 8, "bar_start": 40, "active_stem_roles": ["drums", "bass", "melody"], "variations": [{"variation_type": "preexisting_hook_shape", "bar": 40, "intensity": 0.7}]}
    _apply_producer_taste_decisions(hook1, prev_section={"type": "pre_hook"}, next_section={"type": "verse"}, variation_index=1)
    _apply_producer_taste_decisions(hook2, prev_section={"type": "bridge"}, next_section={"type": "outro"}, variation_index=1)

    h1 = _var_types(hook1)
    h2 = _var_types(hook2)
    assert "final_hook_drum_lift" not in h1
    assert "final_hook_drum_lift" in h2
    assert "final_hook_bass_lift" in h2
    assert h1 != h2

    # restrained boundary count (no transition spam): we only add a compact set
    assert len(hook2.get("boundary_events") or []) <= 6


def test_phrase_plan_used_and_phrase_evolution_for_all_8bar_sections():
    sections = [
        {"type": "verse", "bars": 8, "bar_start": 0, "active_stem_roles": ["drums", "bass", "melody"]},
        {"type": "pre_hook", "bars": 8, "bar_start": 8, "active_stem_roles": ["drums", "bass", "melody"]},
        {"type": "hook", "bars": 8, "bar_start": 16, "active_stem_roles": ["drums", "bass", "melody"]},
        {"type": "bridge", "bars": 8, "bar_start": 24, "active_stem_roles": ["drums", "bass", "pads"]},
    ]
    for i, section in enumerate(sections):
        prev_section = sections[i - 1] if i > 0 else None
        next_section = sections[i + 1] if i + 1 < len(sections) else None
        _apply_producer_taste_decisions(section, prev_section=prev_section, next_section=next_section, variation_index=1)
        section["phrase_plan_used"] = bool(section.get("phrase_plan")) and int(section.get("bars", 0)) >= 8

    assert all(s.get("phrase_plan_used") for s in sections)
    summary = _build_render_spec_summary([
        {
            "name": s["type"],
            "type": s["type"],
            "runtime_active_stems": s.get("active_stem_roles", []),
            "phrase_plan_used": s["phrase_plan_used"],
            "hook_evolution": {"stage": "hook_1"} if s["type"] == "hook" else {},
            "applied_events": [v.get("variation_type") for v in s.get("variations", [])],
            "boundary_events": s.get("boundary_events", []),
            "energy_level": 0.7 if s["type"] == "hook" else 0.45,
        }
        for s in sections
    ] + [{
        "name": "hook_2", "type": "hook", "runtime_active_stems": ["drums", "bass", "melody", "perc"],
        "phrase_plan_used": True, "hook_evolution": {"stage": "hook_2"}, "applied_events": ["final_hook_drum_lift"],
        "boundary_events": [], "energy_level": 0.9,
    }])
    assert summary["phrase_evolution_score"] > 0.35
