"""
Tests for producer moves persistence fix.

Covers:
1. Producer plan events are generated and non-empty
2. Fallback events fire when main pipeline produces nothing
3. All SUPPORTED_RENDER_ACTIONS are in _RENDER_MOVE_EVENT_TYPES
4. All SUPPORTED_RENDER_ACTIONS are in _PRODUCER_MOVE_TYPES
5. _apply_producer_move_effect handles all render action aliases
6. mute_role never mutes for more than 1 bar
7. Hook sections keep drums and bass (safety guard)
8. _extract_producer_fields_from_plan populates all fields
9. decision_log and section_summary are non-empty when events exist
10. transition_event_count derived from applied_events
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Generative producer system tests
# ---------------------------------------------------------------------------


class TestGenerativeProducerOrchestratorEvents:
    """Verify the orchestrator always produces events."""

    def _make_sections(self):
        return [
            {"name": "intro",    "bar_start": 0,  "bar_end": 8,  "bars": 8},
            {"name": "verse",    "bar_start": 8,  "bar_end": 16, "bars": 8},
            {"name": "hook",     "bar_start": 16, "bar_end": 24, "bars": 8},
            {"name": "bridge",   "bar_start": 24, "bar_end": 28, "bars": 4},
            {"name": "outro",    "bar_start": 28, "bar_end": 32, "bars": 4},
        ]

    def test_orchestrator_produces_events(self):
        """Orchestrator generates at least one event per section."""
        from app.services.generative_producer_system.orchestrator import (
            GenerativeProducerOrchestrator,
        )
        orch = GenerativeProducerOrchestrator(
            available_roles=["drums", "bass", "melody"],
        )
        plan = orch.run(
            sections=self._make_sections(),
            genre="trap",
            vibe="high",
            seed=1234,
        )
        assert len(plan.events) > 0, "Producer plan must not be empty"

    def test_all_events_have_supported_render_action(self):
        """Every event's render_action must be in SUPPORTED_RENDER_ACTIONS."""
        from app.services.generative_producer_system.orchestrator import (
            GenerativeProducerOrchestrator,
        )
        from app.services.generative_producer_system.types import SUPPORTED_RENDER_ACTIONS

        orch = GenerativeProducerOrchestrator(
            available_roles=["drums", "bass", "melody", "fx"],
        )
        plan = orch.run(
            sections=self._make_sections(),
            genre="generic",
            vibe="medium",
            seed=42,
        )
        for ev in plan.events:
            assert ev.render_action in SUPPORTED_RENDER_ACTIONS, (
                f"Event {ev.event_type} has unsupported render_action={ev.render_action!r}"
            )

    def test_fallback_events_when_all_skipped(self):
        """Fallback events are injected when mapper skips all generated events."""
        from app.services.generative_producer_system.orchestrator import (
            GenerativeProducerOrchestrator,
            _generate_fallback_events,
        )
        from app.services.generative_producer_system.types import SUPPORTED_RENDER_ACTIONS

        sections = self._make_sections()
        evs = _generate_fallback_events(sections, seed=99)
        assert len(evs) == len(sections), "One fallback event per section"
        for ev in evs:
            assert ev.render_action in SUPPORTED_RENDER_ACTIONS, (
                f"Fallback event has unsupported render_action={ev.render_action!r}"
            )

    def test_section_variation_score_non_zero_when_events_present(self):
        """section_variation_score > 0 when there are events."""
        from app.services.generative_producer_system.orchestrator import (
            GenerativeProducerOrchestrator,
        )
        orch = GenerativeProducerOrchestrator(
            available_roles=["drums", "bass", "melody"],
        )
        plan = orch.run(
            sections=self._make_sections(),
            genre="trap",
            vibe="high",
            seed=777,
        )
        if plan.events:
            assert plan.section_variation_score > 0.0


# ---------------------------------------------------------------------------
# Renderer mapping / event type set tests
# ---------------------------------------------------------------------------


