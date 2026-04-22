"""Additional tests for app/services/transition_engine.py — covering uncovered branches.

Focuses on:
- _normalize_section_type helper
- _section_energy helper
- _bar_start / _bar_end helpers
- _detected_roles helper
- build_transition_plan edge cases (outro, bridge, chorus/drop aliases, intro→hook)
- TransitionEngine.create_transition and audio generation methods
"""

import pytest
from unittest.mock import MagicMock
from pydub import AudioSegment

from app.services.transition_engine import (
    _bar_end,
    _bar_start,
    _detected_roles,
    _normalize_section_type,
    _section_energy,
    build_transition_plan,
    TransitionEngine,
)
from app.services.producer_models import TransitionType


# ===========================================================================
# _normalize_section_type
# ===========================================================================

class TestNormalizeSectionType:
    def test_none_defaults_to_verse(self):
        assert _normalize_section_type(None) == "verse"

    def test_empty_dict_defaults_to_verse(self):
        assert _normalize_section_type({}) == "verse"

    def test_section_type_field_used(self):
        assert _normalize_section_type({"section_type": "intro"}) == "intro"

    def test_type_field_fallback(self):
        assert _normalize_section_type({"type": "bridge"}) == "bridge"

    def test_name_field_last_fallback(self):
        assert _normalize_section_type({"name": "Outro"}) == "outro"

    def test_chorus_normalized_to_hook(self):
        assert _normalize_section_type({"section_type": "Chorus"}) == "hook"

    def test_drop_normalized_to_hook(self):
        assert _normalize_section_type({"section_type": "drop"}) == "hook"

    def test_build_normalized_to_buildup(self):
        assert _normalize_section_type({"section_type": "buildup"}) == "buildup"

    def test_break_normalized_to_bridge(self):
        assert _normalize_section_type({"section_type": "break"}) == "bridge"

    def test_whitespace_stripped(self):
        assert _normalize_section_type({"section_type": "  hook  "}) == "hook"


# ===========================================================================
# _section_energy
# ===========================================================================

class TestSectionEnergy:
    def test_none_returns_default(self):
        assert _section_energy(None) == 0.6

    def test_empty_dict_returns_default(self):
        assert _section_energy({}) == 0.6

    def test_energy_field_used(self):
        assert _section_energy({"energy": 0.9}) == 0.9

    def test_energy_level_field_preferred(self):
        assert _section_energy({"energy_level": 0.8, "energy": 0.5}) == 0.8

    def test_none_value_returns_default(self):
        assert _section_energy({"energy": None}) == 0.6

    def test_returns_float(self):
        result = _section_energy({"energy": 1})
        assert isinstance(result, float)


# ===========================================================================
# _bar_start / _bar_end
# ===========================================================================

class TestBarHelpers:
    def test_bar_start_uses_bar_start_field(self):
        assert _bar_start({"bar_start": 8}) == 8

    def test_bar_start_uses_start_bar_fallback(self):
        assert _bar_start({"start_bar": 16}) == 16

    def test_bar_start_defaults_to_zero(self):
        assert _bar_start({}) == 0

    def test_bar_end_adds_bars_to_start(self):
        assert _bar_end({"bar_start": 0, "bars": 8}) == 8

    def test_bar_end_minimum_one_bar(self):
        """If bars is missing/zero, bar_end is at least start + 1."""
        assert _bar_end({"bar_start": 4, "bars": 0}) == 5

    def test_bar_end_with_missing_bars(self):
        assert _bar_end({"bar_start": 8}) == 9  # default bars=1


# ===========================================================================
# _detected_roles
# ===========================================================================

