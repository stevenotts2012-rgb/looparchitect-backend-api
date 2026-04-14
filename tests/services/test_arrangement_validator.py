"""Unit tests for ArrangementValidator."""

from __future__ import annotations

import pytest

from app.services.arrangement_validator import ArrangementValidator
from app.services.producer_models import (
    EnergyPoint,
    InstrumentType,
    ProducerArrangement,
    Section,
    SectionType,
    Track,
    Variation,
    VariationType,
)

# Use correct VariationType member names
_FILL_VARIATION = VariationType.DRUM_FILL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_arrangement() -> ProducerArrangement:
    """Return a minimal arrangement that passes all validation rules."""
    arr = ProducerArrangement(
        tempo=120.0,
        key="C",
        total_bars=96,
        total_seconds=192.0,
        genre="trap",
    )
    arr.sections = [
        Section(
            name="Intro",
            section_type=SectionType.INTRO,
            bar_start=0,
            bars=8,
            energy_level=0.3,
            instruments=[InstrumentType.KICK, InstrumentType.HATS],
        ),
        Section(
            name="Verse 1",
            section_type=SectionType.VERSE,
            bar_start=8,
            bars=16,
            energy_level=0.5,
            instruments=[InstrumentType.KICK, InstrumentType.SNARE, InstrumentType.BASS],
        ),
        Section(
            name="Hook",
            section_type=SectionType.HOOK,
            bar_start=24,
            bars=8,
            energy_level=0.85,
            instruments=[
                InstrumentType.KICK,
                InstrumentType.SNARE,
                InstrumentType.BASS,
                InstrumentType.LEAD,
                InstrumentType.PAD,
            ],
        ),
        Section(
            name="Outro",
            section_type=SectionType.OUTRO,
            bar_start=32,
            bars=8,
            energy_level=0.2,
            instruments=[InstrumentType.KICK],
        ),
    ]
    arr.all_variations = [
        Variation(bar=6, section_index=0, variation_type=VariationType.DRUM_FILL, intensity=0.7)
    ]
    arr.energy_curve = [
        EnergyPoint(bar=0, energy=0.3),
        EnergyPoint(bar=8, energy=0.5),
        EnergyPoint(bar=24, energy=0.85),
        EnergyPoint(bar=32, energy=0.2),
    ]
    return arr


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


class TestArrangementValidatorValidate:
    def test_valid_arrangement_passes(self):
        arr = _make_valid_arrangement()
        is_valid, errors = ArrangementValidator.validate(arr)
        assert is_valid is True
        assert errors == []

    def test_too_few_sections_fails(self):
        arr = _make_valid_arrangement()
        arr.sections = arr.sections[:2]
        is_valid, errors = ArrangementValidator.validate(arr)
        assert is_valid is False
        assert any("at least 3 sections" in e for e in errors)

    def test_single_section_fails(self):
        arr = _make_valid_arrangement()
        arr.sections = arr.sections[:1]
        is_valid, errors = ArrangementValidator.validate(arr)
        assert is_valid is False

    def test_duration_too_short_fails(self):
        arr = _make_valid_arrangement()
        arr.total_seconds = 10.0
        is_valid, errors = ArrangementValidator.validate(arr)
        assert is_valid is False
        assert any("too short" in e.lower() for e in errors)

    def test_duration_exactly_at_minimum_passes(self):
        arr = _make_valid_arrangement()
        arr.total_seconds = 30.0
        is_valid, errors = ArrangementValidator.validate(arr)
        assert is_valid is True

    def test_hooks_lower_energy_than_other_sections_fails(self):
        arr = _make_valid_arrangement()
        # Flip: make hook energy lower than verses
        for s in arr.sections:
            if s.section_type == SectionType.HOOK:
                s.energy_level = 0.2
            elif s.section_type == SectionType.VERSE:
                s.energy_level = 0.9
        is_valid, errors = ArrangementValidator.validate(arr)
        assert is_valid is False
        assert any("energy" in e.lower() for e in errors)

    def test_hooks_equal_energy_passes(self):
        """Hook energy equal to others should still pass (not below)."""
        arr = _make_valid_arrangement()
        for s in arr.sections:
            s.energy_level = 0.5
        is_valid, errors = ArrangementValidator.validate(arr)
        # Equal, not strictly less, so no energy error
        assert not any("hooks should have highest energy" in e.lower() for e in errors)

    def test_verse_more_instruments_than_hook_fails(self):
        arr = _make_valid_arrangement()
        # Give verse more instruments than hook
        for s in arr.sections:
            if s.section_type == SectionType.VERSE:
                s.instruments = [
                    InstrumentType.KICK,
                    InstrumentType.SNARE,
                    InstrumentType.BASS,
                    InstrumentType.LEAD,
                    InstrumentType.PAD,
                    InstrumentType.VOCAL,
                ]
            elif s.section_type == SectionType.HOOK:
                s.instruments = [InstrumentType.KICK]
        is_valid, errors = ArrangementValidator.validate(arr)
        assert is_valid is False
        assert any("fewer instruments" in e.lower() for e in errors)

    def test_no_variations_fails(self):
        arr = _make_valid_arrangement()
        arr.all_variations = []
        is_valid, errors = ArrangementValidator.validate(arr)
        assert is_valid is False
        assert any("variation" in e.lower() for e in errors)

    def test_flat_energy_curve_fails(self):
        arr = _make_valid_arrangement()
        # Completely flat energy curve — range < 0.2
        arr.energy_curve = [
            EnergyPoint(bar=0, energy=0.5),
            EnergyPoint(bar=8, energy=0.55),
            EnergyPoint(bar=24, energy=0.52),
            EnergyPoint(bar=32, energy=0.51),
        ]
        is_valid, errors = ArrangementValidator.validate(arr)
        assert is_valid is False
        assert any("energy curve" in e.lower() for e in errors)

    def test_empty_energy_curve_does_not_crash(self):
        arr = _make_valid_arrangement()
        arr.energy_curve = []
        # Should not raise
        is_valid, errors = ArrangementValidator.validate(arr)
        # Validity depends on other rules; we only check it doesn't crash
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_no_hook_sections_no_energy_check(self):
        """Arrangements without hooks should not raise an energy comparison error."""
        arr = _make_valid_arrangement()
        for s in arr.sections:
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS):
                s.section_type = SectionType.VERSE
        is_valid, errors = ArrangementValidator.validate(arr)
        assert not any("hooks should have highest energy" in e.lower() for e in errors)

    def test_chorus_treated_as_hook_for_energy(self):
        """CHORUS sections should also be treated as high-energy sections."""
        arr = _make_valid_arrangement()
        for s in arr.sections:
            if s.section_type == SectionType.HOOK:
                s.section_type = SectionType.CHORUS
                s.energy_level = 0.9  # still high
        is_valid, errors = ArrangementValidator.validate(arr)
        assert not any("hooks should have highest energy" in e.lower() for e in errors)

    def test_returns_tuple(self):
        arr = _make_valid_arrangement()
        result = ArrangementValidator.validate(arr)
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# validate_and_raise()
# ---------------------------------------------------------------------------


