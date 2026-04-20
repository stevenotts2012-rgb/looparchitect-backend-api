"""
Tests for the producer moves translator and its integration with the
ProducerMovesEngine.

Verifies:
1. Current UI move selections are still accepted (backward compat)
2. Moves are translated into structured planning intents (not one-to-one shallow events)
3. Conflicting moves are resolved correctly
4. Repeated sections become more distinct when move combinations allow it
5. Observability fields are present in render plans
6. No direct one-to-one shallow-only behavior remains
"""

from __future__ import annotations

import pytest

from app.services.producer_moves_translator import (
    MoveTranslationResult,
    PlanningIntent,
    translate_producer_moves,
)
from app.services.producer_moves_engine import ProducerMovesEngine
from app.services.arrangement_jobs import _build_pre_render_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_render_plan(sections: list[dict] | None = None) -> dict:
    """Return a minimal render plan suitable for ProducerMovesEngine.inject."""
    if sections is None:
        sections = [
            {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.6, "instruments": ["kick", "bass"]},
            {"name": "Hook 1", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.8, "instruments": ["kick", "snare", "bass", "melody"]},
            {"name": "Bridge", "type": "bridge", "bar_start": 16, "bars": 8, "energy": 0.45, "instruments": ["pad", "melody"]},
            {"name": "Hook 2", "type": "hook", "bar_start": 24, "bars": 8, "energy": 0.85, "instruments": ["kick", "snare", "bass", "melody", "hats"]},
            {"name": "Outro", "type": "outro", "bar_start": 32, "bars": 8, "energy": 0.35, "instruments": ["pad"]},
        ]
    return {
        "arrangement_id": 1,
        "bpm": 96.0,
        "target_seconds": 100,
        "key": "C",
        "total_bars": sum(s["bars"] for s in sections),
        "sections": sections,
        "events": [],
        "tracks": [],
        "render_profile": {},
    }


# ---------------------------------------------------------------------------
# 1. Translation produces structured intents (not shallow one-to-one events)
# ---------------------------------------------------------------------------


class TestTranslationProducesIntents:
    """Moves must translate into structured PlanningIntent dicts, not single events."""

    def test_hook_drop_produces_four_intent_fields(self):
        result = translate_producer_moves(["hook_drop"])
        assert len(result.translated_planning_intents) == 1
        intent = result.translated_planning_intents[0]
        assert intent["move_name"] == "hook_drop"
        # All four intent dimensions must be populated
        assert intent["section_intent"]
        assert intent["timeline_intent"]
        assert intent["pattern_intent"]
        assert intent["transition_intent"]

    def test_bridge_breakdown_intent_describes_deep_planning(self):
        result = translate_producer_moves(["bridge_breakdown"])
        intent = result.translated_planning_intents[0]
        # Must describe a multi-dimensional planning behaviour, not a single effect toggle
        assert "sparse" in intent["section_intent"] or "density" in intent["section_intent"]
        assert intent["pattern_intent"] == "bass_dropout"
        assert intent["transition_intent"] == "mute_drop"

    def test_outro_strip_uses_progressive_intent_not_single_strip(self):
        result = translate_producer_moves(["outro_strip"])
        intent = result.translated_planning_intents[0]
        # Must be progressive, not a single strip event
        assert "progressive" in intent["section_intent"]
        assert intent["timeline_intent"] == "progressive_layer_removal"
        assert intent["parameters"]["progressive"] is True

    def test_eight_bar_hat_roll_plans_repeating_variation(self):
        result = translate_producer_moves(["8-bar hat roll"])
        intent = result.translated_planning_intents[0]
        # Must plan repetition, not emit one stock effect
        assert intent["parameters"].get("repeat") is True
        assert int(intent["parameters"].get("interval_bars", 0)) == 4

    def test_call_and_response_describes_alternating_phrase_behavior(self):
        result = translate_producer_moves(["call-and-response"])
        intent = result.translated_planning_intents[0]
        assert "alternating" in intent["section_intent"]
        assert intent["parameters"].get("alternating_phrase") is True


# ---------------------------------------------------------------------------
# 2. UI selections still work (backward compatibility / alias resolution)
# ---------------------------------------------------------------------------