class TestDetectedRoles:
    def test_none_stem_metadata_uses_sections(self):
        sections = [{"active_stem_roles": ["drums", "bass"]}]
        roles = _detected_roles(None, sections)
        assert "drums" in roles
        assert "bass" in roles

    def test_roles_detected_key_used(self):
        meta = {"roles_detected": ["melody", "fx"]}
        roles = _detected_roles(meta, [])
        assert "melody" in roles
        assert "fx" in roles

    def test_stems_generated_key_used(self):
        meta = {"stems_generated": ["drums"]}
        roles = _detected_roles(meta, [])
        assert "drums" in roles

    def test_available_roles_key_used(self):
        meta = {"available_roles": ["pad"]}
        roles = _detected_roles(meta, [])
        assert "pad" in roles

    def test_non_list_value_ignored(self):
        meta = {"roles_detected": "drums"}  # string, not list
        roles = _detected_roles(meta, [])
        assert len(roles) == 0

    def test_roles_normalised_lowercase(self):
        meta = {"roles_detected": ["DRUMS", "Bass"]}
        roles = _detected_roles(meta, [])
        assert "drums" in roles
        assert "bass" in roles

    def test_empty_items_skipped(self):
        meta = {"roles_detected": [None, "", "fx"]}
        roles = _detected_roles(meta, [])
        assert "fx" in roles
        assert "" not in roles


# ===========================================================================
# build_transition_plan — edge cases
# ===========================================================================

class TestBuildTransitionPlanEdgeCases:
    def test_empty_sections_returns_empty(self):
        result = build_transition_plan([])
        assert result == {"boundaries": [], "events": []}

    def test_single_section_returns_empty(self):
        result = build_transition_plan([{"name": "Intro", "bar_start": 0, "bars": 8}])
        assert result == {"boundaries": [], "events": []}

    def test_intro_to_hook_with_no_energy_lift_skips_silence_drop(self):
        """Intro→hook where energy_lift < 0.1 skips pre_hook events."""
        sections = [
            {"section_type": "intro", "bar_start": 0, "bars": 8, "energy": 0.5},
            {"section_type": "hook", "bar_start": 8, "bars": 8, "energy": 0.5},
        ]
        result = build_transition_plan(sections)
        events_types = [e["type"] for e in result["events"]]
        assert "pre_hook_silence_drop" not in events_types

    def test_verse_to_bridge_generates_bridge_strip(self):
        sections = [
            {"section_type": "verse", "bar_start": 0, "bars": 8, "energy": 0.5},
            {"section_type": "bridge", "bar_start": 8, "bars": 8, "energy": 0.4},
        ]
        result = build_transition_plan(sections)
        boundary_events = result["boundaries"][0]["events"]
        assert "bridge_strip" in boundary_events

    def test_hook_to_outro_generates_outro_strip(self):
        sections = [
            {"section_type": "hook", "bar_start": 0, "bars": 8, "energy": 0.9},
            {"section_type": "outro", "bar_start": 8, "bars": 8, "energy": 0.3},
        ]
        result = build_transition_plan(sections)
        all_event_types = [e["type"] for e in result["events"]]
        assert "outro_strip" in all_event_types

    def test_no_stem_metadata_stems_exist_is_false(self):
        sections = [
            {"section_type": "verse", "bar_start": 0, "bars": 8, "energy": 0.5},
            {"section_type": "hook", "bar_start": 8, "bars": 8, "energy": 0.9},
        ]
        result = build_transition_plan(sections, stem_metadata=None)
        if result["boundaries"]:
            assert result["boundaries"][0]["stem_primary"] is False

    def test_stems_not_enabled_stems_exist_is_false(self):
        sections = [
            {"section_type": "verse", "bar_start": 0, "bars": 8, "energy": 0.5},
            {"section_type": "hook", "bar_start": 8, "bars": 8, "energy": 0.9},
        ]
        meta = {"enabled": False, "succeeded": True}
        result = build_transition_plan(sections, stem_metadata=meta)
        if result["boundaries"]:
            assert result["boundaries"][0]["stem_primary"] is False

    def test_chorus_alias_treated_as_hook(self):
        """A section_type of 'chorus' must produce hook boundary events."""
        sections = [
            {"section_type": "verse", "bar_start": 0, "bars": 8, "energy": 0.5},
            {"section_type": "chorus", "bar_start": 8, "bars": 8, "energy": 0.9},
        ]
        result = build_transition_plan(sections)
        boundaries = result["boundaries"]
        assert any("hook" in b["boundary"] for b in boundaries)

    def test_events_list_matches_flattened_events(self):
        """boundary['events'] must be the union of before/on_downbeat/end_of_section."""
        sections = [
            {"section_type": "verse", "bar_start": 0, "bars": 8, "energy": 0.5,
             "active_stem_roles": ["drums", "bass"]},
            {"section_type": "hook", "bar_start": 8, "bars": 8, "energy": 0.9,
             "active_stem_roles": ["drums", "bass", "fx"]},
        ]
        result = build_transition_plan(sections)
        for boundary in result["boundaries"]:
            expected = [
                *boundary["before_section"],
                *boundary["on_downbeat"],
                *boundary["end_of_section"],
            ]
            assert boundary["events"] == expected

    def test_verse_to_non_hook_non_bridge_non_outro_no_boundary(self):
        """verse → verse transition produces no boundary events."""
        sections = [
            {"section_type": "verse", "bar_start": 0, "bars": 8, "energy": 0.5},
            {"section_type": "verse", "bar_start": 8, "bars": 8, "energy": 0.5},
        ]
        result = build_transition_plan(sections)
        assert result["boundaries"] == []
        assert result["events"] == []

    def test_energy_curve_field_stored_in_boundary(self):
        sections = [
            {"section_type": "verse", "bar_start": 0, "bars": 8, "energy": 0.5},
            {"section_type": "hook", "bar_start": 8, "bars": 8, "energy": 0.9},
        ]
        result = build_transition_plan(sections)
        for boundary in result["boundaries"]:
            ec = boundary["energy_curve"]
            assert "from" in ec
            assert "to" in ec
            assert "delta" in ec


