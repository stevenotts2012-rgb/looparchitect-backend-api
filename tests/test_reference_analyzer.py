"""
Unit tests for the Reference Audio Analyzer (Phase 2).

Tests cover:
- Section segmentation helpers
- Energy profile computation
- Edge cases: short audio, long audio, low-dynamics, fallback behavior
- Confidence scoring
- Section type classification
"""

from __future__ import annotations

import math
import struct
import wave
from io import BytesIO
from typing import List
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: synthetic audio generation
# ---------------------------------------------------------------------------


def _make_sine_wav(
    duration_sec: float,
    sample_rate: int = 22050,
    amplitude: float = 0.5,
    freq_hz: float = 440.0,
) -> bytes:
    """Return raw bytes of a WAV file containing a sine wave."""
    n_samples = int(duration_sec * sample_rate)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            sample = amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate)
            packed = struct.pack("<h", int(sample * 32767))
            wf.writeframes(packed)
    return buf.getvalue()


def _make_silent_wav(duration_sec: float, sample_rate: int = 22050) -> bytes:
    """Return raw bytes of a silent WAV file."""
    return _make_sine_wav(duration_sec, sample_rate, amplitude=0.0)


def _make_varying_energy_wav(
    duration_sec: float, sample_rate: int = 22050
) -> bytes:
    """Return a WAV with clearly varying energy: loud first half, quiet second half."""
    n_samples = int(duration_sec * sample_rate)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        half = n_samples // 2
        for i in range(n_samples):
            amp = 0.8 if i < half else 0.1
            sample = amp * math.sin(2 * math.pi * 440.0 * i / sample_rate)
            wf.writeframes(struct.pack("<h", int(sample * 32767)))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------

try:
    import librosa  # type: ignore  # noqa: F401
    import numpy  # type: ignore  # noqa: F401
    _LIBROSA_AVAILABLE = True
except ImportError:
    _LIBROSA_AVAILABLE = False

from app.services.reference_analyzer import ReferenceAnalyzer, _WINDOW_SECONDS, _HOP_SECONDS


# ---------------------------------------------------------------------------
# Tests: ReferenceAnalyzer helpers (pure-Python, no librosa required)
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_all_equal_values(self):
        analyzer = ReferenceAnalyzer()
        result = analyzer._normalize([0.5, 0.5, 0.5])
        assert result == [0.5, 0.5, 0.5]

    def test_zero_to_one(self):
        analyzer = ReferenceAnalyzer()
        result = analyzer._normalize([0.0, 0.5, 1.0])
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(0.5)
        assert result[2] == pytest.approx(1.0)

    def test_empty_list(self):
        analyzer = ReferenceAnalyzer()
        assert analyzer._normalize([]) == []

    def test_single_value(self):
        analyzer = ReferenceAnalyzer()
        result = analyzer._normalize([0.3])
        assert result == [0.3]


class TestClassifySection:
    def _classify(self, index, n, energy, density, duration, total):
        return ReferenceAnalyzer._classify_section(
            index=index, n_sections=n, energy=energy, density=density,
            duration=duration, total_duration=total,
        )

    def test_first_section_is_intro(self):
        assert self._classify(0, 5, 0.3, 0.3, 30.0, 150.0) == "intro"

    def test_last_section_is_outro(self):
        assert self._classify(4, 5, 0.3, 0.3, 30.0, 150.0) == "outro"

    def test_high_energy_density_is_hook(self):
        result = self._classify(2, 6, 0.85, 0.75, 30.0, 180.0)
        assert result == "hook"

    def test_low_energy_density_is_breakdown(self):
        result = self._classify(2, 6, 0.2, 0.2, 30.0, 180.0)
        assert result == "breakdown"

    def test_default_is_verse(self):
        result = self._classify(2, 6, 0.5, 0.5, 30.0, 180.0)
        assert result == "verse"


class TestSectionConfidence:
    def test_normal_section_has_good_confidence(self):
        conf = ReferenceAnalyzer._section_confidence(30.0, 180.0)
        assert conf >= 0.6

    def test_very_short_section_has_low_confidence(self):
        conf = ReferenceAnalyzer._section_confidence(2.0, 180.0)
        assert conf <= 0.35

    def test_very_long_section_has_medium_confidence(self):
        conf = ReferenceAnalyzer._section_confidence(100.0, 180.0)
        assert conf <= 0.55