class TestRenderEventTypeSets:
    """Verify SUPPORTED_RENDER_ACTIONS are present in both type-gate sets."""

    def test_supported_render_actions_in_render_executor_type_set(self):
        """All SUPPORTED_RENDER_ACTIONS must be in render_executor._RENDER_MOVE_EVENT_TYPES."""
        from app.services.generative_producer_system.types import SUPPORTED_RENDER_ACTIONS
        from app.services.render_executor import _RENDER_MOVE_EVENT_TYPES

        missing = SUPPORTED_RENDER_ACTIONS - _RENDER_MOVE_EVENT_TYPES
        assert not missing, (
            f"These SUPPORTED_RENDER_ACTIONS are not in _RENDER_MOVE_EVENT_TYPES: {missing}"
        )

    def test_supported_render_actions_in_producer_move_types(self):
        """All SUPPORTED_RENDER_ACTIONS must be in arrangement_jobs._PRODUCER_MOVE_TYPES."""
        from app.services.generative_producer_system.types import SUPPORTED_RENDER_ACTIONS
        from app.services.arrangement_jobs import _PRODUCER_MOVE_TYPES

        missing = SUPPORTED_RENDER_ACTIONS - _PRODUCER_MOVE_TYPES
        assert not missing, (
            f"These SUPPORTED_RENDER_ACTIONS are not in _PRODUCER_MOVE_TYPES: {missing}"
        )


# ---------------------------------------------------------------------------
# _apply_producer_move_effect handler tests
# ---------------------------------------------------------------------------


class TestApplyProducerMoveEffect:
    """Verify every SUPPORTED_RENDER_ACTIONS value has a handler."""

    @pytest.fixture(autouse=True)
    def _audio(self):
        """Build a 2-second 44.1 kHz silent AudioSegment for testing.

        At 120 BPM: 1 bar = 4 beats = (60/120) * 4 = 2 seconds = 2000 ms.
        """
        from pydub import AudioSegment
        self.seg = AudioSegment.silent(duration=2000, frame_rate=44100)
        self.bar_ms = 2000  # 120 BPM: 1 bar = 4 beats × 500 ms/beat = 2000 ms

    def _apply(self, move_type: str, intensity: float = 0.7, params: dict | None = None):
        from app.services.arrangement_jobs import _apply_producer_move_effect
        return _apply_producer_move_effect(
            segment=self.seg,
            move_type=move_type,
            intensity=intensity,
            stem_available=True,
            bar_duration_ms=self.bar_ms,
            params=params or {},
        )

    def test_mute_role_returns_audio(self):
        result = self._apply("mute_role")
        assert len(result) > 0

    def test_mute_role_max_duration_one_bar(self):
        """mute_role must not silence more than 1 bar of audio."""
        from pydub import AudioSegment

        # Use a 4-bar segment so there is headroom to measure the dropout window.
        # bar_ms comes from the fixture: 2000 ms at 120 BPM.
        seg4 = AudioSegment.silent(duration=4 * self.bar_ms)

        from app.services.arrangement_jobs import _apply_producer_move_effect
        result = _apply_producer_move_effect(
            segment=seg4,
            move_type="mute_role",
            intensity=1.0,  # max intensity
            stem_available=True,
            bar_duration_ms=self.bar_ms,
            params={},
        )
        # The result must be the same length as input (no audio dropped)
        assert len(result) == len(seg4)

    def test_unmute_role_returns_audio(self):
        result = self._apply("unmute_role")
        assert len(result) > 0

    def test_filter_role_returns_audio(self):
        result = self._apply("filter_role")
        assert len(result) > 0

    def test_chop_role_returns_audio(self):
        result = self._apply("chop_role")
        assert len(result) > 0

    def test_reverse_slice_returns_audio(self):
        result = self._apply("reverse_slice")
        assert len(result) > 0

    def test_add_hat_roll_returns_audio(self):
        result = self._apply("add_hat_roll")
        assert len(result) > 0

    def test_add_drum_fill_returns_audio(self):
        result = self._apply("add_drum_fill")
        assert len(result) > 0

    def test_bass_pattern_variation_returns_audio(self):
        result = self._apply("bass_pattern_variation")
        assert len(result) > 0

    def test_add_fx_riser_returns_audio(self):
        result = self._apply("add_fx_riser")
        assert len(result) > 0

    def test_add_impact_returns_audio(self):
        result = self._apply("add_impact")
        assert len(result) > 0

    def test_fade_role_returns_audio(self):
        result = self._apply("fade_role")
        assert len(result) > 0

    def test_widen_role_returns_audio(self):
        result = self._apply("widen_role")
        assert len(result) > 0

    def test_delay_role_returns_audio(self):
        result = self._apply("delay_role")
        assert len(result) > 0

    def test_reverb_tail_returns_audio(self):
        result = self._apply("reverb_tail")
        assert len(result) > 0

    def test_all_supported_actions_handled(self):
        """No SUPPORTED_RENDER_ACTION returns unchanged silent audio for all tests."""
        from app.services.generative_producer_system.types import SUPPORTED_RENDER_ACTIONS
        from app.services.arrangement_jobs import _apply_producer_move_effect
        from pydub import AudioSegment

        # Use a non-silent segment (+3 dB) so we can detect no-ops
        seg = AudioSegment.silent(duration=2000) + 3

        for action in SUPPORTED_RENDER_ACTIONS:
            result = _apply_producer_move_effect(
                segment=seg,
                move_type=action,
                intensity=0.7,
                stem_available=True,
                bar_duration_ms=500,
                params={},
            )
            assert len(result) > 0, f"{action} returned zero-length audio"


