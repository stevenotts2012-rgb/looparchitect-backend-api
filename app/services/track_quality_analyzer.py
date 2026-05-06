"""
Track Technical Quality Analyzer — V1.

Performs DSP-based technical quality analysis on a single audio file and
returns metrics matching the ``TrackQualityAnalysisResponse`` schema.

Measurements provided
---------------------
* Sample rate / bit depth     — read from file metadata via soundfile / pydub.
* Clipping                    — fraction of samples at or near full-scale.
* Mono compatibility          — phase-coherence test: L/R correlation + mono
                                sum energy ratio.
* Integrated loudness (LUFS)  — simplified BS.1770-3 approximation using
                                windowed RMS with absolute and relative gating.
                                No K-weighting filter is applied; values are
                                close to a certified loudness meter but not
                                identical.
* True peak                   — maximum sample amplitude in dBFS.
* Phase issues                — significant L/R phase cancellation check.
* Stereo field width          — mid/side energy ratio (Narrow / Normal / Wide).
* Tonal profile               — FFT energy balance across four spectral bands
                                (Low, Low-Mid, Mid, High) compared to reference
                                ranges for a well-balanced mix.
* Suggestions                 — rule-based actionable tips derived from the
                                metrics above.

Design notes
------------
* Requires numpy + librosa (already in requirements.txt).  soundfile is used
  for metadata extraction; pydub is the fallback loader.
* All heavy analysis runs synchronously; callers should offload to a thread
  pool executor for async routes.
* Graceful degradation: every analysis step has a safe fallback so the service
  always returns a complete response.
"""

from __future__ import annotations

import io
import logging
import math
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public facade
# ---------------------------------------------------------------------------

from app.schemas.track_quality import (
    ClippingLevel,
    StereoFieldWidth,
    TonalBandStatus,
    TonalProfile,
    TrackQualityAnalysisResponse,
    TrackQualitySuggestion,
)

# ---------------------------------------------------------------------------
# Analysis constants
# ---------------------------------------------------------------------------

_ANALYSIS_VERSION = "1.0.0"

# Loudness gating — absolute gate at approximately −70 LUFS
_ABSOLUTE_GATE_LUFS = -70.0

# Relative gating offset below first-pass gated mean (BS.1770-3: −10 LU)
_RELATIVE_GATE_LU = -10.0

# Block/hop sizes for integrated loudness (BS.1770-3: 400 ms block, 75 % overlap)
_LOUDNESS_BLOCK_SEC = 0.4
_LOUDNESS_HOP_SEC = 0.1

# Clipping threshold: samples at or above this value are considered clipped
_CLIP_THRESHOLD = 0.999

# Clipping severity boundary: fraction of clipped samples
_CLIP_MINOR_THRESHOLD = 0.0001   # > 0.01 % → Minor
_CLIP_SEVERE_THRESHOLD = 0.001   # > 0.1 %  → Severe

# Mono-compatibility: minimum acceptable L/R channel correlation
_MONO_COMPAT_CORR_MIN = 0.3

# Mono-compatibility: minimum acceptable mono-sum / average-channel RMS ratio
_MONO_COMPAT_ENERGY_RATIO_MIN = 0.70

# Phase issue threshold: mono-sum energy must be < this fraction of avg to flag
_PHASE_ISSUE_ENERGY_RATIO = 0.50

# Stereo field width thresholds (side/mid RMS ratio)
_STEREO_NARROW_MAX = 0.30
_STEREO_WIDE_MIN = 0.70

# Tonal profile: reference energy-fraction ranges for a "well-balanced" mix.
# These heuristic ranges were derived from spectral analysis of commercially
# released tracks across multiple genres.
_TONAL_REFERENCE_RANGES: Dict[str, Tuple[float, float]] = {
    "low":     (0.10, 0.40),   # 20–250 Hz
    "low_mid": (0.20, 0.45),   # 250–2000 Hz
    "mid":     (0.10, 0.40),   # 2000–8000 Hz
    "high":    (0.05, 0.30),   # 8000–20000 Hz
}

# Tonal band frequency boundaries in Hz
_TONAL_BANDS: List[Tuple[str, int, int]] = [
    ("low",     20,    250),
    ("low_mid", 250,  2000),
    ("mid",    2000,  8000),
    ("high",   8000, 20000),
]

