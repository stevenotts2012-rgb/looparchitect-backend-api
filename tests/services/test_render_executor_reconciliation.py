import json

from app.services.render_executor import (
    _build_producer_arrangement_from_render_plan,
    _enrich_timeline_with_producer_plan,
)


def test_section_reconciliation_populates_bridge_and_coverage():
    render_plan = {
        "sections": [
            {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8, "instruments": ["drums"]},
            {"name": "Bridge", "type": "bridge", "bar_start": 8, "bars": 8, "instruments": ["drums"]},
        ],
        "events": [
            {"type": "drum_fill", "bar": 1, "source": "producer_plan"},
            {"type": "mute_role", "bar": 9, "source": "producer_plan"},
            {"type": "delay_role", "bar": 12, "source": "producer_plan"},
        ],
        "producer_plan": {
            "events": [
                # section-relative bars as emitted by producer plan
                {"section_name": "verse", "bar_start": 1, "bar_end": 2, "render_action": "drum_fill"},
                {"section_name": "bridge", "bar_start": 1, "bar_end": 2, "render_action": "mute_role"},
                {"section_name": "bridge", "bar_start": 4, "bar_end": 5, "render_action": "delay_role"},
            ]
        },
    }
    producer_arrangement, _ = _build_producer_arrangement_from_render_plan(render_plan, fallback_bpm=120.0)
    timeline = {
        "sections": [
            {**producer_arrangement["sections"][0], "applied_events": ["drum_fill"]},
            {**producer_arrangement["sections"][1], "applied_events": ["mute_role", "delay_role"]},
        ],
        "render_spec_summary": {},
    }

    enriched = json.loads(_enrich_timeline_with_producer_plan(json.dumps(timeline), render_plan))
    summary = enriched["render_spec_summary"]
    by_section = {e["section"].lower(): e for e in summary["transition_plan_by_section"]}

    assert "bridge" in by_section
    assert "mute_role" in by_section["bridge"]["planned_events"]
    assert "delay_role" in by_section["bridge"]["planned_events"]
    assert by_section["bridge"]["matched_count"] > 0
    assert by_section["bridge"]["plan_coverage"] > 0
    assert "bridge" not in summary["sections_missing_transitions"]
    assert by_section["verse"]["planned_events"], "sections with producer events must have planned_events"


def test_fallback_source_does_not_replace_producer_source():
    render_plan = {
        "sections": [
            {"name": "Bridge", "type": "bridge", "bar_start": 8, "bars": 8, "instruments": ["drums"]},
            {"name": "Outro", "type": "outro", "bar_start": 16, "bars": 8, "instruments": ["drums"]},
        ],
        "events": [
            {"type": "mute_role", "bar": 9, "source": "producer_plan"},
        ],
    }
    producer_arrangement, _ = _build_producer_arrangement_from_render_plan(render_plan, fallback_bpm=120.0)
    bridge = producer_arrangement["sections"][0]
    outro = producer_arrangement["sections"][1]

    bridge_sources = {e.get("source") for e in bridge.get("variations", []) + bridge.get("boundary_events", [])}
    outro_sources = {e.get("source") for e in outro.get("variations", []) + outro.get("boundary_events", [])}

    assert "producer_plan" in bridge_sources
    assert "fallback" in outro_sources


def test_bridge_absolute_bars_not_double_offset_and_apply():
    render_plan = {
        "sections": [
            {"name": "Bridge", "type": "bridge", "bar_start": 99, "bars": 13, "instruments": ["drums", "bass"]},
        ],
        "events": [
            {"type": "mute_role", "bar": 99, "source": "producer_plan"},
            {"type": "delay_role", "bar": 111, "source": "producer_plan"},
        ],
        "producer_plan": {
            "events": [
                {"section_name": "bridge", "bar_start": 99, "bar_end": 100, "render_action": "mute_role"},
                {"section_name": "bridge", "bar_start": 111, "bar_end": 112, "render_action": "delay_role"},
            ]
        },
    }
    producer_arrangement, _ = _build_producer_arrangement_from_render_plan(render_plan, fallback_bpm=120.0)
    bridge = producer_arrangement["sections"][0]
    timeline = {
        "sections": [{**bridge, "applied_events": ["mute_role", "delay_role"], "skipped_events": []}],
        "render_spec_summary": {},
    }

    enriched = json.loads(_enrich_timeline_with_producer_plan(json.dumps(timeline), render_plan))
    summary = enriched["render_spec_summary"]
    bridge_row = next(row for row in summary["transition_plan_by_section"] if row["section"].lower() == "bridge")

    assert bridge_row["plan_coverage"] > 0
    assert "mute_role" in bridge_row["planned_events"]
    assert "delay_role" in bridge_row["planned_events"]
    assert bridge_row["matched_count"] >= 2
    assert not any(
        e.get("reason") == "event_out_of_section_bounds"
        for e in enriched["sections"][0].get("skipped_events", [])
    )


def test_bridge_section_relative_bars_are_offset_once():
    render_plan = {
        "sections": [
            {"name": "Bridge", "type": "bridge", "bar_start": 99, "bars": 13, "instruments": ["drums", "bass"]},
        ],
        "events": [
            {"type": "mute_role", "bar": 99, "source": "producer_plan"},
            {"type": "delay_role", "bar": 100, "source": "producer_plan"},
        ],
        "producer_plan": {
            "events": [
                {"section_name": "bridge", "bar_start": 0, "bar_end": 1, "render_action": "mute_role"},
                {"section_name": "bridge", "bar_start": 1, "bar_end": 2, "render_action": "delay_role"},
            ]
        },
    }

    producer_arrangement, _ = _build_producer_arrangement_from_render_plan(render_plan, fallback_bpm=120.0)
    bridge = producer_arrangement["sections"][0]
    timeline = {
        "sections": [{**bridge, "applied_events": ["mute_role", "delay_role"]}],
        "render_spec_summary": {},
    }

    enriched = json.loads(_enrich_timeline_with_producer_plan(json.dumps(timeline), render_plan))
    summary = enriched["render_spec_summary"]
    bridge_row = next(row for row in summary["transition_plan_by_section"] if row["section"].lower() == "bridge")

    assert bridge_row["plan_coverage"] > 0
    assert bridge_row["matched_count"] >= 2