# ===========================================================================
# TransitionEngine.create_transition
# ===========================================================================

class TestTransitionEngineCreateTransition:
    def test_riser_returns_audio_segment(self):
        audio = TransitionEngine.create_transition(
            TransitionType.RISER, duration_ms=500, intensity=0.5
        )
        assert isinstance(audio, AudioSegment)

    def test_impact_returns_audio_segment(self):
        audio = TransitionEngine.create_transition(
            TransitionType.IMPACT, duration_ms=200, intensity=0.8
        )
        assert isinstance(audio, AudioSegment)

    def test_silence_drop_returns_audio_segment(self):
        audio = TransitionEngine.create_transition(
            TransitionType.SILENCE_DROP, duration_ms=500
        )
        assert isinstance(audio, AudioSegment)

    def test_unknown_type_returns_silence(self):
        """A transition type not handled explicitly falls back to silence."""
        audio = TransitionEngine.create_transition(
            TransitionType.CROSSFADE, duration_ms=1000
        )
        assert isinstance(audio, AudioSegment)
        assert len(audio) > 0

    def test_riser_duration_approximately_correct(self):
        audio = TransitionEngine.create_transition(
            TransitionType.RISER, duration_ms=1000, intensity=0.5
        )
        assert 900 <= len(audio) <= 1100  # within 10% of requested duration

    def test_zero_intensity_does_not_crash(self):
        audio = TransitionEngine.create_transition(
            TransitionType.RISER, duration_ms=500, intensity=0.0
        )
        assert isinstance(audio, AudioSegment)

    def test_max_intensity_does_not_crash(self):
        audio = TransitionEngine.create_transition(
            TransitionType.IMPACT, duration_ms=500, intensity=1.0
        )
        assert isinstance(audio, AudioSegment)


# ===========================================================================
# TransitionEngine.apply_transition_before_section
# ===========================================================================

class TestApplyTransitionBeforeSection:
    def _make_transition(self, ttype=TransitionType.RISER, duration=1.0, intensity=0.5):
        """Create a mock Transition with the attributes the engine uses."""
        t = MagicMock()
        t.transition_type = ttype
        t.duration = duration
        t.intensity = intensity
        return t

    def test_returns_audio_segment(self):
        base = AudioSegment.silent(duration=4000)
        transition = self._make_transition()
        result = TransitionEngine.apply_transition_before_section(base, transition)
        assert isinstance(result, AudioSegment)

    def test_output_same_length_as_base(self):
        base = AudioSegment.silent(duration=4000)
        transition = self._make_transition()
        result = TransitionEngine.apply_transition_before_section(base, transition)
        assert len(result) == len(base)