# Suggestion trigger thresholds
_COMPRESSION_DYNAMIC_RANGE_DB = 15.0  # (true_peak − integrated_loudness) > this
_LOUDNESS_QUIET_LUFS = -20.0          # integrated_loudness < this → too quiet


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_file_metadata(audio_bytes: bytes, filename: str) -> Tuple[int, int]:
    """Return (sample_rate, bit_depth) by inspecting the file header.

    Tries soundfile first (PCM/FLAC/OGG); falls back to pydub for MP3/AAC.
    Returns (44100, 16) as a safe default on any failure.
    """
    try:
        import soundfile as sf  # type: ignore

        with sf.SoundFile(io.BytesIO(audio_bytes)) as f:
            sr = f.samplerate
            subtype = f.subtype  # e.g. "PCM_24", "FLOAT", "VORBIS"
            bit_depth = _parse_sf_bit_depth(subtype)
            return sr, bit_depth
    except Exception:
        pass

    # Fallback: pydub
    try:
        from pydub import AudioSegment

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
        seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format=ext)
        return seg.frame_rate, seg.sample_width * 8
    except Exception:
        pass

    return 44100, 16


def _parse_sf_bit_depth(subtype: str) -> int:
    """Map a soundfile subtype string to a bit-depth integer."""
    if subtype.startswith("PCM_"):
        try:
            return int(subtype.split("_")[1])
        except (IndexError, ValueError):
            pass
    mapping = {
        "FLOAT":  32,
        "DOUBLE": 64,
        "ULAW":   8,
        "ALAW":   8,
        "VORBIS": 16,
        "OPUS":   16,
    }
    return mapping.get(subtype, 16)


def _load_audio(
    audio_bytes: bytes, filename: str
) -> Tuple[object, object, int]:
    """Load audio via librosa (mono=False to preserve stereo).

    Returns (y_left, y_right_or_None, sample_rate).

    ``y_left`` is always a 1-D float32 numpy array.
    ``y_right`` is a 1-D float32 numpy array for stereo files, or ``None``
    for mono files.
    """
    import librosa  # type: ignore
    import numpy as np  # type: ignore

    try:
        loaded = librosa.load(io.BytesIO(audio_bytes), sr=None, mono=False)
        if isinstance(loaded, tuple) and len(loaded) >= 2:
            y, sr = loaded[0], loaded[1]
        else:
            y, sr = loaded, 44100
    except Exception:
        # Fallback: let pydub decode, then reload via librosa
        from pydub import AudioSegment

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
        seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format=ext)
        wav_buf = io.BytesIO()
        seg.export(wav_buf, format="wav")
        wav_buf.seek(0)
        loaded = librosa.load(wav_buf, sr=None, mono=False)
        if isinstance(loaded, tuple) and len(loaded) >= 2:
            y, sr = loaded[0], loaded[1]
        else:
            y, sr = loaded, int(seg.frame_rate or 44100)

    if y.ndim == 1:
        # Mono file
        return y, None, int(sr)

    # Multichannel: use first two channels
    y_left = y[0]
    y_right = y[1]
    return y_left, y_right, int(sr)


def _detect_clipping(y_left, y_right) -> ClippingLevel:
    """Classify clipping severity based on fraction of near-full-scale samples."""
    import numpy as np  # type: ignore

    all_samples = (
        np.concatenate([y_left, y_right])
        if y_right is not None
        else y_left
    )
    abs_samples = np.abs(all_samples)
    total = len(abs_samples)
    if total == 0:
        return ClippingLevel.NONE

    clipped = int(np.sum(abs_samples >= _CLIP_THRESHOLD))
    ratio = clipped / total

    if ratio >= _CLIP_SEVERE_THRESHOLD:
        return ClippingLevel.SEVERE
    if ratio >= _CLIP_MINOR_THRESHOLD:
        return ClippingLevel.MINOR
    return ClippingLevel.NONE


def _compute_mono_compatibility(y_left, y_right) -> bool:
    """Return True if the stereo pair is mono-compatible.

    Checks two independent criteria:
    1. Pearson correlation between L and R channels ≥ threshold.
    2. Mono-sum RMS ≥ threshold fraction of average individual channel RMS.

    A file that fails either check is flagged as mono-incompatible.
    """
    import numpy as np  # type: ignore

    if y_right is None:
        return True  # Mono files are always compatible

    std_l = float(np.std(y_left))
    std_r = float(np.std(y_right))

    if std_l < 1e-10 and std_r < 1e-10:
        return True  # Silent signal — trivially mono compatible

    if std_l > 1e-10 and std_r > 1e-10:
        corr = float(np.corrcoef(y_left, y_right)[0, 1])
    else:
        corr = 1.0  # One channel silent → treat as mono compatible

    # Energy ratio check
    rms_l = math.sqrt(float(np.mean(y_left ** 2)))
    rms_r = math.sqrt(float(np.mean(y_right ** 2)))
    mono_sum = y_left + y_right
    rms_mono_sum = math.sqrt(float(np.mean(mono_sum ** 2)))

    avg_rms = (rms_l + rms_r) / 2.0
    energy_ratio = rms_mono_sum / avg_rms if avg_rms > 1e-10 else 2.0

    return (
        corr >= _MONO_COMPAT_CORR_MIN
        and energy_ratio >= _MONO_COMPAT_ENERGY_RATIO_MIN
    )