class TestArrangementValidatorValidateAndRaise:
    def test_valid_arrangement_returns_arrangement(self):
        arr = _make_valid_arrangement()
        result = ArrangementValidator.validate_and_raise(arr)
        assert result is arr
        assert result.is_valid is True
        assert result.validation_errors == []

    def test_invalid_arrangement_raises_value_error(self):
        arr = _make_valid_arrangement()
        arr.sections = arr.sections[:1]  # too few sections
        with pytest.raises(ValueError, match="validation failed"):
            ArrangementValidator.validate_and_raise(arr)

    def test_error_message_contains_rule_details(self):
        arr = _make_valid_arrangement()
        arr.total_seconds = 5.0
        with pytest.raises(ValueError) as exc_info:
            ArrangementValidator.validate_and_raise(arr)
        assert "too short" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# get_validation_summary()
# ---------------------------------------------------------------------------


class TestArrangementValidatorGetSummary:
    def test_summary_keys_present(self):
        arr = _make_valid_arrangement()
        summary = ArrangementValidator.get_validation_summary(arr)

        expected_keys = {
            "is_valid",
            "errors",
            "sections_count",
            "total_bars",
            "total_seconds",
            "variations_count",
            "tracks_count",
            "hook_energy",
            "verse_energy",
            "hook_instruments",
            "verse_instruments",
        }
        assert expected_keys == set(summary.keys())

    def test_summary_valid_arrangement(self):
        arr = _make_valid_arrangement()
        summary = ArrangementValidator.get_validation_summary(arr)

        assert summary["is_valid"] is True
        assert summary["sections_count"] == len(arr.sections)
        assert summary["total_bars"] == arr.total_bars
        assert summary["total_seconds"] == arr.total_seconds
        assert summary["variations_count"] == len(arr.all_variations)
        assert summary["tracks_count"] == len(arr.tracks)

    def test_summary_hook_energy_computed(self):
        arr = _make_valid_arrangement()
        summary = ArrangementValidator.get_validation_summary(arr)

        hook_sections = [
            s for s in arr.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        expected_hook_energy = sum(s.energy_level for s in hook_sections) / len(hook_sections)
        assert abs(summary["hook_energy"] - round(expected_hook_energy, 2)) < 0.001

    def test_summary_no_hooks_returns_zero_hook_energy(self):
        arr = _make_valid_arrangement()
        for s in arr.sections:
            s.section_type = SectionType.VERSE
        summary = ArrangementValidator.get_validation_summary(arr)
        assert summary["hook_energy"] == 0.0

    def test_summary_invalid_arrangement(self):
        arr = _make_valid_arrangement()
        arr.sections = arr.sections[:2]  # too few
        summary = ArrangementValidator.get_validation_summary(arr)
        assert summary["is_valid"] is False
        assert len(summary["errors"]) > 0
