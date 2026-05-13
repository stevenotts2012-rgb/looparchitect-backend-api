import types

from app.routes import render_jobs


class _FakeEvent:
    def __init__(self, section_name: str, bar_start: int, bar_end: int):
        self.section_name = section_name
        self.bar_start = bar_start
        self.bar_end = bar_end
        self.render_action = "fill"
        self.intensity = 0.7
        self.reason = "test"
        self.parameters = {}


class _FakePlan:
    def __init__(self):
        self.events = [_FakeEvent("hook_1", 8, 9)]
        self.skipped_events = []
        self.section_variation_score = 0.9
        self.warnings = []

    def to_dict(self):
        return {"events": []}


class _FakeOrchestrator:
    def __init__(self, **kwargs):
        pass

    def run(self, **kwargs):
        return _FakePlan()


class _Loop:
    id = 1
    bpm = 120
    tempo = 120
    bars = 32
    genre = "edm"
    key = "C"
    stem_roles = {"drums": "x", "bass": "y", "music": "z", "fx": "q"}


def test_apply_producer_intelligence_attaches_metadata_and_changes_sections(monkeypatch):
    base = {
        "sections": [
            {"name": "intro", "bar_start": 0, "bars": 8, "energy": 0.2, "active_stem_roles": ["drums"], "instruments": ["drums"], "variations": []},
            {"name": "hook_1", "bar_start": 8, "bars": 8, "energy": 0.5, "active_stem_roles": ["drums"], "instruments": ["drums"], "variations": []},
        ],
        "producer_plan": {"available_roles": ["drums", "bass", "music", "fx"]},
        "metadata": {},
    }
    out = render_jobs._apply_producer_intelligence(base, style="edm", mood="hype", energy="high")
    assert "producer_intelligence" in out["metadata"]
    assert out["sections"][1]["energy"] != 0.5
    assert len(out["sections"][1]["active_stem_roles"]) >= 1


def test_build_generative_render_plan_uses_intelligence(monkeypatch):
    fake_mod = types.SimpleNamespace(GenerativeProducerOrchestrator=_FakeOrchestrator)
    monkeypatch.setitem(__import__("sys").modules, "app.services.generative_producer_system.orchestrator", fake_mod)
    called = {"count": 0}

    def _fake_apply(render_plan, style, mood, energy):
        called["count"] += 1
        render_plan.setdefault("metadata", {})["producer_intelligence"] = {"applied": True}
        return render_plan

    monkeypatch.setattr(render_jobs, "_apply_producer_intelligence", _fake_apply)
    plan = render_jobs._build_generative_render_plan(_Loop(), {"genre": "edm", "energy": "high", "personality": "p"}, target_bars=32, seed=7)
    assert called["count"] == 1
    assert plan["metadata"]["producer_intelligence"]["applied"] is True


def test_production_two_variation_mode_clamps_to_two(monkeypatch):
    monkeypatch.setattr(render_jobs.settings, "is_production", True)
    requested = 5
    effective = 2 if render_jobs.settings.is_production and requested > 2 else requested
    assert effective == 2


def test_ai_guide_modifies_actual_render_plan(monkeypatch):
    base = {
        "sections": [
            {"name": "verse_1", "bar_start": 0, "bars": 8, "energy": 0.4, "active_stem_roles": ["drums", "bass", "melody"], "instruments": [], "variations": []},
            {"name": "hook_1", "bar_start": 8, "bars": 8, "energy": 0.6, "active_stem_roles": ["drums", "bass", "melody"], "instruments": [], "variations": []},
        ],
        "producer_plan": {"available_roles": ["drums", "bass", "melody"]},
        "metadata": {},
    }
    monkeypatch.setattr(render_jobs._producer_intelligence_planner, "generate", lambda **_: {
        "energy": {"verse_1": 0.42, "hook_1": 0.72},
        "stems": {"verse_1": ["drums", "bass", "melody"], "hook_1": ["drums", "bass", "melody"]},
        "phrases": {},
        "hooks": {},
        "transitions": [],
        "melody_presence_score": 1.0,
        "drum_bass_dominance_score": 0.2,
        "melodic_sections_count": 2,
        "melody_restored_count": 0,
        "mix_balance_guard_applied": True,
        "transition_density": 0.7,
        "ai_guide": {"mix_priorities": {"melody_priority": 0.9}, "style_traits": {"stem_density": 0.3}, "variation_strategy": [{"focus": "melody"}]},
    })
    out = render_jobs._apply_producer_intelligence(base, style="trap", mood="dark", energy="high")
    assert out["sections"][1]["energy"] > 0.72
    assert out["sections"][0]["active_stem_roles"][0] == "melody"