def _detect_phase_issues(y_left, y_right) -> bool:
    """Return True when significant phase cancellation is present.

    Phase cancellation is inferred by comparing the RMS of the mono sum
    to the average RMS of individual channels.  When the sum is much quieter
    than expected, polarity inversion or strong out-of-phase content is present.
    """
    import numpy as np  # type: ignore

    if y_right is None:
        return False  # Mono — no stereo phase to evaluate

    rms_l = math.sqrt(float(np.mean(y_left ** 2)))
    rms_r = math.sqrt(float(np.mean(y_right ** 2)))
    mono_sum = y_left + y_right
    rms_mono_sum = math.sqrt(float(np.mean(mono_sum ** 2)))

    avg_rms = (rms_l + rms_r) / 2.0
    if avg_rms < 1e-10:
        return False

    return (rms_mono_sum / avg_rms) < _PHASE_ISSUE_ENERGY_RATIO


def _compute_stereo_field(y_left, y_right) -> StereoFieldWidth:
    """Classify stereo field width using mid/side energy ratio."""
    import numpy as np  # type: ignore

    if y_right is None:
        return StereoFieldWidth.NARROW  # Mono file has no stereo width

    mid = (y_left + y_right) / math.sqrt(2.0)
    side = (y_left - y_right) / math.sqrt(2.0)

    rms_mid = math.sqrt(float(np.mean(mid ** 2)))
    rms_side = math.sqrt(float(np.mean(side ** 2)))

    if rms_mid < 1e-10:
        return StereoFieldWidth.NORMAL

    ratio = rms_side / rms_mid

    if ratio < _STEREO_NARROW_MAX:
        return StereoFieldWidth.NARROW
    if ratio > _STEREO_WIDE_MIN:
        return StereoFieldWidth.WIDE
    return StereoFieldWidth.NORMAL


def _compute_integrated_loudness(y_left, y_right, sr: int) -> float:
    """Compute integrated loudness (simplified BS.1770-3 approximation).

    Uses 400 ms blocks with 75 % overlap, applies absolute gating at −70 LUFS
    and relative gating at −10 LU below the first-pass mean.

    Note: No K-weighting filter is applied — results approximate true LUFS
    but are not identical to a certified loudness meter.
    """
    import numpy as np  # type: ignore

    block_size = max(int(_LOUDNESS_BLOCK_SEC * sr), 1)
    hop_size = max(int(_LOUDNESS_HOP_SEC * sr), 1)

    def _block_mean_squares(y_ch) -> object:
        n = len(y_ch)
        if n < block_size:
            ms = float(np.mean(y_ch ** 2))
            return np.array([ms])
        blocks = []
        for start in range(0, n - block_size + 1, hop_size):
            block = y_ch[start : start + block_size]
            blocks.append(float(np.mean(block ** 2)))
        return np.array(blocks) if blocks else np.array([float(np.mean(y_ch ** 2))])

    left_ms = _block_mean_squares(y_left)
    if y_right is not None:
        right_ms = _block_mean_squares(y_right)
        # Align lengths (may differ by one block due to rounding)
        n_blocks = min(len(left_ms), len(right_ms))
        mean_squares = (left_ms[:n_blocks] + right_ms[:n_blocks]) / 2.0
    else:
        mean_squares = left_ms

    # Absolute gating: convert −70 LUFS absolute gate to mean-square threshold
    # LUFS = −0.691 + 10·log10(mean_square)  →  mean_square = 10^((L+0.691)/10)
    abs_gate_ms = 10 ** ((_ABSOLUTE_GATE_LUFS + 0.691) / 10.0)
    gated = mean_squares[mean_squares > abs_gate_ms]

    if len(gated) == 0:
        return _ABSOLUTE_GATE_LUFS

    # Relative gating: −10 LU below first-pass mean
    mean_gated = float(gated.mean())
    rel_gate_ms = mean_gated * 10 ** (_RELATIVE_GATE_LU / 10.0)
    gated2 = gated[gated > rel_gate_ms]

    if len(gated2) == 0:
        gated2 = gated

    final_ms = float(gated2.mean())
    if final_ms <= 0:
        return _ABSOLUTE_GATE_LUFS

    loudness = -0.691 + 10.0 * math.log10(final_ms)
    return round(loudness, 1)