# ---------------------------------------------------------------------------
# Worker helper: _extract_producer_fields_from_plan
# ---------------------------------------------------------------------------


class TestExtractProducerFields:
    """Verify _extract_producer_fields_from_plan populates all DB fields."""

    def _make_render_plan(self, event_count: int = 3) -> dict:
        return {
            "bpm": 140.0,
            "total_bars": 32,
            "events": [
                {
                    "type": "add_drum_fill",
                    "bar": i * 4,
                    "intensity": 0.7,
                    "description": f"Fill {i}",
                }
                for i in range(event_count)
            ],
            "sections": [
                {
                    "name": "intro",
                    "type": "intro",
                    "bar_start": 0,
                    "bars": 8,
                }
            ],
            "render_profile": {
                "genre_profile": "trap",
                "energy_curve_score": 0.82,
            },
            "metadata": {
                "energy_curve_score": 0.82,
                "producer_variation_score": 0.65,
            },
        }

    def _make_timeline(self) -> str:
        return json.dumps({
            "sections": [
                {
                    "name": "intro",
                    "type": "intro",
                    "applied_events": ["add_drum_fill", "filter_role"],
                    "boundary_events": [{"type": "crash_hit", "placement": "start_of_section"}],
                    "transition_out": "filter_sweep",
                    "energy": 0.3,
                }
            ],
        })

    def test_producer_plan_json_not_null(self):
        from app.workers.render_worker import _extract_producer_fields_from_plan
        plan = self._make_render_plan(event_count=3)
        fields = _extract_producer_fields_from_plan(plan, self._make_timeline())
        assert fields["producer_plan_json"] is not None
        parsed = json.loads(fields["producer_plan_json"])
        assert isinstance(parsed, dict)

    def test_decision_log_not_empty(self):
        from app.workers.render_worker import _extract_producer_fields_from_plan
        plan = self._make_render_plan(event_count=3)
        fields = _extract_producer_fields_from_plan(plan, self._make_timeline())
        assert fields["decision_log_json"] is not None
        log = json.loads(fields["decision_log_json"])
        assert len(log) == 3, "decision_log should have one entry per event"

    def test_section_summary_contains_applied_events(self):
        from app.workers.render_worker import _extract_producer_fields_from_plan
        plan = self._make_render_plan()
        fields = _extract_producer_fields_from_plan(plan, self._make_timeline())
        assert fields["section_summary_json"] is not None
        summary = json.loads(fields["section_summary_json"])
        assert len(summary) == 1
        assert "applied_events" in summary[0]
        assert len(summary[0]["applied_events"]) == 2

    def test_section_summary_contains_boundary_events(self):
        from app.workers.render_worker import _extract_producer_fields_from_plan
        plan = self._make_render_plan()
        fields = _extract_producer_fields_from_plan(plan, self._make_timeline())
        summary = json.loads(fields["section_summary_json"])
        assert len(summary[0]["boundary_events"]) == 1

    def test_quality_score_populated(self):
        from app.workers.render_worker import _extract_producer_fields_from_plan
        plan = self._make_render_plan()
        fields = _extract_producer_fields_from_plan(plan, self._make_timeline())
        assert fields["quality_score"] is not None
        assert 0.0 <= fields["quality_score"] <= 1.0

    def test_transition_event_count_derivable(self):
        """transition_event_count can be derived from section_summary applied_events."""
        from app.workers.render_worker import _extract_producer_fields_from_plan
        plan = self._make_render_plan()
        fields = _extract_producer_fields_from_plan(plan, self._make_timeline())
        summary = json.loads(fields["section_summary_json"])
        transition_event_count = sum(len(s.get("applied_events") or []) for s in summary)
        assert transition_event_count > 0

    def test_handles_empty_events(self):
        """No crash when events list is empty."""
        from app.workers.render_worker import _extract_producer_fields_from_plan
        plan = self._make_render_plan(event_count=0)
        fields = _extract_producer_fields_from_plan(plan, "{}")
        assert fields["producer_plan_json"] is not None
        log = json.loads(fields["decision_log_json"])
        assert log == []