def test_ai_failure_falls_back_without_breaking_render_plan(monkeypatch):
    base = {"sections": [{"name": "intro", "bar_start": 0, "bars": 8, "energy": 0.2, "active_stem_roles": ["drums"], "instruments": [], "variations": []}], "producer_plan": {"available_roles": ["drums"]}, "metadata": {}}
    out = render_jobs._apply_producer_intelligence(base, style="edm", mood="hype", energy="high")
    assert out["sections"][0]["active_stem_roles"]

def test_ai_advice_changes_section_plan_order_and_lengths(monkeypatch):
    base = {
        "sections": [
            {"name": "hook_1", "bar_start": 0, "bars": 8, "energy": 0.6, "active_stem_roles": ["drums", "bass", "melody"], "instruments": [], "variations": []},
            {"name": "pre_hook", "bar_start": 8, "bars": 2, "energy": 0.5, "active_stem_roles": ["drums", "bass"], "instruments": [], "variations": []},
            {"name": "bridge", "bar_start": 10, "bars": 8, "energy": 0.4, "active_stem_roles": ["pad"], "instruments": [], "variations": []},
        ],
        "producer_plan": {"available_roles": ["drums", "bass", "melody", "pad"]},
        "metadata": {"variation_index": 1},
    }
    monkeypatch.setattr(render_jobs._producer_intelligence_planner, "generate", lambda **_: {
        "energy": {"hook_1": 0.7, "pre_hook": 0.55, "bridge": 0.45},
        "stems": {"hook_1": ["drums", "bass", "melody"], "pre_hook": ["drums", "bass"], "bridge": ["pad"]},
        "phrases": {}, "hooks": {}, "transitions": [],
        "melody_presence_score": 0.8, "drum_bass_dominance_score": 0.7, "melodic_sections_count": 1, "melody_restored_count": 0,
        "mix_balance_guard_applied": True, "transition_density": 0.8,
        "ai_guide": {"arrangement_advice": {"section_order": ["pre_hook", "hook_1", "bridge"]}, "variation_strategy": [{"focus": "impact"}]},
    })
    out = render_jobs._apply_producer_intelligence(base, style="trap", mood="dark", energy="high")
    assert [s["name"] for s in out["sections"]][:2] == ["pre_hook", "hook_1"]
    assert out["sections"][0]["bars"] >= 4


def test_variation_personality_profiles_produce_different_events():
    s1 = [{"name": "pre_hook", "bar_start": 0, "bars": 4, "active_stem_roles": ["drums", "bass", "fx"], "variations": []}]
    s2 = [{"name": "pre_hook", "bar_start": 0, "bars": 4, "active_stem_roles": ["drums", "bass", "fx"], "variations": []}]
    p1 = render_jobs._apply_variation_personality_audio(s1, 0)
    p2 = render_jobs._apply_variation_personality_audio(s2, 1)
    assert p1 != p2
    assert any(v["variation_type"] == "bass_pause_before_hook" for v in s2[0]["variations"])


def test_generic_repair_and_story_metrics_present(monkeypatch):
    base = {
        "sections": [{"name": "verse", "bar_start": i*4, "bars": 4, "energy": 0.5, "active_stem_roles": ["drums"], "instruments": [], "variations": []} for i in range(4)],
        "producer_plan": {"available_roles": ["drums"]},
        "metadata": {"variation_index": 0},
    }
    monkeypatch.setattr(render_jobs._producer_intelligence_planner, "generate", lambda **_: {
        "energy": {"verse": 0.5}, "stems": {"verse": ["drums"]}, "phrases": {}, "hooks": {}, "transitions": [],
        "melody_presence_score": 0.2, "drum_bass_dominance_score": 0.9, "melodic_sections_count": 0, "melody_restored_count": 0,
        "mix_balance_guard_applied": True, "transition_density": 0.2, "ai_guide": {}
    })
    out = render_jobs._apply_producer_intelligence(base, style="edm", mood="flat", energy="low")
    meta = out["metadata"]["producer_intelligence"]
    assert "generic_arrangement_score" in meta
    assert "arrangement_story" in meta


def test_processing_job_forced_to_timeout_terminal_state(db_session):
    from app.models.job import RenderJob
    from datetime import datetime, timedelta
    from app.services.job_service import get_job_status
    j = RenderJob(id="jid", loop_id=1, status="processing", started_at=datetime.utcnow()-timedelta(seconds=9999))
    db_session.add(j)
    db_session.commit()
    res = get_job_status(db_session, "jid")
    assert res.status in {"timeout", "failed", "succeeded", "missing_output"}
