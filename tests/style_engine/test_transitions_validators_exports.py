"""Tests for style_engine modules with 0% coverage:
- app/style_engine/transitions.py
- app/style_engine/validators.py
- app/style_engine/export_midi.py
- app/style_engine/export_stems.py
"""

import random

import pytest

from app.style_engine.transitions import TransitionEvent, generate_transitions
from app.style_engine.validators import (
    ALLOWED_PARAM_KEYS,
    validate_style_overrides,
    validate_variation_count,
)
from app.style_engine.export_midi import maybe_export_midi
from app.style_engine.export_stems import maybe_export_stems


# ===========================================================================
# TransitionEvent dataclass
# ===========================================================================


class TestTransitionEvent:
    def test_creation_stores_fields(self):
        event = TransitionEvent(section_index=2, kind="riser", intensity=0.7)
        assert event.section_index == 2
        assert event.kind == "riser"
        assert event.intensity == 0.7

    def test_frozen_prevents_mutation(self):
        event = TransitionEvent(section_index=0, kind="fill", intensity=0.5)
        with pytest.raises(Exception):
            event.kind = "riser"  # type: ignore[misc]

    def test_equality_by_value(self):
        a = TransitionEvent(section_index=1, kind="drop_fx", intensity=0.3)
        b = TransitionEvent(section_index=1, kind="drop_fx", intensity=0.3)
        assert a == b

    def test_inequality(self):
        a = TransitionEvent(section_index=1, kind="riser", intensity=0.3)
        b = TransitionEvent(section_index=2, kind="riser", intensity=0.3)
        assert a != b

    def test_hashable(self):
        event = TransitionEvent(section_index=0, kind="fill", intensity=0.5)
        s = {event}  # must not raise
        assert event in s


# ===========================================================================
# generate_transitions
# ===========================================================================


class TestGenerateTransitions:
    def _rng(self, seed: int = 42) -> random.Random:
        return random.Random(seed)

    def test_returns_tuple(self):
        result = generate_transitions(self._rng(), section_count=4, fx_intensity=0.5)
        assert isinstance(result, tuple)

    def test_zero_sections_returns_empty(self):
        result = generate_transitions(self._rng(), section_count=0, fx_intensity=0.5)
        assert result == ()

    def test_one_section_returns_empty(self):
        result = generate_transitions(self._rng(), section_count=1, fx_intensity=0.5)
        assert result == ()

    def test_events_have_valid_kinds(self):
        rng = random.Random(0)
        result = generate_transitions(rng, section_count=10, fx_intensity=1.0)
        for event in result:
            assert event.kind in {"riser", "fill", "drop_fx"}

    def test_events_section_indices_in_range(self):
        section_count = 6
        result = generate_transitions(self._rng(), section_count=section_count, fx_intensity=0.8)
        for event in result:
            assert 0 <= event.section_index < section_count - 1

    def test_intensity_clamps_below_zero(self):
        """Negative fx_intensity must be clamped to 0.0."""
        rng = random.Random(99)
        result_neg = generate_transitions(rng, section_count=5, fx_intensity=-10.0)
        rng2 = random.Random(99)
        result_zero = generate_transitions(rng2, section_count=5, fx_intensity=0.0)
        assert result_neg == result_zero

    def test_intensity_clamps_above_one(self):
        """fx_intensity > 1.0 must be clamped to 1.0."""
        rng = random.Random(7)
        result_high = generate_transitions(rng, section_count=5, fx_intensity=5.0)
        rng2 = random.Random(7)
        result_one = generate_transitions(rng2, section_count=5, fx_intensity=1.0)
        assert result_high == result_one

    def test_deterministic_with_same_seed(self):
        result_a = generate_transitions(random.Random(42), section_count=8, fx_intensity=0.6)
        result_b = generate_transitions(random.Random(42), section_count=8, fx_intensity=0.6)
        assert result_a == result_b

    def test_high_intensity_increases_event_probability(self):
        """High fx_intensity (close to 1.0) should generally produce more events."""
        trials = 100
        high_count = sum(
            len(generate_transitions(random.Random(i), section_count=20, fx_intensity=1.0))
            for i in range(trials)
        )
        low_count = sum(
            len(generate_transitions(random.Random(i), section_count=20, fx_intensity=0.0))
            for i in range(trials)
        )
        assert high_count > low_count

    def test_intensity_stored_on_event(self):
        rng = random.Random(42)
        result = generate_transitions(rng, section_count=10, fx_intensity=0.8)
        for event in result:
            assert event.intensity == 0.8


# ===========================================================================
# validate_style_overrides
# ===========================================================================