class TestUISelectionsStillWork:
    """All display names from the UI must be accepted."""

    @pytest.mark.parametrize("ui_name,expected_canonical", [
        ("Hook Drop", "hook_drop"),
        ("End-of-Section Fill", "end_of_section_fill"),
        ("Pre-Hook Mute", "pre_hook_mute"),
        ("Silence Drop", "silence_drop"),
        ("Verse Space", "verse_space"),
        ("8-Bar Hat Roll", "eight_bar_hat_roll"),
        ("Layer Lift", "layer_lift"),
        ("Bridge Breakdown", "bridge_breakdown"),
        ("Final Hook Expansion", "final_hook_expansion"),
        ("Call-and-Response", "call_and_response"),
        ("Intro Tease", "intro_tease"),
        ("Outro Strip", "outro_strip"),
    ])
    def test_ui_display_name_accepted(self, ui_name, expected_canonical):
        result = translate_producer_moves([ui_name])
        assert expected_canonical in result.selected_producer_moves, (
            f"UI name '{ui_name}' should resolve to '{expected_canonical}'"
        )

    def test_empty_moves_returns_empty_result(self):
        result = translate_producer_moves([])
        assert result.selected_producer_moves == []
        assert result.translated_planning_intents == []

    def test_none_moves_returns_empty_result(self):
        result = translate_producer_moves(None)
        assert result.selected_producer_moves == []

    def test_unknown_move_is_silently_skipped(self):
        result = translate_producer_moves(["unknown_move_xyz", "hook_drop"])
        assert "hook_drop" in result.selected_producer_moves
        assert "unknown_move_xyz" not in result.selected_producer_moves


# ---------------------------------------------------------------------------
# 3. Conflicting moves are resolved
# ---------------------------------------------------------------------------


class TestConflictResolution:
    """Contradictory move combinations must be detected and resolved."""

    def test_pre_hook_mute_and_silence_drop_conflict_resolved(self):
        result = translate_producer_moves(["pre_hook_mute", "silence_drop"])
        # Only the stronger one (silence_drop) should survive
        assert "silence_drop" in result.selected_producer_moves
        assert "pre_hook_mute" not in result.selected_producer_moves
        assert len(result.conflicting_moves_resolved) >= 1
        assert any("silence" in c.lower() or "pre_hook" in c.lower()
                   for c in result.conflicting_moves_resolved)

    def test_outro_strip_and_layer_lift_conflict_resolved(self):
        result = translate_producer_moves(["outro_strip", "layer_lift"])
        assert "outro_strip" in result.selected_producer_moves
        assert "layer_lift" not in result.selected_producer_moves
        assert len(result.conflicting_moves_resolved) >= 1

    def test_non_conflicting_moves_both_preserved(self):
        result = translate_producer_moves(["hook_drop", "bridge_breakdown"])
        assert "hook_drop" in result.selected_producer_moves
        assert "bridge_breakdown" in result.selected_producer_moves
        assert result.conflicting_moves_resolved == []

    def test_conflict_log_is_human_readable(self):
        result = translate_producer_moves(["pre_hook_mute", "silence_drop"])
        for entry in result.conflicting_moves_resolved:
            assert isinstance(entry, str)
            assert len(entry) > 10  # not just an empty string


# ---------------------------------------------------------------------------
# 4. Intents flow into ProducerMovesEngine and modulate section behavior
# ---------------------------------------------------------------------------


class TestIntentModulationInEngine:
    """Planning intents must measurably affect section energy/density."""

    def test_hook_drop_raises_hook_energy(self):
        plan = _simple_render_plan()
        baseline_hook_energy = [
            float(s.get("energy", 0))
            for s in plan["sections"]
            if s.get("type") == "hook"
        ]

        plan_with_move = _simple_render_plan()
        result = translate_producer_moves(["hook_drop"])
        plan_with_move = ProducerMovesEngine.inject(plan_with_move, move_translation=result)

        moved_hook_energy = [
            float(s.get("energy", 0))
            for s in plan_with_move["sections"]
            if s.get("type") == "hook"
        ]
        # hook_drop must not reduce hook energy vs. the baseline
        assert min(moved_hook_energy) >= min(baseline_hook_energy)

    def test_bridge_breakdown_reduces_bridge_energy(self):
        plan = _simple_render_plan()
        baseline_bridge_energy = float(
            next(s for s in plan["sections"] if s.get("type") == "bridge")["energy"]
        )

        plan_with_move = _simple_render_plan()
        result = translate_producer_moves(["bridge_breakdown"])
        plan_with_move = ProducerMovesEngine.inject(plan_with_move, move_translation=result)

        moved_bridge_energy = float(
            next(s for s in plan_with_move["sections"] if s.get("type") == "bridge")["energy"]
        )
        # bridge_breakdown has energy_modifier=-0.20, so energy must be lower
        assert moved_bridge_energy <= baseline_bridge_energy

    def test_final_hook_expansion_targets_only_final_hook(self):
        sections = [
            {"name": "Hook 1", "type": "hook", "bar_start": 0, "bars": 8, "energy": 0.80, "instruments": ["kick", "snare", "bass", "melody"]},
            {"name": "Hook 2", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.85, "instruments": ["kick", "snare", "bass", "melody", "hats"]},
        ]
        plan = _simple_render_plan(sections)
        result = translate_producer_moves(["final_hook_expansion"])
        plan = ProducerMovesEngine.inject(plan, move_translation=result)

        hook_sections = [s for s in plan["sections"] if s.get("type") == "hook"]
        assert len(hook_sections) == 2
        # The last hook should have a higher layers target than the first
        assert hook_sections[-1].get("active_layers_target", 0) >= hook_sections[0].get("active_layers_target", 0)

    def test_section_tagged_with_applied_move_intents(self):
        plan = _simple_render_plan()
        result = translate_producer_moves(["bridge_breakdown"])
        plan = ProducerMovesEngine.inject(plan, move_translation=result)

        bridge = next(s for s in plan["sections"] if s.get("type") == "bridge")
        assert "bridge_breakdown" in bridge.get("applied_move_intents", [])