class TestCombinedNovelty:
    def test_constant_energy_has_zero_novelty(self):
        energy = [0.5] * 10
        density = [0.5] * 10
        novelty = ReferenceAnalyzer._combined_novelty(energy, density)
        assert all(v == pytest.approx(0.0) for v in novelty)

    def test_step_change_has_high_novelty(self):
        energy = [0.0] * 5 + [1.0] * 5
        density = [0.0] * 5 + [1.0] * 5
        novelty = ReferenceAnalyzer._combined_novelty(energy, density)
        assert novelty[5] > 0.5

    def test_mismatched_lengths_handled(self):
        energy = [0.5] * 8
        density = [0.5] * 5
        novelty = ReferenceAnalyzer._combined_novelty(energy, density)
        assert len(novelty) == 8


class TestScoreConfidence:
    def test_insufficient_when_no_sections(self):
        analyzer = ReferenceAnalyzer()
        score, quality = analyzer._score_confidence([], [], 60.0, [])
        assert quality == "insufficient"
        assert score < 0.3

    def test_good_sections_medium_or_better(self):
        from app.schemas.reference_arrangement import ReferenceSection
        sections = [
            ReferenceSection(
                index=i, start_time_sec=i*30.0, end_time_sec=(i+1)*30.0,
                estimated_bars=8, section_type_guess="verse",
                energy_level=0.5, density_level=0.5,
                transition_in_strength=0.3, transition_out_strength=0.3,
                confidence=0.7,
            )
            for i in range(5)
        ]
        energy_curve = [0.2, 0.4, 0.6, 0.8, 0.6, 0.4, 0.3, 0.5]
        score, quality = ReferenceAnalyzer._score_confidence(sections, energy_curve, 150.0, [])
        assert quality in ("medium", "high")
        assert score >= 0.4

    def test_flat_energy_lowers_confidence(self):
        from app.schemas.reference_arrangement import ReferenceSection
        sections = [
            ReferenceSection(
                index=0, start_time_sec=0.0, end_time_sec=60.0,
                estimated_bars=16, section_type_guess="verse",
                energy_level=0.5, density_level=0.5,
                transition_in_strength=0.0, transition_out_strength=0.0,
                confidence=0.5,
            )
        ]
        # Completely flat energy
        energy_curve = [0.5] * 30
        warnings: List[str] = []
        score, quality = ReferenceAnalyzer._score_confidence(sections, energy_curve, 60.0, warnings)
        assert any("flat" in w.lower() or "dynamics" in w.lower() for w in warnings)
        # Flat energy should result in lower confidence score
        assert score < 0.45


class TestSegmentSections:
    def test_constant_energy_returns_at_least_two_sections(self):
        analyzer = ReferenceAnalyzer()
        energy = [0.5] * 20
        density = [0.5] * 20
        boundaries = analyzer._segment_sections(energy, density, 60.0, [])
        assert len(boundaries) >= 2
        assert boundaries[0] == 0.0
        assert boundaries[-1] == pytest.approx(60.0)

    def test_step_change_triggers_boundary(self):
        analyzer = ReferenceAnalyzer()
        # Sharp transition in the middle
        energy = [0.1] * 10 + [0.9] * 10
        density = [0.1] * 10 + [0.9] * 10
        boundaries = analyzer._segment_sections(energy, density, 40.0, [])
        # Should detect at least one boundary in the middle
        assert len(boundaries) >= 3

    def test_short_curve_returns_two_sections(self):
        analyzer = ReferenceAnalyzer()
        boundaries = analyzer._segment_sections([0.5, 0.6], [0.5, 0.6], 10.0, [])
        assert len(boundaries) == 2

    def test_too_many_sections_capped(self):
        from app.services.reference_analyzer import _MAX_SECTION_COUNT
        analyzer = ReferenceAnalyzer()
        # Create energy with many changes
        energy = [float(i % 2) for i in range(200)]
        density = [float(i % 2) for i in range(200)]
        warnings: List[str] = []
        boundaries = analyzer._segment_sections(energy, density, 400.0, warnings)
        assert len(boundaries) - 1 <= _MAX_SECTION_COUNT