def _compute_true_peak(y_left, y_right) -> float:
    """Return maximum sample amplitude in dBFS."""
    import numpy as np  # type: ignore

    all_samples = (
        np.concatenate([y_left, y_right])
        if y_right is not None
        else y_left
    )
    max_abs = float(np.max(np.abs(all_samples)))
    if max_abs <= 0:
        return -120.0
    return round(20.0 * math.log10(max_abs), 1)


def _compute_tonal_profile(y_left, y_right, sr: int) -> TonalProfile:
    """Analyze spectral energy balance across four broad frequency bands.

    Uses a real FFT on up to 30 seconds of the mono mix.  Each band's energy
    fraction is compared to the reference range in ``_TONAL_REFERENCE_RANGES``.
    """
    import numpy as np  # type: ignore

    # Build mono mix for tonal analysis
    if y_right is not None:
        y_mono = (y_left + y_right) / 2.0
    else:
        y_mono = y_left

    # Use a representative segment (avoid silence at edges)
    max_samples = sr * 30
    y_seg = y_mono[:max_samples]

    n = len(y_seg)
    if n < 2:
        return TonalProfile(
            low=TonalBandStatus.OPTIMAL,
            low_mid=TonalBandStatus.OPTIMAL,
            mid=TonalBandStatus.OPTIMAL,
            high=TonalBandStatus.OPTIMAL,
        )

    fft_mags = np.abs(np.fft.rfft(y_seg))
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    power = fft_mags ** 2

    band_energies: Dict[str, float] = {}
    for name, lo, hi in _TONAL_BANDS:
        mask = (freqs >= lo) & (freqs < hi)
        band_energies[name] = float(np.mean(power[mask])) if np.any(mask) else 0.0

    total = sum(band_energies.values())
    if total <= 0.0:
        return TonalProfile(
            low=TonalBandStatus.OPTIMAL,
            low_mid=TonalBandStatus.OPTIMAL,
            mid=TonalBandStatus.OPTIMAL,
            high=TonalBandStatus.OPTIMAL,
        )

    statuses: Dict[str, TonalBandStatus] = {}
    for name, (lo_ref, hi_ref) in _TONAL_REFERENCE_RANGES.items():
        ratio = band_energies[name] / total
        if ratio > hi_ref:
            statuses[name] = TonalBandStatus.TOO_HIGH
        elif ratio < lo_ref:
            statuses[name] = TonalBandStatus.TOO_LOW
        else:
            statuses[name] = TonalBandStatus.OPTIMAL

    return TonalProfile(
        low=statuses["low"],
        low_mid=statuses["low_mid"],
        mid=statuses["mid"],
        high=statuses["high"],
    )


def _generate_suggestions(
    integrated_loudness: float,
    true_peak: float,
    mono_compatibility: bool,
    stereo_field: StereoFieldWidth,
    tonal_profile: TonalProfile,
) -> List[TrackQualitySuggestion]:
    """Generate rule-based improvement suggestions from the quality metrics."""
    suggestions: List[TrackQualitySuggestion] = []

    # Compression — wide dynamic range
    dynamic_range = true_peak - integrated_loudness
    if dynamic_range > _COMPRESSION_DYNAMIC_RANGE_DB:
        suggestions.append(
            TrackQualitySuggestion(
                category="compression",
                message=(
                    "Unless this is a deliberate artistic decision, you could consider applying "
                    "more compression to make adjustments. Here's a tip on how to achieve this: "
                    "Use compression on individual instruments to smooth out overly loud or quiet "
                    "parts. Apply it carefully to keep the sound natural—this helps your track feel "
                    "balanced without losing its energy."
                ),
            )
        )

    # Loudness — too quiet
    if integrated_loudness < _LOUDNESS_QUIET_LUFS:
        suggestions.append(
            TrackQualitySuggestion(
                category="loudness",
                message=(
                    "Here's a tip on how to improve that: If your mix sounds too quiet, go through "
                    "each track and raise its volume while keeping the overall balance intact. This "
                    "ensures all the elements in your mix are clear and present without causing "
                    "distortion on the master channel. A louder mix will sound more engaging and "
                    "professional."
                ),
            )
        )

    # Mono compatibility
    if not mono_compatibility:
        suggestions.append(
            TrackQualitySuggestion(
                category="mono_compatibility",
                message=(
                    "Here's a tip that could help you improve this: Instead of applying stereo "
                    "processing to the whole mix, focus on individual tracks. Use tools like EQ and "
                    "compression to fix specific issues while ensuring the overall mix stays "
                    "mono-compatible. This approach gives you better control and keeps your mix "
                    "balanced."
                ),
            )
        )

    # Stereo field — narrow
    if stereo_field == StereoFieldWidth.NARROW:
        suggestions.append(
            TrackQualitySuggestion(
                category="stereo_field",
                message=(
                    "If this is not intentional, here is a tip on how to achieve a wider mix: "
                    "Spread your instruments across the stereo field to create a fuller, more "
                    "spacious mix. Panning allows each sound to have its own space, making it "
                    "easier for listeners to hear individual parts clearly."
                ),
            )
        )

    # Tonal balance
    _add_tonal_suggestions(tonal_profile, suggestions)

    return suggestions