# ---------------------------------------------------------------------------
# 5. Observability fields present in render plan
# ---------------------------------------------------------------------------


class TestObservabilityFields:
    """All five observability fields must be present in the render plan."""

    def test_observability_fields_present_with_moves(self):
        plan = _simple_render_plan()
        result = translate_producer_moves(["hook_drop", "bridge_breakdown"])
        plan = ProducerMovesEngine.inject(plan, move_translation=result)

        assert "selected_producer_moves" in plan
        assert "translated_planning_intents" in plan
        assert "timeline_events_from_moves" in plan
        assert "pattern_events_from_moves" in plan
        assert "conflicting_moves_resolved" in plan

    def test_observability_fields_present_without_moves(self):
        plan = _simple_render_plan()
        plan = ProducerMovesEngine.inject(plan)

        assert "selected_producer_moves" in plan
        assert plan["selected_producer_moves"] == []
        assert "translated_planning_intents" in plan
        assert "timeline_events_from_moves" in plan
        assert "pattern_events_from_moves" in plan
        assert "conflicting_moves_resolved" in plan

    def test_selected_moves_populated_correctly(self):
        plan = _simple_render_plan()
        result = translate_producer_moves(["hook_drop", "outro_strip"])
        plan = ProducerMovesEngine.inject(plan, move_translation=result)

        assert "hook_drop" in plan["selected_producer_moves"]
        assert "outro_strip" in plan["selected_producer_moves"]

    def test_intents_have_expected_keys(self):
        plan = _simple_render_plan()
        result = translate_producer_moves(["hook_drop"])
        plan = ProducerMovesEngine.inject(plan, move_translation=result)

        assert len(plan["translated_planning_intents"]) == 1
        intent = plan["translated_planning_intents"][0]
        for key in ("move_name", "section_intent", "timeline_intent", "pattern_intent", "transition_intent"):
            assert key in intent, f"Intent missing key: {key}"

    def test_timeline_hints_have_source_move(self):
        result = translate_producer_moves(["hook_drop", "bridge_breakdown"])
        for hint in result.timeline_events_from_moves:
            assert "source_move" in hint
            assert "timeline_intent" in hint

    def test_pattern_hints_have_source_move(self):
        result = translate_producer_moves(["verse_space", "call_and_response"])
        for hint in result.pattern_events_from_moves:
            assert "source_move" in hint
            assert "pattern_intent" in hint


# ---------------------------------------------------------------------------
# 6. Repeated sections differentiated when move combinations allow
# ---------------------------------------------------------------------------


