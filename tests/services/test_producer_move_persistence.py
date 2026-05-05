"""
Tests for producer move persistence and rendering.

Covers the bug where producer moves were generated but silently discarded
because the render_action strings (e.g. "mute_role", "add_drum_fill") did not
match the event type strings expected by the renderer
("disable_stem", "drum_fill", etc.).

Test cases:
1. producer_plan persists non-null in render_plan_json
2. decision_log is non-empty when events are generated
3. arrangement_json sections contain applied_events / boundary_events after render
4. transition_event_count > 0
5. No event mutes all stems for more than 1 bar
6. Hook sections keep drums and bass roles
7. Fallback events are injected when producer engine returns no events
8. _RENDER_ACTION_TO_RENDERER_TYPE covers all SUPPORTED_RENDER_ACTIONS
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from app.services.generative_producer_system.types import (
    ProducerEvent,
    ProducerPlan,
    SUPPORTED_RENDER_ACTIONS,
)
from app.services.generative_producer_system.orchestrator import (
    GenerativeProducerOrchestrator,
    plan_to_dict,
)

# render_jobs helpers
from app.routes.render_jobs import (
    _RENDER_ACTION_TO_RENDERER_TYPE,
    _MUTE_RENDERER_TYPES,
    _HOOK_SECTION_TYPES,
    _generate_fallback_producer_events,
    _producer_plan_to_render_plan,
    _layout_sections,
    _classify_roles,
)

# render_executor helper
from app.services.render_executor import (
    _build_producer_arrangement_from_render_plan,
    _RENDER_MOVE_EVENT_TYPES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_section_templates(total_bars: int = 32) -> List[Dict]:
    return _layout_sections(total_bars)


def _make_producer_plan(events: list[ProducerEvent] | None = None) -> ProducerPlan:
    """Build a minimal ProducerPlan with optional events."""
    if events is None:
        events = []
    plan = ProducerPlan(genre="trap", vibe="medium", seed=42, events=events)
    plan.section_variation_score = 0.4
    return plan


def _make_event(
    section_name: str = "verse",
    bar_start: int = 0,
    bar_end: int = 8,
    render_action: str = "add_drum_fill",
) -> ProducerEvent:
    return ProducerEvent.make(
        section_name=section_name,
        occurrence_index=0,
        bar_start=bar_start,
        bar_end=bar_end,
        target_role="drums",
        event_type="drum_fill",
        intensity=0.7,
        render_action=render_action,
        reason="test event",
    )


# ---------------------------------------------------------------------------
# 1. Render action mapping covers all SUPPORTED_RENDER_ACTIONS
# ---------------------------------------------------------------------------


class TestRenderActionMapping:
    def test_all_supported_render_actions_are_mapped(self):
        """Every SUPPORTED_RENDER_ACTION must have an entry in the translation dict.

        Without this, events from the generative producer system are silently
        discarded by the renderer because the type strings don't match.
        """
        unmapped = SUPPORTED_RENDER_ACTIONS - set(_RENDER_ACTION_TO_RENDERER_TYPE.keys())
        # A render_action may also pass through unchanged if it already matches a
        # renderer type (e.g. it appears verbatim in _RENDER_MOVE_EVENT_TYPES).
        truly_unmapped = {
            action for action in unmapped
            if action not in _RENDER_MOVE_EVENT_TYPES
        }
        assert not truly_unmapped, (
            f"The following SUPPORTED_RENDER_ACTIONS are not mapped to renderer types "
            f"and are not natively understood by the renderer: {sorted(truly_unmapped)}"
        )

    def test_all_renderer_types_are_valid(self):
        """Every value in _RENDER_ACTION_TO_RENDERER_TYPE must be in _RENDER_MOVE_EVENT_TYPES."""
        invalid = {
            action: renderer_type
            for action, renderer_type in _RENDER_ACTION_TO_RENDERER_TYPE.items()
            if renderer_type not in _RENDER_MOVE_EVENT_TYPES
        }
        assert not invalid, (
            f"The following render_action → renderer_type mappings target unknown renderer "
            f"types: {invalid}"
        )


# ---------------------------------------------------------------------------
# 2. _producer_plan_to_render_plan emits renderer-compatible event types
# ---------------------------------------------------------------------------


class TestProducerPlanToRenderPlan:
    _AVAILABLE_ROLES = ["drums", "bass", "melody", "fx"]

    def _call(self, producer_plan: ProducerPlan, total_bars: int = 32) -> dict:
        templates = _make_section_templates(total_bars)
        role_groups = _classify_roles(self._AVAILABLE_ROLES)
        return _producer_plan_to_render_plan(
            producer_plan=producer_plan,
            section_templates=templates,
            available_roles=self._AVAILABLE_ROLES,
            role_groups=role_groups,
            bpm=140.0,
            loop_id=1,
            genre="trap",
            key="C",
        )

    def test_producer_plan_persists_non_null(self):
        """render_plan_json must contain _producer_plan even with zero events."""
        plan = _make_producer_plan()
        result = self._call(plan)
        assert "_producer_plan" in result
        assert result["_producer_plan"] is not None
        assert isinstance(result["_producer_plan"], dict)

    def test_decision_log_populated_when_events_present(self):
        """decision_log should have one entry per ProducerEvent."""
        events = [
            _make_event(section_name="verse", bar_start=0, bar_end=8, render_action="add_drum_fill"),
            _make_event(section_name="hook", bar_start=8, bar_end=16, render_action="add_impact"),
        ]
        plan = _make_producer_plan(events=events)
        result = self._call(plan)
        assert "_decision_log" in result
        assert len(result["_decision_log"]) == 2

    def test_decision_log_empty_when_no_events(self):
        """decision_log is an empty list (not null) when producer has no events."""
        plan = _make_producer_plan()
        result = self._call(plan)
        assert result["_decision_log"] == []

    def test_section_summary_populated_when_events_present(self):
        """_section_summary groups events by section."""
        events = [
            _make_event(section_name="verse", render_action="add_drum_fill"),
            _make_event(section_name="verse", render_action="mute_role"),
            _make_event(section_name="hook", render_action="add_impact"),
        ]
        plan = _make_producer_plan(events=events)
        result = self._call(plan)
        summary = result["_section_summary"]
        assert "verse" in summary
        assert summary["verse"]["event_count"] == 2
        assert "hook" in summary
        assert summary["hook"]["event_count"] == 1

    def test_events_translated_to_renderer_types(self):
        """Events must use renderer-compatible type strings, not raw render_action names."""
        events = [
            _make_event(section_name="verse", render_action="mute_role"),
            _make_event(section_name="verse", render_action="add_drum_fill"),
            _make_event(section_name="hook", render_action="add_impact"),
        ]
        plan = _make_producer_plan(events=events)
        result = self._call(plan)

        # All event types in the top-level events list must be renderer-known types.
        for evt in result["events"]:
            evt_type = evt["type"]
            assert evt_type in _RENDER_MOVE_EVENT_TYPES, (
                f"Event type {evt_type!r} is not in _RENDER_MOVE_EVENT_TYPES — "
                f"it will be silently discarded by the renderer"
            )

    def test_fallback_events_injected_when_no_producer_events(self):
        """When producer_plan.events is empty, fallback events must be generated."""
        plan = _make_producer_plan()
        result = self._call(plan)
        assert len(result["events"]) > 0, "Fallback events must be injected when producer returns none"

    def test_fallback_events_use_renderer_compatible_types(self):
        """Fallback events must also use renderer-compatible type strings."""
        plan = _make_producer_plan()
        result = self._call(plan)
        for evt in result["events"]:
            assert evt["type"] in _RENDER_MOVE_EVENT_TYPES, (
                f"Fallback event type {evt['type']!r} is not in _RENDER_MOVE_EVENT_TYPES"
            )

    def test_mute_events_capped_to_one_bar(self):
        """Mute/dropout events must be at most 1 bar to prevent dead air."""
        events = [
            _make_event(
                section_name="verse",
                bar_start=0,
                bar_end=8,  # 8-bar duration — must be capped to 1
                render_action="mute_role",
            ),
        ]
        plan = _make_producer_plan(events=events)
        result = self._call(plan)

        for evt in result["events"]:
            if evt["type"] in _MUTE_RENDERER_TYPES:
                assert evt["duration_bars"] <= 1, (
                    f"Mute event {evt['type']!r} has duration_bars={evt['duration_bars']} "
                    f"which exceeds the 1-bar maximum and would cause dead air"
                )

    def test_hook_sections_have_drums_and_bass(self):
        """Hook sections must list drums and bass in their active_stem_roles."""
        plan = _make_producer_plan()
        result = self._call(plan)
        for section in result["sections"]:
            if section["name"] in _HOOK_SECTION_TYPES:
                roles = section.get("active_stem_roles") or section.get("instruments") or []
                has_drums = any("drum" in r.lower() or "percussion" in r.lower() for r in roles)
                has_bass = any("bass" in r.lower() for r in roles)
                if self._AVAILABLE_ROLES:  # only check when stems are available
                    assert has_drums, (
                        f"Hook section '{section['name']}' is missing drums — "
                        f"got roles: {roles}"
                    )
                    assert has_bass, (
                        f"Hook section '{section['name']}' is missing bass — "
                        f"got roles: {roles}"
                    )


# ---------------------------------------------------------------------------
# 3. _generate_fallback_producer_events output
# ---------------------------------------------------------------------------


class TestFallbackProducerEvents:
    def test_returns_nonempty_list(self):
        templates = _make_section_templates(32)
        events = _generate_fallback_producer_events(templates, ["drums", "bass", "melody"])
        assert len(events) > 0

    def test_all_event_types_are_renderer_compatible(self):
        templates = _make_section_templates(32)
        events = _generate_fallback_producer_events(templates, ["drums", "bass"])
        for evt in events:
            assert evt["type"] in _RENDER_MOVE_EVENT_TYPES, (
                f"Fallback event type {evt['type']!r} is not in _RENDER_MOVE_EVENT_TYPES"
            )

    def test_hook_sections_get_fill_event(self):
        """Hook sections must receive a stutter fill fallback event."""
        templates = _make_section_templates(32)
        events = _generate_fallback_producer_events(templates, ["drums", "bass", "melody"])
        hook_section_names = {
            t["name"] for t in templates if t["name"] in ("hook", "hook_2")
        }
        fill_section_names = set()
        for evt in events:
            if evt["type"] == "fill_event":
                # Find which section this bar belongs to
                bar = evt["bar"]
                for tmpl in templates:
                    if tmpl["bar_start"] <= bar < tmpl["bar_end"]:
                        fill_section_names.add(tmpl["name"])
                        break
        assert hook_section_names & fill_section_names, (
            f"Expected fill_event in hook sections {hook_section_names}, "
            f"but only got fills in {fill_section_names}"
        )

    def test_duration_bars_always_at_least_one(self):
        templates = _make_section_templates(32)
        events = _generate_fallback_producer_events(templates, ["drums"])
        for evt in events:
            assert evt.get("duration_bars", 1) >= 1


# ---------------------------------------------------------------------------
# 4. _build_producer_arrangement_from_render_plan accepts translated types
# ---------------------------------------------------------------------------


class TestRendererAcceptsTranslatedTypes:
    def _build_plan(self, events: list[dict]) -> dict:
        return {
            "bpm": 140.0,
            "total_bars": 16,
            "sections": [
                {
                    "name": "verse",
                    "type": "verse",
                    "bar_start": 0,
                    "bars": 8,
                    "energy": 0.5,
                    "instruments": ["drums", "bass", "melody"],
                    "variations": [],
                    "boundary_events": [],
                },
                {
                    "name": "hook",
                    "type": "hook",
                    "bar_start": 8,
                    "bars": 8,
                    "energy": 0.9,
                    "instruments": ["drums", "bass", "melody"],
                    "variations": [],
                    "boundary_events": [],
                },
            ],
            "events": events,
            "render_profile": {},
        }

    def test_translated_drum_fill_is_applied(self):
        """drum_fill (translated from add_drum_fill) must be dispatched into section variations."""
        render_plan = self._build_plan([
            {"type": "drum_fill", "bar": 4, "intensity": 0.7, "duration_bars": 1,
             "description": "test", "params": {}},
        ])
        producer_arrangement, summary = _build_producer_arrangement_from_render_plan(
            render_plan=render_plan, fallback_bpm=140.0
        )
        # The event should land in the verse section's variations
        verse_section = next(s for s in producer_arrangement["sections"] if s["name"] == "verse")
        var_types = [v["variation_type"] for v in verse_section.get("variations", [])]
        assert "drum_fill" in var_types, (
            f"drum_fill was not dispatched into verse variations; got {var_types}"
        )

    def test_translated_disable_stem_is_applied(self):
        """disable_stem (translated from mute_role) must be dispatched."""
        render_plan = self._build_plan([
            {"type": "disable_stem", "bar": 2, "intensity": 0.6, "duration_bars": 1,
             "description": "test", "params": {}},
        ])
        producer_arrangement, summary = _build_producer_arrangement_from_render_plan(
            render_plan=render_plan, fallback_bpm=140.0
        )
        verse_section = next(s for s in producer_arrangement["sections"] if s["name"] == "verse")
        var_types = [v["variation_type"] for v in verse_section.get("variations", [])]
        assert "disable_stem" in var_types

    def test_unknown_event_type_is_skipped(self):
        """Events with unknown types (old render_action names) must be skipped, not crash."""
        render_plan = self._build_plan([
            {"type": "mute_role", "bar": 4, "intensity": 0.7, "duration_bars": 1,
             "description": "old action name", "params": {}},
        ])
        # Must not raise
        producer_arrangement, summary = _build_producer_arrangement_from_render_plan(
            render_plan=render_plan, fallback_bpm=140.0
        )
        # mute_role should be skipped (not in _RENDER_MOVE_EVENT_TYPES before the fix)
        # After the fix, the translation happens upstream so this should arrive as disable_stem
        assert producer_arrangement is not None


# ---------------------------------------------------------------------------
# 5. GenerativeProducerOrchestrator → _producer_plan_to_render_plan pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Integration-style tests that run the full producer → render-plan chain."""

    _SECTIONS = [
        {"name": "intro",    "bar_start": 0,  "bar_end": 4,  "bars": 4},
        {"name": "verse",    "bar_start": 4,  "bar_end": 12, "bars": 8},
        {"name": "pre_hook", "bar_start": 12, "bar_end": 16, "bars": 4},
        {"name": "hook",     "bar_start": 16, "bar_end": 24, "bars": 8},
        {"name": "bridge",   "bar_start": 24, "bar_end": 28, "bars": 4},
        {"name": "outro",    "bar_start": 28, "bar_end": 32, "bars": 4},
    ]
    _AVAILABLE_ROLES = ["drums", "bass", "melody", "fx"]

    def _run(self, genre: str = "trap", seed: int = 42) -> dict:
        orchestrator = GenerativeProducerOrchestrator(
            available_roles=self._AVAILABLE_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        producer_plan = orchestrator.run(
            sections=self._SECTIONS,
            genre=genre,
            vibe="medium",
            seed=seed,
        )
        role_groups = _classify_roles(self._AVAILABLE_ROLES)
        return _producer_plan_to_render_plan(
            producer_plan=producer_plan,
            section_templates=self._SECTIONS,
            available_roles=self._AVAILABLE_ROLES,
            role_groups=role_groups,
            bpm=140.0,
            loop_id=1,
            genre=genre,
        )

    def test_producer_plan_non_null(self):
        result = self._run()
        assert result["_producer_plan"] is not None
        assert isinstance(result["_producer_plan"], dict)
        assert result["_producer_plan"]["genre"] == "trap"

    def test_decision_log_non_empty(self):
        result = self._run()
        # Producer generates at least some events for a 6-section arrangement
        assert len(result["_decision_log"]) > 0

    def test_all_top_level_events_use_renderer_types(self):
        result = self._run()
        for evt in result["events"]:
            assert evt["type"] in _RENDER_MOVE_EVENT_TYPES, (
                f"Event type {evt['type']!r} produced by full pipeline is not in "
                f"_RENDER_MOVE_EVENT_TYPES — it will be discarded by the renderer"
            )

    def test_transition_event_count_positive(self):
        """After the full pipeline, events > 0 means transition_event_count will be > 0."""
        result = self._run()
        assert len(result["events"]) > 0, (
            "No events generated — transition_event_count will be 0 after rendering"
        )

    def test_no_mute_event_exceeds_one_bar(self):
        result = self._run()
        for evt in result["events"]:
            if evt["type"] in _MUTE_RENDERER_TYPES:
                assert evt["duration_bars"] <= 1, (
                    f"Mute event {evt['type']!r} duration_bars={evt['duration_bars']} "
                    f"exceeds 1-bar maximum — would cause dead air"
                )

    def test_hook_sections_have_drums_and_bass_instruments(self):
        result = self._run()
        for section in result["sections"]:
            if section["name"] in _HOOK_SECTION_TYPES:
                roles = section.get("instruments") or section.get("active_stem_roles") or []
                drums_present = any("drum" in r.lower() or "percussion" in r.lower() for r in roles)
                bass_present = any("bass" in r.lower() for r in roles)
                assert drums_present, f"Hook section {section['name']} missing drums, got: {roles}"
                assert bass_present, f"Hook section {section['name']} missing bass, got: {roles}"

    def test_section_summary_non_empty(self):
        result = self._run()
        assert isinstance(result["_section_summary"], dict)
        assert len(result["_section_summary"]) > 0

    @pytest.mark.parametrize("genre", ["trap", "drill", "rnb", "rage", "west_coast", "generic"])
    def test_all_genres_produce_valid_renderer_events(self, genre: str):
        """All genres must produce events with renderer-compatible type strings."""
        result = self._run(genre=genre)
        for evt in result["events"]:
            assert evt["type"] in _RENDER_MOVE_EVENT_TYPES, (
                f"Genre {genre!r}: event type {evt['type']!r} not in _RENDER_MOVE_EVENT_TYPES"
            )