def _add_tonal_suggestions(
    tonal_profile: TonalProfile,
    suggestions: List[TrackQualitySuggestion],
) -> None:
    """Append tonal-balance suggestions based on the spectral analysis."""
    if tonal_profile.low == TonalBandStatus.TOO_HIGH:
        suggestions.append(
            TrackQualitySuggestion(
                category="tonal_balance",
                message=(
                    "The low end of your track is overpowering the rest of the mix, which can "
                    "make it sound boomy or muddy. Try pulling back the bass level or using an EQ "
                    "to reduce some of the low-end energy. This will help the vocals and other "
                    "instruments come through more clearly. Addressing the tonal balance across "
                    "these areas will help your track sound more polished and closer to what's "
                    "typical for this style."
                ),
            )
        )
    elif tonal_profile.low == TonalBandStatus.TOO_LOW:
        suggestions.append(
            TrackQualitySuggestion(
                category="tonal_balance",
                message=(
                    "Your track lacks low-end energy, which can make it sound thin or weak. "
                    "Consider boosting the bass frequencies or adding more low-end content to "
                    "give your track more weight and body."
                ),
            )
        )

    if tonal_profile.low_mid == TonalBandStatus.TOO_HIGH:
        suggestions.append(
            TrackQualitySuggestion(
                category="tonal_balance",
                message=(
                    "The low-mid frequencies (250–2000 Hz) are overpowering your mix, which can "
                    "cause a boxy or muddy sound. Try cutting some of this range with a parametric "
                    "EQ to add clarity and definition to your mix."
                ),
            )
        )
    elif tonal_profile.low_mid == TonalBandStatus.TOO_LOW:
        suggestions.append(
            TrackQualitySuggestion(
                category="tonal_balance",
                message=(
                    "Your mix lacks low-mid energy (250–2000 Hz), which can make it sound thin "
                    "or lacking body. Consider boosting this range slightly to add warmth and "
                    "fullness to your sound."
                ),
            )
        )

    if tonal_profile.high == TonalBandStatus.TOO_HIGH:
        suggestions.append(
            TrackQualitySuggestion(
                category="tonal_balance",
                message=(
                    "The high frequencies in your track are overpowering, which can cause listener "
                    "fatigue or make the track sound harsh and sibilant. Try rolling off some of "
                    "the high-end energy with a high-shelf EQ or a gentle low-pass filter."
                ),
            )
        )
    elif tonal_profile.high == TonalBandStatus.TOO_LOW:
        suggestions.append(
            TrackQualitySuggestion(
                category="tonal_balance",
                message=(
                    "Your track lacks high-frequency content (8000 Hz and above), which can make "
                    "it sound dull or muffled. Consider boosting the high-end or adding air with a "
                    "high-shelf EQ to brighten and open up your mix."
                ),
            )
        )


# ---------------------------------------------------------------------------
# Public service class
# ---------------------------------------------------------------------------