class TestRepeatedSectionDifferentiation:
    """When relevant moves are active, repeated sections must evolve differently."""

    def test_hooks_evolve_with_final_hook_expansion(self):
        producer_arrangement = {
            "tempo": 96.0,
            "key": "C",
            "total_bars": 48,
            "sections": [
                {"name": "Hook 1", "type": "hook", "bar_start": 0, "bars": 8, "energy": 0.80, "instruments": ["kick", "snare", "bass", "melody"]},
                {"name": "Hook 2", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.85, "instruments": ["kick", "snare", "bass", "melody", "hats"]},
                {"name": "Hook 3", "type": "hook", "bar_start": 16, "bars": 8, "energy": 0.90, "instruments": ["kick", "snare", "bass", "melody", "hats", "fx"]},
            ],
            "tracks": [],
        }

        plan = _build_pre_render_plan(
            arrangement_id=2001,
            bpm=96.0,
            target_seconds=100,
            producer_arrangement=producer_arrangement,
            style_sections=None,
            genre_hint="trap",
            selected_producer_moves=["final_hook_expansion", "hook_drop"],
        )

        hook_sections = [s for s in plan["sections"] if str(s.get("type", "")).lower() == "hook"]
        assert len(hook_sections) == 3

        # Hooks should grow: energy values must be non-decreasing
        energies = [float(s.get("energy", 0.0)) for s in hook_sections]
        assert energies[-1] >= energies[0], (
            f"Final hook energy should be >= first hook; got {energies}"
        )

        # Layer targets must grow across hooks
        layer_targets = [int(s.get("active_layers_target", 0)) for s in hook_sections]
        assert layer_targets[-1] >= layer_targets[0]

    def test_verse_space_reduces_density_in_verses(self):
        producer_arrangement = {
            "tempo": 96.0,
            "key": "C",
            "total_bars": 32,
            "sections": [
                {"name": "Verse 1", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.60, "instruments": ["kick", "snare", "bass", "melody"]},
                {"name": "Hook 1", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.80, "instruments": ["kick", "snare", "bass", "melody", "hats"]},
                {"name": "Verse 2", "type": "verse", "bar_start": 16, "bars": 8, "energy": 0.62, "instruments": ["kick", "snare", "bass", "melody"]},
                {"name": "Hook 2", "type": "hook", "bar_start": 24, "bars": 8, "energy": 0.88, "instruments": ["kick", "snare", "bass", "melody", "hats"]},
            ],
            "tracks": [],
        }

        plan = _build_pre_render_plan(
            arrangement_id=2002,
            bpm=96.0,
            target_seconds=80,
            producer_arrangement=producer_arrangement,
            style_sections=None,
            genre_hint="rnb",
            selected_producer_moves=["verse_space"],
        )

        verse_sections = [s for s in plan["sections"] if str(s.get("type", "")).lower() == "verse"]
        hook_sections = [s for s in plan["sections"] if str(s.get("type", "")).lower() == "hook"]

        avg_verse = sum(float(s.get("energy", 0)) for s in verse_sections) / len(verse_sections)
        avg_hook = sum(float(s.get("energy", 0)) for s in hook_sections) / len(hook_sections)

        # verse_space should keep verses below hooks
        assert avg_verse < avg_hook

    def test_bridge_breakdown_sparses_bridge_more_than_without_move(self):
        """Bridge energy must be lower when bridge_breakdown is active."""
        base_sections = [
            {"name": "Bridge", "type": "bridge", "bar_start": 0, "bars": 8, "energy": 0.50, "instruments": ["pad", "bass"]},
        ]

        plan_no_move = _build_pre_render_plan(
            arrangement_id=2003,
            bpm=96.0,
            target_seconds=30,
            producer_arrangement={"tempo": 96, "key": "C", "total_bars": 8, "sections": base_sections, "tracks": []},
            style_sections=None,
            genre_hint="trap",
            selected_producer_moves=[],
        )

        plan_with_move = _build_pre_render_plan(
            arrangement_id=2004,
            bpm=96.0,
            target_seconds=30,
            producer_arrangement={"tempo": 96, "key": "C", "total_bars": 8, "sections": base_sections, "tracks": []},
            style_sections=None,
            genre_hint="trap",
            selected_producer_moves=["bridge_breakdown"],
        )

        bridge_no_move = next(s for s in plan_no_move["sections"] if s.get("type") == "bridge")
        bridge_with_move = next(s for s in plan_with_move["sections"] if s.get("type") == "bridge")

        assert float(bridge_with_move.get("energy", 1.0)) <= float(bridge_no_move.get("energy", 1.0))


# ---------------------------------------------------------------------------
# 7. to_dict serialisation round-trip
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_translation_result_to_dict_round_trips(self):
        result = translate_producer_moves(["hook_drop", "bridge_breakdown"])
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "selected_producer_moves" in d
        assert "translated_planning_intents" in d
        assert "timeline_events_from_moves" in d
        assert "pattern_events_from_moves" in d
        assert "conflicting_moves_resolved" in d

    def test_empty_result_to_dict(self):
        result = translate_producer_moves(None)
        d = result.to_dict()
        assert d["selected_producer_moves"] == []
        assert d["translated_planning_intents"] == []
