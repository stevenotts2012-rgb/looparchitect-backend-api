from app.services import render_executor


def _plan(v=0):
    return {
        "sections": [
            {"name": "verse", "bar_start": 0, "bars": 8, "active_stem_roles": ["drums", "bass", "fx"], "variations": []},
            {"name": "pre_hook", "bar_start": 8, "bars": 2, "active_stem_roles": ["drums", "bass"], "variations": []},
            {"name": "hook", "bar_start": 10, "bars": 8, "active_stem_roles": ["drums", "bass", "melody"], "variations": []},
            {"name": "bridge", "bar_start": 18, "bars": 8, "active_stem_roles": ["pad"], "variations": []},
            {"name": "outro", "bar_start": 26, "bars": 6, "active_stem_roles": ["pad"], "variations": []},
        ],
        "metadata": {"variation_index": v},
    }


def test_structure_personality_and_metrics_run_when_provider_disabled(monkeypatch):
    monkeypatch.setattr(render_executor.settings, "feature_ai_producer_assist", False)
    out = render_executor._apply_active_path_ai_guide(_plan(0))
    assert out["metadata"].get("producer_story")
    for k in ("generic_arrangement_score", "hook_payoff_score", "section_contrast_score", "phrase_evolution_score", "transition_story_score"):
        assert k in out["metadata"]


def test_variation_0_and_1_have_different_events(monkeypatch):
    monkeypatch.setattr(render_executor.settings, "feature_ai_producer_assist", False)
    a = render_executor._apply_active_path_ai_guide(_plan(0))
    b = render_executor._apply_active_path_ai_guide(_plan(1))
    va = {v["variation_type"] for s in a["sections"] for v in s.get("variations", [])}
    vb = {v["variation_type"] for s in b["sections"] for v in s.get("variations", [])}
    assert "clean_main_audio_profile" in va
    assert "dark_heavier_audio_profile" in vb
    assert va != vb


def test_local_advisor_enabled_not_disabled_fallback(monkeypatch, caplog):
    monkeypatch.setattr(render_executor.settings, "feature_ai_producer_assist", True)
    monkeypatch.setenv("AI_PRODUCER_GUIDE_ENABLED", "false")
    render_executor._apply_active_path_ai_guide(_plan(0))
    assert "AI_PRODUCER_GUIDE_FALLBACK_USED reason=disabled" not in caplog.text
    assert "AI_PRODUCER_GUIDE_LOCAL_ADVISOR_USED" in caplog.text
    assert "AI_PRODUCER_GUIDE_APPLIED" in caplog.text