class TestValidateStyleOverrides:
    def test_none_returns_empty_dict(self):
        assert validate_style_overrides(None) == {}

    def test_empty_dict_returns_empty_dict(self):
        assert validate_style_overrides({}) == {}

    def test_unknown_key_is_dropped(self):
        result = validate_style_overrides({"unknown_key": 0.5})
        assert "unknown_key" not in result

    def test_known_keys_are_kept(self):
        overrides = {key: 0.5 for key in ALLOWED_PARAM_KEYS}
        result = validate_style_overrides(overrides)
        assert set(result.keys()) == ALLOWED_PARAM_KEYS

    def test_tempo_multiplier_clamps_below(self):
        result = validate_style_overrides({"tempo_multiplier": 0.0})
        assert result["tempo_multiplier"] == 0.5

    def test_tempo_multiplier_clamps_above(self):
        result = validate_style_overrides({"tempo_multiplier": 99.0})
        assert result["tempo_multiplier"] == 1.5

    def test_tempo_multiplier_within_range_unchanged(self):
        result = validate_style_overrides({"tempo_multiplier": 1.0})
        assert result["tempo_multiplier"] == 1.0

    def test_other_param_clamps_below_zero(self):
        result = validate_style_overrides({"drum_density": -5.0})
        assert result["drum_density"] == 0.0

    def test_other_param_clamps_above_one(self):
        result = validate_style_overrides({"swing": 3.0})
        assert result["swing"] == 1.0

    def test_other_param_within_range_unchanged(self):
        result = validate_style_overrides({"aggression": 0.75})
        assert result["aggression"] == 0.75

    def test_mixed_known_and_unknown_keys(self):
        result = validate_style_overrides({"swing": 0.5, "bad_key": 0.9, "drum_density": 0.3})
        assert "bad_key" not in result
        assert result["swing"] == 0.5
        assert result["drum_density"] == 0.3

    def test_string_value_converted_to_float(self):
        result = validate_style_overrides({"swing": "0.6"})
        assert isinstance(result["swing"], float)
        assert result["swing"] == 0.6

    def test_all_allowed_keys_present_in_module(self):
        expected = {
            "tempo_multiplier",
            "drum_density",
            "hat_roll_probability",
            "glide_probability",
            "swing",
            "aggression",
            "melody_complexity",
            "fx_intensity",
        }
        assert ALLOWED_PARAM_KEYS == expected


# ===========================================================================
# validate_variation_count
# ===========================================================================


class TestValidateVariationCount:
    def test_disabled_always_returns_one(self):
        assert validate_variation_count(0, enabled=False) == 1
        assert validate_variation_count(5, enabled=False) == 1
        assert validate_variation_count(3, enabled=False) == 1

    def test_enabled_clamps_below_one(self):
        assert validate_variation_count(0, enabled=True) == 1

    def test_enabled_clamps_above_three(self):
        assert validate_variation_count(10, enabled=True) == 3

    def test_enabled_valid_values(self):
        assert validate_variation_count(1, enabled=True) == 1
        assert validate_variation_count(2, enabled=True) == 2
        assert validate_variation_count(3, enabled=True) == 3

    def test_enabled_negative_count_clamps_to_one(self):
        assert validate_variation_count(-5, enabled=True) == 1


# ===========================================================================
# maybe_export_midi
# ===========================================================================


class TestMaybeExportMidi:
    def test_disabled_returns_none(self):
        assert maybe_export_midi(feature_enabled=False) is None

    def test_enabled_returns_none_placeholder(self):
        assert maybe_export_midi(feature_enabled=True) is None

    def test_disabled_logs_skipped(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="app.style_engine.export_midi"):
            maybe_export_midi(feature_enabled=False)
        assert any("skipped" in r.message for r in caplog.records)

    def test_enabled_logs_executed(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="app.style_engine.export_midi"):
            maybe_export_midi(feature_enabled=True)
        assert any("executed" in r.message for r in caplog.records)


# ===========================================================================
# maybe_export_stems
# ===========================================================================


class TestMaybeExportStems:
    def test_disabled_returns_none(self):
        assert maybe_export_stems(feature_enabled=False) is None

    def test_enabled_returns_none_placeholder(self):
        assert maybe_export_stems(feature_enabled=True) is None

    def test_disabled_logs_skipped(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="app.style_engine.export_stems"):
            maybe_export_stems(feature_enabled=False)
        assert any("skipped" in r.message for r in caplog.records)

    def test_enabled_logs_executed(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="app.style_engine.export_stems"):
            maybe_export_stems(feature_enabled=True)
        assert any("executed" in r.message for r in caplog.records)