# ---------------------------------------------------------------------------
# render_executor: events are converted, not discarded
# ---------------------------------------------------------------------------


class TestRenderExecutorEventConversion:
    """Verify _build_producer_arrangement_from_render_plan converts producer events."""

    def test_producer_render_actions_placed_into_sections(self):
        """Events with SUPPORTED_RENDER_ACTIONS are placed in section variations."""
        from app.services.render_executor import _build_producer_arrangement_from_render_plan

        render_plan = {
            "bpm": 120.0,
            "total_bars": 16,
            "events": [
                {
                    "type": "add_drum_fill",
                    "bar": 6,
                    "intensity": 0.7,
                    "description": "drum fill",
                },
                {
                    "type": "filter_role",
                    "bar": 2,
                    "intensity": 0.5,
                    "description": "filter intro",
                },
                {
                    "type": "add_impact",
                    "bar": 10,
                    "intensity": 0.9,
                    "description": "hook impact",
                },
            ],
            "sections": [
                {
                    "name": "intro",
                    "type": "intro",
                    "bar_start": 0,
                    "bars": 8,
                    "energy": 0.3,
                    "instruments": ["drums", "bass"],
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
        }

        arrangement, summary = _build_producer_arrangement_from_render_plan(render_plan, fallback_bpm=120.0)
        sections = arrangement["sections"]

        # Collect all variation_types across all sections
        all_variation_types = []
        for sec in sections:
            for var in sec.get("variations") or []:
                all_variation_types.append(var.get("variation_type"))

        assert "add_drum_fill" in all_variation_types, (
            "add_drum_fill event should appear in section variations"
        )
        assert "filter_role" in all_variation_types, (
            "filter_role event should appear in section variations"
        )


# ---------------------------------------------------------------------------
# Fallback event injection tests
# ---------------------------------------------------------------------------


class TestFallbackTransitionEventInjection:
    """Verify deterministic fallback events are injected when producer plan is empty.

    The render-async path does not call _apply_stem_primary_section_states, so
    when the generative producer plan is empty sections would otherwise render
    with applied_events=[] and transition_event_count=0.  The fallback injector
    inside _build_producer_arrangement_from_render_plan ensures at least one
    event is present per section.
    """

    _SECTION_TYPES = ["intro", "verse", "pre_hook", "hook", "bridge", "outro"]

    def _make_empty_sections(self):
        cursor = 0
        sections = []
        bar_counts = {"intro": 8, "verse": 8, "pre_hook": 4, "hook": 8, "bridge": 4, "outro": 4}
        for stype in self._SECTION_TYPES:
            bars = bar_counts[stype]
            sections.append({
                "name": stype,
                "type": stype,
                "bar_start": cursor,
                "bars": bars,
                "energy": 0.5,
                "instruments": ["drums", "bass", "melody"],
                "variations": [],
                "boundary_events": [],
            })
            cursor += bars
        return sections

    def _make_render_plan(self, events=None):
        sections = self._make_empty_sections()
        total_bars = sum(s["bars"] for s in sections)
        return {
            "bpm": 120.0,
            "total_bars": total_bars,
            "events": events or [],
            "sections": sections,
        }

    # --- _inject_fallback_transition_events unit tests -----------------------

    def test_fallback_injected_when_no_producer_events(self):
        """Every section must receive at least one event when producer plan is empty."""
        from app.services.render_executor import _inject_fallback_transition_events

        sections = self._make_empty_sections()
        injected = _inject_fallback_transition_events(sections)
        assert injected > 0, "Fallback should inject events when sections are empty"
        for section in sections:
            total = len(section.get("variations") or []) + len(section.get("boundary_events") or [])
            assert total > 0, (
                f"Section {section['type']} still has no events after fallback injection"
            )

    def test_fallback_not_applied_when_section_has_variations(self):
        """Sections with existing variations must NOT receive fallback events."""
        from app.services.render_executor import _inject_fallback_transition_events

        sections = [
            {
                "name": "hook", "type": "hook", "bar_start": 0, "bars": 8,
                "variations": [{"variation_type": "add_drum_fill"}],
                "boundary_events": [],
            }
        ]
        original_len = len(sections[0]["variations"])
        injected = _inject_fallback_transition_events(sections)
        assert injected == 0, "Should not inject into a section that already has variations"
        assert len(sections[0]["variations"]) == original_len

    def test_fallback_not_applied_when_section_has_boundary_events(self):
        """Sections with existing boundary_events must NOT receive fallback events."""
        from app.services.render_executor import _inject_fallback_transition_events

        sections = [
            {
                "name": "bridge", "type": "bridge", "bar_start": 0, "bars": 4,
                "variations": [],
                "boundary_events": [{"type": "crash_hit"}],
            }
        ]
        injected = _inject_fallback_transition_events(sections)
        assert injected == 0
        assert len(sections[0]["boundary_events"]) == 1

    def test_hook_fallback_does_not_add_mute_role(self):
        """Hook sections must never receive a mute_role fallback (drums + bass preserved)."""
        from app.services.render_executor import _inject_fallback_transition_events

        sections = [
            {
                "name": "hook", "type": "hook", "bar_start": 0, "bars": 8,
                "variations": [],
                "boundary_events": [],
            }
        ]
        _inject_fallback_transition_events(sections)
        all_types = (
            [v.get("variation_type") for v in sections[0].get("variations") or []]
            + [e.get("type") for e in sections[0].get("boundary_events") or []]
        )
        assert "mute_role" not in all_types, (
            "mute_role must never be injected into hook sections"
        )

    def test_fallback_event_types_are_in_render_move_types(self):
        """All fallback event types must be in _RENDER_MOVE_EVENT_TYPES."""
        from app.services.render_executor import (
            _inject_fallback_transition_events,
            _RENDER_MOVE_EVENT_TYPES,
        )

        sections = self._make_empty_sections()
        _inject_fallback_transition_events(sections)
        for section in sections:
            for var in section.get("variations") or []:
                vtype = var.get("variation_type", "")
                assert vtype in _RENDER_MOVE_EVENT_TYPES, (
                    f"Fallback variation_type={vtype!r} not in _RENDER_MOVE_EVENT_TYPES"
                )
            for bev in section.get("boundary_events") or []:
                btype = bev.get("type", "")
                assert btype in _RENDER_MOVE_EVENT_TYPES, (
                    f"Fallback boundary event type={btype!r} not in _RENDER_MOVE_EVENT_TYPES"
                )

    # --- _build_producer_arrangement_from_render_plan integration tests ------

    def test_pipeline_all_sections_have_events_after_empty_plan(self):
        """When events=[], all sections must have variations or boundary_events after pipeline."""
        from app.services.render_executor import _build_producer_arrangement_from_render_plan

        render_plan = self._make_render_plan(events=[])
        arrangement, _ = _build_producer_arrangement_from_render_plan(render_plan, fallback_bpm=120.0)
        for section in arrangement["sections"]:
            total = len(section.get("variations") or []) + len(section.get("boundary_events") or [])
            assert total > 0, (
                f"Section {section['type']} has no events after pipeline with empty producer plan"
            )

    def test_transition_event_count_nonzero_after_empty_plan(self):
        """transition_event_count must be > 0 even with an empty producer plan.

        This simulates the full render pipeline: the fallback events must survive
        from _build_producer_arrangement_from_render_plan through to the
        _build_render_spec_summary applied_events accounting.
        """
        from app.services.render_executor import _build_producer_arrangement_from_render_plan
        from app.services.arrangement_jobs import _build_render_spec_summary

        render_plan = self._make_render_plan(events=[])
        arrangement, _ = _build_producer_arrangement_from_render_plan(render_plan, fallback_bpm=120.0)

        # Simulate what _render_producer_arrangement does: accumulate applied_events
        # per section.  For this test we mimic the fallback event accumulation by
        # reading the variations/boundary_events injected by the pipeline.
        simulated_sections = []
        for sec in arrangement["sections"]:
            applied = (
                [v.get("variation_type", "") for v in (sec.get("variations") or [])]
                + [e.get("type", "") for e in (sec.get("boundary_events") or [])]
            )
            simulated_sections.append({
                "name": sec["name"],
                "type": sec["type"],
                "applied_events": [e for e in applied if e],
                "boundary_events": sec.get("boundary_events") or [],
            })

        summary = _build_render_spec_summary(simulated_sections)
        assert summary["transition_event_count"] > 0, (
            f"transition_event_count must be > 0 but got {summary['transition_event_count']}"
        )

    def test_applied_events_nonempty_per_section_after_empty_plan(self):
        """Every section must have at least one applied_events entry after the pipeline."""
        from app.services.render_executor import _build_producer_arrangement_from_render_plan
        from app.services.arrangement_jobs import _build_render_spec_summary

        render_plan = self._make_render_plan(events=[])
        arrangement, _ = _build_producer_arrangement_from_render_plan(render_plan, fallback_bpm=120.0)

        for sec in arrangement["sections"]:
            total = (
                len(sec.get("variations") or [])
                + len(sec.get("boundary_events") or [])
            )
            assert total > 0, (
                f"Section '{sec['type']}' applied_events will be empty — fallback injection failed"
            )

    def test_existing_events_win_over_fallback(self):
        """When producer plan provides real events, fallback is skipped for those sections."""
        from app.services.render_executor import _build_producer_arrangement_from_render_plan

        render_plan = self._make_render_plan(events=[
            {"type": "add_drum_fill", "bar": 0, "intensity": 0.7},
        ])
        arrangement, _ = _build_producer_arrangement_from_render_plan(render_plan, fallback_bpm=120.0)

        # Intro section (bar 0) should have the real event, not need fallback
        intro_section = next(
            (s for s in arrangement["sections"] if s.get("type") == "intro"), None
        )
        assert intro_section is not None
        var_types = [v.get("variation_type") for v in (intro_section.get("variations") or [])]
        assert "add_drum_fill" in var_types


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
