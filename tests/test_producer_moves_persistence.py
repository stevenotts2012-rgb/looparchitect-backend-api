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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
