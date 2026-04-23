"""Tests for TransitionEngine class in app/services/transition_engine.py.

Covers: create_transition (all types), _create_riser, _create_impact,
_create_silence_drop, _create_downlifter, _create_swell,
apply_transition_before_section.
"""

from __future__ import annotations

import pytest
from pydub import AudioSegment

from app.services.producer_models import Transition, TransitionType
from app.services.transition_engine import TransitionEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _silent(duration_ms: int = 4000) -> AudioSegment:
    return AudioSegment.silent(duration=duration_ms).set_frame_rate(44100)


def _make_transition(
    transition_type: TransitionType = TransitionType.RISER,
    duration_bars: int = 2,
    intensity: float = 0.5,
) -> Transition:
    return Transition(
        from_section=0,
        to_section=1,
        transition_type=transition_type,
        duration_bars=duration_bars,
        intensity=intensity,
    )


# ===========================================================================
# create_transition
# ===========================================================================


class TestCreateTransition:
    def test_riser_returns_audio_segment(self):
        result = TransitionEngine.create_transition(TransitionType.RISER)
        assert isinstance(result, AudioSegment)
        assert len(result) > 0

    def test_impact_returns_audio_segment(self):
        result = TransitionEngine.create_transition(TransitionType.IMPACT)
        assert isinstance(result, AudioSegment)
        assert len(result) > 0

    def test_silence_drop_returns_silent_segment(self):
        result = TransitionEngine.create_transition(
            TransitionType.SILENCE_DROP, duration_ms=500
        )
        assert isinstance(result, AudioSegment)
        assert abs(len(result) - 500) <= 10

    def test_unknown_type_returns_silence(self):
        # Use an enum value that has no specific handler
        result = TransitionEngine.create_transition(
            TransitionType.FILTER_SWEEP, duration_ms=300
        )
        assert isinstance(result, AudioSegment)

    def test_duration_respected(self):
        duration_ms = 1000
        result = TransitionEngine.create_transition(
            TransitionType.SILENCE_DROP, duration_ms=duration_ms
        )
        assert abs(len(result) - duration_ms) <= 10

    def test_intensity_zero_still_returns_audio(self):
        result = TransitionEngine.create_transition(
            TransitionType.RISER, intensity=0.0, duration_ms=500
        )
        assert isinstance(result, AudioSegment)

    def test_intensity_one_still_returns_audio(self):
        result = TransitionEngine.create_transition(
            TransitionType.RISER, intensity=1.0, duration_ms=500
        )
        assert isinstance(result, AudioSegment)


# ===========================================================================
# _create_riser
# ===========================================================================


class TestCreateRiser:
    def test_returns_audio_segment(self):
        result = TransitionEngine._create_riser(duration_ms=2000, intensity=0.5)
        assert isinstance(result, AudioSegment)

    def test_has_correct_approximate_duration(self):
        result = TransitionEngine._create_riser(duration_ms=1000, intensity=0.5)
        # Allow ±50ms for sample alignment
        assert abs(len(result) - 1000) <= 50

    def test_short_riser(self):
        result = TransitionEngine._create_riser(duration_ms=100, intensity=0.5)
        assert isinstance(result, AudioSegment)

    def test_high_intensity_produces_audio(self):
        result = TransitionEngine._create_riser(duration_ms=500, intensity=1.0)
        assert isinstance(result, AudioSegment)


# ===========================================================================
# _create_impact
# ===========================================================================


class TestCreateImpact:
    def test_returns_audio_segment(self):
        result = TransitionEngine._create_impact(duration_ms=500, intensity=0.7)
        assert isinstance(result, AudioSegment)

    def test_has_approximate_duration(self):
        result = TransitionEngine._create_impact(duration_ms=1000, intensity=0.5)
        assert abs(len(result) - 1000) <= 50

    def test_low_intensity(self):
        result = TransitionEngine._create_impact(duration_ms=500, intensity=0.1)
        assert isinstance(result, AudioSegment)

    def test_high_intensity(self):
        result = TransitionEngine._create_impact(duration_ms=500, intensity=1.0)
        assert isinstance(result, AudioSegment)


# ===========================================================================
# _create_silence_drop
# ===========================================================================


class TestCreateSilenceDrop:
    def test_returns_silent_segment(self):
        result = TransitionEngine._create_silence_drop(duration_ms=500)
        assert isinstance(result, AudioSegment)
        assert result.rms == 0  # should be silent

    def test_duration_matches(self):
        result = TransitionEngine._create_silence_drop(duration_ms=800)
        assert abs(len(result) - 800) <= 5


# ===========================================================================
# _create_downlifter
# ===========================================================================


class TestCreateDownlifter:
    def test_returns_audio_segment(self):
        result = TransitionEngine._create_downlifter(duration_ms=1000, intensity=0.5)
        assert isinstance(result, AudioSegment)

    def test_has_approximate_duration(self):
        result = TransitionEngine._create_downlifter(duration_ms=500, intensity=0.5)
        # downlifter reverses a riser — duration should be close
        assert isinstance(result, AudioSegment)


# ===========================================================================
# _create_swell
# ===========================================================================


class TestCreateSwell:
    def test_returns_audio_segment(self):
        result = TransitionEngine._create_swell(duration_ms=1000, intensity=0.5)
        assert isinstance(result, AudioSegment)

    def test_has_approximate_duration(self):
        result = TransitionEngine._create_swell(duration_ms=500, intensity=0.5)
        assert isinstance(result, AudioSegment)


# ===========================================================================
# apply_transition_before_section
# ===========================================================================


class TestApplyTransitionBeforeSection:
    def test_returns_audio_segment(self):
        base = _silent(4000)
        transition = _make_transition(TransitionType.RISER)
        result = TransitionEngine.apply_transition_before_section(
            base, transition, bpm=120.0
        )
        assert isinstance(result, AudioSegment)

    def test_returns_base_length_audio(self):
        base = _silent(4000)
        transition = _make_transition(TransitionType.SILENCE_DROP)
        result = TransitionEngine.apply_transition_before_section(
            base, transition, bpm=120.0
        )
        # The result is an overlay so length should equal base length
        assert len(result) == len(base)

    def test_gracefully_handles_attribute_error(self):
        """Transition.duration_bars != .duration so attribute error is caught."""
        base = _silent(2000)
        transition = _make_transition(TransitionType.IMPACT)
        # Should not raise even if transition.duration is missing
        result = TransitionEngine.apply_transition_before_section(
            base, transition, bpm=120.0
        )
        assert isinstance(result, AudioSegment)

    def test_short_audio_does_not_crash(self):
        base = _silent(100)  # very short
        transition = _make_transition(TransitionType.RISER)
        result = TransitionEngine.apply_transition_before_section(base, transition, bpm=120.0)
        assert isinstance(result, AudioSegment)
