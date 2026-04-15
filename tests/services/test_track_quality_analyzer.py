"""
Unit tests for TrackQualityAnalyzer service.

Tests cover:
- Metadata extraction (sample rate, bit depth)
- Clipping detection (none / minor / severe)
- Mono compatibility (compatible / incompatible)
- Phase issue detection
- Stereo field classification (narrow / normal / wide)
- Integrated loudness approximation
- True peak computation
- Tonal profile (band status)
- Suggestion generation
- Full pipeline on synthetic WAV files
"""

from __future__ import annotations

import io
import math
import struct
import wave
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers: synthetic audio generation
# ---------------------------------------------------------------------------


def _make_stereo_wav(
    duration_sec: float = 2.0,
    sample_rate: int = 44100,
    amplitude_l: float = 0.5,
    amplitude_r: float = 0.5,
    freq_l: float = 440.0,
    freq_r: float = 440.0,
    phase_offset_r: float = 0.0,
) -> bytes:
    """Return raw bytes of a 16-bit stereo WAV with independent L/R sinusoids."""
    n_samples = int(duration_sec * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            left = amplitude_l * math.sin(2 * math.pi * freq_l * t)
            right = amplitude_r * math.sin(2 * math.pi * freq_r * t + phase_offset_r)
            packed = struct.pack("<hh", int(left * 32767), int(right * 32767))
            wf.writeframes(packed)
    return buf.getvalue()


def _make_mono_wav(
    duration_sec: float = 2.0,
    sample_rate: int = 44100,
    amplitude: float = 0.5,
    freq_hz: float = 440.0,
) -> bytes:
    """Return raw bytes of a 16-bit mono WAV."""
    n_samples = int(duration_sec * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            sample = amplitude * math.sin(2 * math.pi * freq_hz * t)
            wf.writeframes(struct.pack("<h", int(sample * 32767)))
    return buf.getvalue()


def _make_clipping_wav(clip_fraction: float = 0.01) -> bytes:
    """Return a stereo WAV where *clip_fraction* of samples are at full scale."""
    sr = 44100
    duration = 1.0
    n_samples = int(duration * sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        clip_count = int(n_samples * clip_fraction)
        for i in range(n_samples):
            # Alternate clipped samples at the start of the file
            val = 32767 if i < clip_count else int(0.3 * 32767)
            wf.writeframes(struct.pack("<hh", val, val))
    return buf.getvalue()


def _make_out_of_phase_wav(duration_sec: float = 2.0) -> bytes:
    """Return a stereo WAV where R channel is the polarity-inverted L channel."""
    sr = 44100
    n_samples = int(duration_sec * sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for i in range(n_samples):
            t = i / sr
            left = int(0.5 * math.sin(2 * math.pi * 440.0 * t) * 32767)
            right = -left  # polarity-inverted
            wf.writeframes(struct.pack("<hh", left, right))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Import guard — skip if librosa/numpy not available
# ---------------------------------------------------------------------------

try:
    import librosa  # type: ignore  # noqa: F401
    import numpy  # type: ignore  # noqa: F401
    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _DEPS_AVAILABLE,
    reason="librosa/numpy not installed — skipping track quality analyzer tests",
)


# ---------------------------------------------------------------------------
# Tests: internal helpers
# ---------------------------------------------------------------------------


class TestClippingDetection:
    def test_no_clipping_returns_none(self):
        from app.services.track_quality_analyzer import _detect_clipping
        import numpy as np

        y = np.sin(np.linspace(0, 2 * np.pi, 44100)) * 0.5
        assert _detect_clipping(y, None).value == "None"

    def test_minor_clipping_detected(self):
        from app.services.track_quality_analyzer import (
            _detect_clipping,
            _CLIP_MINOR_THRESHOLD,
        )
        import numpy as np

        y = np.ones(44100) * 0.3
        # Force a fraction above minor threshold to be clipped
        clip_count = int(44100 * (_CLIP_MINOR_THRESHOLD + 0.0002))
        y[:clip_count] = 0.9995  # above 0.999 threshold
        assert _detect_clipping(y, None).value == "Minor"

    def test_severe_clipping_detected(self):
        from app.services.track_quality_analyzer import (
            _detect_clipping,
            _CLIP_SEVERE_THRESHOLD,
        )
        import numpy as np

        y = np.ones(44100) * 0.3
        clip_count = int(44100 * (_CLIP_SEVERE_THRESHOLD + 0.001))
        y[:clip_count] = 1.0
        assert _detect_clipping(y, None).value == "Severe"

    def test_stereo_both_channels_considered(self):
        from app.services.track_quality_analyzer import (
            _detect_clipping,
            _CLIP_MINOR_THRESHOLD,
        )
        import numpy as np

        n = 44100
        y_l = np.zeros(n)
        y_r = np.zeros(n)
        # Clip enough samples across both channels combined to exceed the minor threshold.
        # Total samples = n * 2; we need clip_count / (n * 2) > _CLIP_MINOR_THRESHOLD.
        clip_count = int(n * 2 * (_CLIP_MINOR_THRESHOLD + 0.0002)) + 1
        y_r[:clip_count] = 1.0  # above 0.999 threshold
        result = _detect_clipping(y_l, y_r)
        assert result.value in ("Minor", "Severe")


class TestMonoCompatibility:
    def test_mono_file_is_always_compatible(self):
        from app.services.track_quality_analyzer import _compute_mono_compatibility
        import numpy as np

        y = np.sin(np.linspace(0, 2 * np.pi, 44100)) * 0.5
        assert _compute_mono_compatibility(y, None) is True

    def test_identical_channels_are_compatible(self):
        from app.services.track_quality_analyzer import _compute_mono_compatibility
        import numpy as np

        y = np.sin(np.linspace(0, 2 * np.pi, 44100)) * 0.5
        assert _compute_mono_compatibility(y, y.copy()) is True

    def test_inverted_channels_are_incompatible(self):
        from app.services.track_quality_analyzer import _compute_mono_compatibility
        import numpy as np

        y = np.sin(np.linspace(0, 2 * np.pi, 44100)) * 0.5
        # Out-of-phase: corr = -1, mono sum ≈ 0
        assert _compute_mono_compatibility(y, -y) is False


class TestPhaseIssues:
    def test_mono_file_no_phase_issues(self):
        from app.services.track_quality_analyzer import _detect_phase_issues
        import numpy as np

        y = np.sin(np.linspace(0, 2 * np.pi, 44100)) * 0.5
        assert _detect_phase_issues(y, None) is False

    def test_identical_channels_no_phase_issues(self):
        from app.services.track_quality_analyzer import _detect_phase_issues
        import numpy as np

        y = np.sin(np.linspace(0, 2 * np.pi, 44100)) * 0.5
        assert _detect_phase_issues(y, y.copy()) is False

    def test_inverted_channels_flag_phase_issues(self):
        from app.services.track_quality_analyzer import _detect_phase_issues
        import numpy as np

        y = np.sin(np.linspace(0, 2 * np.pi, 44100)) * 0.5
        assert _detect_phase_issues(y, -y) is True


class TestStereoField:
    def test_mono_file_returns_narrow(self):
        from app.services.track_quality_analyzer import _compute_stereo_field
        import numpy as np

        y = np.sin(np.linspace(0, 2 * np.pi, 44100)) * 0.5
        assert _compute_stereo_field(y, None).value == "Narrow"

    def test_identical_channels_is_narrow(self):
        from app.services.track_quality_analyzer import _compute_stereo_field
        import numpy as np

        y = np.sin(np.linspace(0, 2 * np.pi, 44100)) * 0.5
        # M = y*sqrt(2), S = 0 → ratio ≈ 0 → Narrow
        assert _compute_stereo_field(y, y.copy()).value == "Narrow"

    def test_uncorrelated_channels_gives_wide_field(self):
        from app.services.track_quality_analyzer import _compute_stereo_field
        import numpy as np

        rng = numpy.random.default_rng(42)
        y_l = rng.standard_normal(44100).astype(numpy.float32) * 0.5
        y_r = rng.standard_normal(44100).astype(numpy.float32) * 0.5
        result = _compute_stereo_field(y_l, y_r)
        assert result.value in ("Normal", "Wide")


class TestIntegratedLoudness:
    def test_silent_signal_returns_floor(self):
        from app.services.track_quality_analyzer import _compute_integrated_loudness
        import numpy as np

        y = np.zeros(44100)
        lufs = _compute_integrated_loudness(y, None, 44100)
        assert lufs <= -70.0

    def test_louder_signal_gives_higher_lufs(self):
        from app.services.track_quality_analyzer import _compute_integrated_loudness
        import numpy as np

        t = np.linspace(0, 5, 44100 * 5)
        y_quiet = np.sin(2 * np.pi * 440 * t) * 0.1
        y_loud = np.sin(2 * np.pi * 440 * t) * 0.9
        lufs_quiet = _compute_integrated_loudness(y_quiet, None, 44100)
        lufs_loud = _compute_integrated_loudness(y_loud, None, 44100)
        assert lufs_loud > lufs_quiet

    def test_returns_float(self):
        from app.services.track_quality_analyzer import _compute_integrated_loudness
        import numpy as np

        t = np.linspace(0, 2, 44100 * 2)
        y = np.sin(2 * np.pi * 440 * t) * 0.5
        result = _compute_integrated_loudness(y, None, 44100)
        assert isinstance(result, float)


class TestTruePeak:
    def test_silent_returns_low_value(self):
        from app.services.track_quality_analyzer import _compute_true_peak
        import numpy as np

        y = np.zeros(1000)
        assert _compute_true_peak(y, None) <= -100.0

    def test_full_scale_returns_zero(self):
        from app.services.track_quality_analyzer import _compute_true_peak
        import numpy as np

        y = np.ones(1000)
        assert _compute_true_peak(y, None) == pytest.approx(0.0, abs=0.1)

    def test_half_amplitude_returns_minus_six(self):
        from app.services.track_quality_analyzer import _compute_true_peak
        import numpy as np

        y = np.ones(1000) * 0.5
        assert _compute_true_peak(y, None) == pytest.approx(-6.02, abs=0.1)


# ---------------------------------------------------------------------------
# Tests: full pipeline on synthetic WAV files
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_mono_wav_analysis(self):
        from app.services.track_quality_analyzer import TrackQualityAnalyzer
        from app.schemas.track_quality import TrackQualityAnalysisResponse

        wav_bytes = _make_mono_wav(duration_sec=3.0, amplitude=0.5)
        analyzer = TrackQualityAnalyzer()
        result = analyzer.analyze(wav_bytes, "test_mono.wav")

        assert isinstance(result, TrackQualityAnalysisResponse)
        assert result.sample_rate == 44100
        assert result.bit_depth == 16
        assert result.clipping.value == "None"
        # Mono file → always compatible
        assert result.mono_compatibility is True
        assert result.phase_issues is False
        assert result.stereo_field.value == "Narrow"
        assert result.integrated_loudness < 0.0
        assert result.true_peak < 0.0
        assert result.analysis_version == "1.0.0"

    def test_stereo_in_phase_wav(self):
        from app.services.track_quality_analyzer import TrackQualityAnalyzer
        from app.schemas.track_quality import TrackQualityAnalysisResponse

        wav_bytes = _make_stereo_wav(
            duration_sec=3.0, amplitude_l=0.5, amplitude_r=0.5
        )
        analyzer = TrackQualityAnalyzer()
        result = analyzer.analyze(wav_bytes, "test_stereo.wav")

        assert isinstance(result, TrackQualityAnalysisResponse)
        assert result.sample_rate == 44100
        assert result.clipping.value == "None"
        assert result.phase_issues is False

    def test_out_of_phase_stereo_flags_issues(self):
        from app.services.track_quality_analyzer import TrackQualityAnalyzer

        wav_bytes = _make_out_of_phase_wav(duration_sec=3.0)
        analyzer = TrackQualityAnalyzer()
        result = analyzer.analyze(wav_bytes, "out_of_phase.wav")

        # Polarity-inverted channels should fail mono compatibility and flag phase
        assert result.mono_compatibility is False
        assert result.phase_issues is True

    def test_clipping_wav_detected(self):
        from app.services.track_quality_analyzer import TrackQualityAnalyzer

        wav_bytes = _make_clipping_wav(clip_fraction=0.005)  # 0.5 % → Severe
        analyzer = TrackQualityAnalyzer()
        result = analyzer.analyze(wav_bytes, "clipping.wav")

        assert result.clipping.value == "Severe"

    def test_suggestions_present_for_quiet_track(self):
        from app.services.track_quality_analyzer import TrackQualityAnalyzer

        # Very low amplitude → quiet loudness → loudness + compression suggestions
        wav_bytes = _make_mono_wav(duration_sec=5.0, amplitude=0.01)
        analyzer = TrackQualityAnalyzer()
        result = analyzer.analyze(wav_bytes, "quiet.wav")

        categories = [s.category for s in result.suggestions]
        assert "loudness" in categories

    def test_response_has_tonal_profile(self):
        from app.services.track_quality_analyzer import TrackQualityAnalyzer

        wav_bytes = _make_mono_wav(duration_sec=2.0, amplitude=0.5)
        analyzer = TrackQualityAnalyzer()
        result = analyzer.analyze(wav_bytes, "track.wav")

        tp = result.tonal_profile
        assert tp.low.value in ("Too High", "Too Low", "Optimal")
        assert tp.low_mid.value in ("Too High", "Too Low", "Optimal")
        assert tp.mid.value in ("Too High", "Too Low", "Optimal")
        assert tp.high.value in ("Too High", "Too Low", "Optimal")


# ---------------------------------------------------------------------------
# Tests: suggestion generation
# ---------------------------------------------------------------------------


class TestSuggestionGeneration:
    def test_compression_suggested_for_high_dynamic_range(self):
        from app.services.track_quality_analyzer import _generate_suggestions
        from app.schemas.track_quality import (
            StereoFieldWidth,
            TonalBandStatus,
            TonalProfile,
        )

        tonal = TonalProfile(
            low=TonalBandStatus.OPTIMAL,
            low_mid=TonalBandStatus.OPTIMAL,
            mid=TonalBandStatus.OPTIMAL,
            high=TonalBandStatus.OPTIMAL,
        )
        # 20 dB dynamic range → triggers compression suggestion
        suggestions = _generate_suggestions(-20.0, 0.0, True, StereoFieldWidth.NORMAL, tonal)
        categories = [s.category for s in suggestions]
        assert "compression" in categories

    def test_loudness_suggested_when_too_quiet(self):
        from app.services.track_quality_analyzer import _generate_suggestions
        from app.schemas.track_quality import (
            StereoFieldWidth,
            TonalBandStatus,
            TonalProfile,
        )

        tonal = TonalProfile(
            low=TonalBandStatus.OPTIMAL,
            low_mid=TonalBandStatus.OPTIMAL,
            mid=TonalBandStatus.OPTIMAL,
            high=TonalBandStatus.OPTIMAL,
        )
        suggestions = _generate_suggestions(-25.0, -10.0, True, StereoFieldWidth.NORMAL, tonal)
        categories = [s.category for s in suggestions]
        assert "loudness" in categories

    def test_mono_compat_suggested_when_incompatible(self):
        from app.services.track_quality_analyzer import _generate_suggestions
        from app.schemas.track_quality import (
            StereoFieldWidth,
            TonalBandStatus,
            TonalProfile,
        )

        tonal = TonalProfile(
            low=TonalBandStatus.OPTIMAL,
            low_mid=TonalBandStatus.OPTIMAL,
            mid=TonalBandStatus.OPTIMAL,
            high=TonalBandStatus.OPTIMAL,
        )
        suggestions = _generate_suggestions(-14.0, -1.0, False, StereoFieldWidth.NORMAL, tonal)
        categories = [s.category for s in suggestions]
        assert "mono_compatibility" in categories

    def test_stereo_field_suggested_when_narrow(self):
        from app.services.track_quality_analyzer import _generate_suggestions
        from app.schemas.track_quality import (
            StereoFieldWidth,
            TonalBandStatus,
            TonalProfile,
        )

        tonal = TonalProfile(
            low=TonalBandStatus.OPTIMAL,
            low_mid=TonalBandStatus.OPTIMAL,
            mid=TonalBandStatus.OPTIMAL,
            high=TonalBandStatus.OPTIMAL,
        )
        suggestions = _generate_suggestions(-14.0, -1.0, True, StereoFieldWidth.NARROW, tonal)
        categories = [s.category for s in suggestions]
        assert "stereo_field" in categories

    def test_tonal_balance_suggested_for_low_too_high(self):
        from app.services.track_quality_analyzer import _generate_suggestions
        from app.schemas.track_quality import (
            StereoFieldWidth,
            TonalBandStatus,
            TonalProfile,
        )

        tonal = TonalProfile(
            low=TonalBandStatus.TOO_HIGH,
            low_mid=TonalBandStatus.OPTIMAL,
            mid=TonalBandStatus.OPTIMAL,
            high=TonalBandStatus.OPTIMAL,
        )
        suggestions = _generate_suggestions(-14.0, -1.0, True, StereoFieldWidth.NORMAL, tonal)
        categories = [s.category for s in suggestions]
        assert "tonal_balance" in categories

    def test_no_suggestions_when_metrics_are_good(self):
        from app.services.track_quality_analyzer import _generate_suggestions
        from app.schemas.track_quality import (
            StereoFieldWidth,
            TonalBandStatus,
            TonalProfile,
        )

        tonal = TonalProfile(
            low=TonalBandStatus.OPTIMAL,
            low_mid=TonalBandStatus.OPTIMAL,
            mid=TonalBandStatus.OPTIMAL,
            high=TonalBandStatus.OPTIMAL,
        )
        # Good metrics: -14 LUFS, -1 dBTP (13 dB DR < 15 threshold),
        # mono compatible, normal stereo field
        suggestions = _generate_suggestions(-14.0, -1.0, True, StereoFieldWidth.NORMAL, tonal)
        assert len(suggestions) == 0