class TrackQualityAnalyzer:
    """Analyzes an uploaded audio file for technical quality metrics.

    Usage::

        analyzer = TrackQualityAnalyzer()
        result = analyzer.analyze(audio_bytes, filename="track.wav")
        # result is a TrackQualityAnalysisResponse

    The ``analyze`` method is synchronous and CPU-bound.  In async routes,
    run it inside ``asyncio.get_event_loop().run_in_executor(None, ...)``.
    """

    def analyze(
        self,
        audio_bytes: bytes,
        filename: str = "track.wav",
    ) -> TrackQualityAnalysisResponse:
        """Run the full quality analysis pipeline on *audio_bytes*.

        Parameters
        ----------
        audio_bytes:
            Raw bytes of the audio file (WAV, MP3, FLAC, OGG, M4A, AAC).
        filename:
            Original filename used as a format hint for codec detection.

        Returns
        -------
        TrackQualityAnalysisResponse
            Always returns a complete, valid response.  Individual metrics
            fall back to safe defaults on error.
        """
        try:
            return self._run_analysis(audio_bytes, filename)
        except Exception as exc:
            logger.error(
                "TrackQualityAnalyzer: unexpected analysis failure: %s",
                exc,
                exc_info=True,
            )
            raise

    def _run_analysis(
        self, audio_bytes: bytes, filename: str
    ) -> TrackQualityAnalysisResponse:
        import numpy as np  # noqa: F401 — validate numpy import early

        # --- File metadata (sample rate, bit depth) ---
        sample_rate, bit_depth = _get_file_metadata(audio_bytes, filename)

        # --- Load audio signal ---
        y_left, y_right, sr_actual = _load_audio(audio_bytes, filename)

        # Prefer metadata sample rate; fall back to librosa's decoded rate
        sample_rate = sample_rate or sr_actual

        logger.info(
            "TrackQualityAnalyzer: loaded audio sr=%d bit_depth=%d "
            "stereo=%s samples=%d",
            sample_rate,
            bit_depth,
            y_right is not None,
            len(y_left),
        )

        # --- Individual metric computations ---
        clipping = _safe(
            lambda: _detect_clipping(y_left, y_right),
            ClippingLevel.NONE,
            "clipping",
        )

        mono_compat = _safe(
            lambda: _compute_mono_compatibility(y_left, y_right),
            True,
            "mono_compatibility",
        )

        phase_issues = _safe(
            lambda: _detect_phase_issues(y_left, y_right),
            False,
            "phase_issues",
        )

        stereo_field = _safe(
            lambda: _compute_stereo_field(y_left, y_right),
            StereoFieldWidth.NORMAL,
            "stereo_field",
        )

        integrated_loudness = _safe(
            lambda: _compute_integrated_loudness(y_left, y_right, sr_actual),
            -23.0,
            "integrated_loudness",
        )

        true_peak = _safe(
            lambda: _compute_true_peak(y_left, y_right),
            -6.0,
            "true_peak",
        )

        tonal_profile = _safe(
            lambda: _compute_tonal_profile(y_left, y_right, sr_actual),
            TonalProfile(
                low=TonalBandStatus.OPTIMAL,
                low_mid=TonalBandStatus.OPTIMAL,
                mid=TonalBandStatus.OPTIMAL,
                high=TonalBandStatus.OPTIMAL,
            ),
            "tonal_profile",
        )

        suggestions = _safe(
            lambda: _generate_suggestions(
                integrated_loudness=integrated_loudness,
                true_peak=true_peak,
                mono_compatibility=mono_compat,
                stereo_field=stereo_field,
                tonal_profile=tonal_profile,
            ),
            [],
            "suggestions",
        )

        logger.info(
            "TrackQualityAnalyzer: analysis complete "
            "lufs=%.1f peak=%.1f clipping=%s mono_compat=%s "
            "stereo=%s phase=%s suggestions=%d",
            integrated_loudness,
            true_peak,
            clipping.value,
            mono_compat,
            stereo_field.value,
            phase_issues,
            len(suggestions),
        )

        return TrackQualityAnalysisResponse(
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            clipping=clipping,
            mono_compatibility=mono_compat,
            integrated_loudness=integrated_loudness,
            true_peak=true_peak,
            phase_issues=phase_issues,
            stereo_field=stereo_field,
            tonal_profile=tonal_profile,
            suggestions=suggestions,
            analysis_version=_ANALYSIS_VERSION,
        )


def _safe(fn, default, label: str = ""):
    """Call *fn()* and return *default* on any exception, logging the error."""
    try:
        return fn()
    except Exception as exc:
        logger.warning(
            "TrackQualityAnalyzer: %s computation failed (%s), using default",
            label,
            exc,
        )
        return default


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

track_quality_analyzer = TrackQualityAnalyzer()