# ---------------------------------------------------------------------------
# Tests: Full analysis pipeline (requires librosa)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LIBROSA_AVAILABLE, reason="librosa not installed")
class TestReferenceAnalyzerWithLibrosa:
    def test_analyze_short_audio_returns_insufficient(self):
        analyzer = ReferenceAnalyzer()
        short_wav = _make_sine_wav(5.0)  # 5 seconds — below minimum
        result = analyzer.analyze(short_wav, "short.wav")
        assert result.analysis_quality == "insufficient"
        assert len(result.analysis_warnings) > 0

    def test_analyze_normal_audio_returns_sections(self):
        analyzer = ReferenceAnalyzer()
        wav = _make_sine_wav(60.0)
        result = analyzer.analyze(wav, "test.wav")
        assert result.total_duration_sec > 0
        # A constant-amplitude sine wave may score low, but should still return sections
        assert len(result.sections) >= 2

    def test_analyze_varying_energy_detects_change(self):
        analyzer = ReferenceAnalyzer()
        wav = _make_varying_energy_wav(60.0)
        result = analyzer.analyze(wav, "test.wav")
        # Should find at least an intro and one more section
        assert len(result.sections) >= 2

    def test_analyze_silent_audio_returns_low_confidence(self):
        analyzer = ReferenceAnalyzer()
        wav = _make_silent_wav(30.0)
        result = analyzer.analyze(wav, "silent.wav")
        # Silent audio → low energy variance → low confidence
        assert result.analysis_confidence < 0.6

    def test_analyze_returns_valid_energy_curve(self):
        analyzer = ReferenceAnalyzer()
        wav = _make_sine_wav(30.0)
        result = analyzer.analyze(wav, "test.wav")
        assert len(result.energy_curve) > 0
        assert all(0.0 <= v <= 1.0 for v in result.energy_curve)

    def test_analyze_section_boundaries_are_ordered(self):
        analyzer = ReferenceAnalyzer()
        wav = _make_sine_wav(60.0)
        result = analyzer.analyze(wav, "test.wav")
        for i in range(1, len(result.sections)):
            prev = result.sections[i - 1]
            curr = result.sections[i]
            assert curr.start_time_sec >= prev.end_time_sec - 0.01

    def test_analyze_section_fields_in_range(self):
        analyzer = ReferenceAnalyzer()
        wav = _make_sine_wav(30.0)
        result = analyzer.analyze(wav, "test.wav")
        for sec in result.sections:
            assert 0.0 <= sec.energy_level <= 1.0
            assert 0.0 <= sec.density_level <= 1.0
            assert 0.0 <= sec.transition_in_strength <= 1.0
            assert 0.0 <= sec.transition_out_strength <= 1.0
            assert 0.0 <= sec.confidence <= 1.0
            assert sec.estimated_bars >= 1

    def test_analyze_long_audio_returns_warning(self):
        from app.services.reference_analyzer import _MAX_AUDIO_SECONDS
        analyzer = ReferenceAnalyzer()
        # Create audio slightly longer than limit
        long_wav = _make_sine_wav(_MAX_AUDIO_SECONDS + 10.0)
        result = analyzer.analyze(long_wav, "long.wav")
        assert any("exceeds" in w.lower() for w in result.analysis_warnings)

    def test_analyze_summary_is_non_empty(self):
        analyzer = ReferenceAnalyzer()
        wav = _make_sine_wav(30.0)
        result = analyzer.analyze(wav, "test.wav")
        assert len(result.summary) > 0

    def test_analyze_returns_structure_with_correct_types(self):
        from app.schemas.reference_arrangement import ReferenceStructure
        analyzer = ReferenceAnalyzer()
        wav = _make_sine_wav(30.0)
        result = analyzer.analyze(wav, "test.wav")
        assert isinstance(result, ReferenceStructure)

    def test_analyze_handles_bad_bytes_gracefully(self):
        analyzer = ReferenceAnalyzer()
        result = analyzer.analyze(b"not_audio_data", "bad.wav")
        # Should return fallback, not raise
        assert result.analysis_quality == "insufficient"


class TestReferenceAnalyzerFallback:
    def test_fallback_when_librosa_unavailable(self):
        with patch("app.services.reference_analyzer._check_librosa", return_value=False):
            analyzer = ReferenceAnalyzer()
            result = analyzer.analyze(b"bytes", "test.wav")
        assert result.analysis_quality == "insufficient"
        assert len(result.sections) == 0

    def test_fallback_structure_fields(self):
        analyzer = ReferenceAnalyzer()
        result = analyzer._fallback_structure(42.0, "test warning")
        assert result.total_duration_sec == pytest.approx(42.0)
        assert result.analysis_quality == "insufficient"
        assert "test warning" in result.analysis_warnings
