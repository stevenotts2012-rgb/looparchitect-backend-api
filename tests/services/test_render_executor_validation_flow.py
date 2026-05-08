import json

from pydub import AudioSegment

from app.services import render_executor


class _MasteringResult:
    def __init__(self, audio):
        self.audio = audio
        self.applied = False
        self.profile = "test"
        self.peak_dbfs_before = -10.0
        self.peak_dbfs_after = -10.0


def _minimal_timeline(sections):
    return json.dumps(
        {
            "sections": sections,
            "events": [],
            "render_spec_summary": {
                "variation_energy_curve": [0.1, 0.2],
                "phrase_split_count": 1,
                "transition_overlap_rendered_count": 1,
                "hook_escalation_applied": True,
                "variation_uniqueness_score": 0.9,
            },
        }
    )


def test_dynamic_validation_rejects_empty_timeline_boundary():
    render_observability = {"unique_render_signature_count": 2}

    try:
        render_executor._assert_dynamic_arrangement(
            timeline_json=json.dumps({"sections": [], "render_spec_summary": {}}),
            render_observability=render_observability,
            render_path_used="stem_render_executor",
        )
        assert False, "Expected RuntimeError for empty timeline"
    except RuntimeError as exc:
        assert str(exc) == "PRODUCER_TIMELINE_EMPTY_BEFORE_VALIDATION"


def test_render_from_plan_passes_post_render_timeline_and_observability(monkeypatch, tmp_path):
    observed = {}

    def _stub_render(*args, **kwargs):
        timeline = _minimal_timeline(
            [{"name": "intro", "type": "intro", "applied_events": ["event_a"]}]
        )
        return AudioSegment.silent(duration=50), timeline

    def _stub_mastering(audio, genre=None):
        return _MasteringResult(audio)

    def _stub_observability(**kwargs):
        timeline = json.loads(kwargs["timeline_json"])
        assert len(timeline.get("sections") or []) == 1
        return {
            "render_signatures": ["sig_a"],
            "unique_render_signature_count": 2,
            "planned_stem_map_by_section": ["a"],
            "actual_stem_map_by_section": ["a"],
            "render_path_used": kwargs["render_path_used"],
            "source_quality_mode_used": kwargs["source_quality_mode_used"],
            "fallback_triggered_count": 0,
            "phrase_split_count": 1,
            "mastering_applied": False,
        }

    def _capture_dynamic(**kwargs):
        observed["timeline"] = json.loads(kwargs["timeline_json"])
        observed["observability"] = kwargs["render_observability"]

    monkeypatch.setattr("app.services.arrangement_jobs._render_producer_arrangement", _stub_render)
    monkeypatch.setattr(render_executor, "apply_mastering", _stub_mastering)
    monkeypatch.setattr(render_executor, "_build_render_observability", _stub_observability)
    monkeypatch.setattr(render_executor, "_assert_producer_runtime_not_noop", lambda **kwargs: None)
    monkeypatch.setattr(render_executor, "_assert_dynamic_arrangement", _capture_dynamic)

    render_plan = {
        "bpm": 120,
        "key": "C",
        "sections": [{"name": "intro", "type": "intro", "bars": 4}],
        "events": [],
        "render_profile": {},
    }
    output = tmp_path / "out.wav"

    render_executor.render_from_plan(
        render_plan_json=render_plan,
        audio_source=AudioSegment.silent(duration=100),
        output_path=output,
        stems=None,
    )

    assert len(observed["timeline"].get("sections") or []) == 1
    assert observed["observability"]["unique_render_signature_count"] == 2
