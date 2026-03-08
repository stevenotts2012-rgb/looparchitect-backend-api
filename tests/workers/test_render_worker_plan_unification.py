import pytest

from app.workers import render_worker
from app.services import render_executor


def test_select_render_mode_prefers_render_plan():
    assert render_worker._select_render_mode(True) == "render_plan"


def test_select_render_mode_fallback_not_default(monkeypatch):
    monkeypatch.setattr(render_worker.settings, "dev_fallback_loop_only", False)
    monkeypatch.setattr(render_worker.settings, "environment", "development")

    with pytest.raises(ValueError, match="render_plan_json is required"):
        render_worker._select_render_mode(False)


def test_select_render_mode_allows_dev_fallback_only_when_enabled(monkeypatch):
    monkeypatch.setattr(render_worker.settings, "dev_fallback_loop_only", True)
    monkeypatch.setattr(render_worker.settings, "environment", "development")

    assert render_worker._select_render_mode(False) == "dev_fallback"


def test_render_executor_plan_conversion_applies_events_and_layering():
    render_plan = {
        "bpm": 140,
        "key": "C",
        "total_bars": 16,
        "render_profile": {"genre_profile": "trap"},
        "sections": [
            {
                "name": "Verse",
                "type": "verse",
                "bar_start": 0,
                "bars": 8,
                "energy": 0.5,
                "instruments": ["kick", "bass"],
            },
            {
                "name": "Hook",
                "type": "hook",
                "bar_start": 8,
                "bars": 8,
                "energy": 0.85,
                "instruments": ["kick", "snare", "bass", "melody", "hats"],
            },
        ],
        "events": [
            {"type": "variation", "bar": 2, "description": "drum fill in verse"},
            {"type": "beat_switch", "bar": 10, "description": "beat switch on hook"},
            {"type": "enter", "bar": 8, "description": "Melody enters"},
        ],
    }

    producer_payload, summary = render_executor._build_producer_arrangement_from_render_plan(
        render_plan=render_plan,
        fallback_bpm=120.0,
    )

    assert producer_payload["tempo"] == 140
    assert producer_payload["genre"] == "trap"
    assert len(producer_payload["sections"]) == 2

    # Events are present and applied as section variations
    verse = producer_payload["sections"][0]
    hook = producer_payload["sections"][1]
    assert len(verse["variations"]) == 1
    assert len(hook["variations"]) == 1
    assert verse["variations"][0]["variation_type"] == "variation"
    assert hook["variations"][0]["variation_type"] == "beat_switch"

    # Hook has more active layers than verse
    assert summary["layer_counts"]["hook"] > summary["layer_counts"]["verse"]

    # Summary has section/event counts and producer moves extracted
    assert summary["sections_count"] == 2
    assert summary["events_count"] == 3
    assert "beat_switch" in summary["producer_moves"]
