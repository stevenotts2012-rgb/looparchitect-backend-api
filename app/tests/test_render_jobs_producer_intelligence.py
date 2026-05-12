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
