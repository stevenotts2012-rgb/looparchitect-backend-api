"""
Reference Audio Analyzer V1 — Phase 2.

Extracts high-level arrangement guidance from a full reference audio track.

Design philosophy:
- Robust heuristics over fragile complexity.
- No melody/harmony/drum-pattern extraction.
- No musical content cloning.
- Graceful degradation when analysis is weak.
- Every result is explicitly confidence-banded.

Analysis methods used:
- Windowed RMS for energy curve.
- Spectral flux proxy (high-frequency energy changes) for onset density.
- Energy novelty + threshold-based section segmentation.
- Position + energy heuristics for section type classification.
- librosa.beat.beat_track() for tempo (nullable on failure).
"""

from __future__ import annotations

import io
import logging
import math
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Lazy-import librosa and numpy so the rest of the app does not break if
# they are unavailable in constrained environments.
_librosa_available: Optional[bool] = None
_numpy_available: Optional[bool] = None


def _check_librosa() -> bool:
    global _librosa_available
    if _librosa_available is None:
        try:
            import librosa  # noqa: F401
            import numpy  # noqa: F401
            _librosa_available = True
        except ImportError:
            _librosa_available = False
            logger.warning(
                "librosa/numpy not available — reference analyzer will use fallback path"
            )
    return _librosa_available


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

from app.schemas.reference_arrangement import (
    ReferenceSection,
    ReferenceStructure,
)

# Analysis constants (V1 heuristic parameters)
_WINDOW_SECONDS = 2.0          # RMS window size
_HOP_SECONDS = 1.0             # RMS hop between windows
_MIN_SECTION_SECONDS = 8.0     # Minimum allowed section length
_MAX_SECTION_COUNT = 12        # Maximum sections returned
_MIN_SECTION_COUNT = 2         # Minimum (below this → insufficient)
_MIN_AUDIO_SECONDS = 10.0      # Below this → insufficient quality
_MAX_AUDIO_SECONDS = 900.0     # 15 min limit for V1
_ENERGY_NOVELTY_THRESHOLD = 0.15  # Relative change to trigger a boundary
_TEMPO_CONFIDENCE_THRESHOLD = 0.4  # Below this → nullable tempo


class ReferenceAnalyzer:
    """V1 reference audio analyzer.

    Accepts raw audio bytes (WAV, MP3, FLAC, OGG, M4A, AAC) and returns a
    :class:`ReferenceStructure` containing only structural/energy guidance.

    Musical content is never extracted, stored, or returned.
    """

    def analyze(
        self,
        audio_bytes: bytes,
        filename: str = "reference.wav",
    ) -> ReferenceStructure:
        """Run analysis and return a :class:`ReferenceStructure`.

        Parameters
        ----------
        audio_bytes:
            Raw bytes of the reference audio file.
        filename:
            Original filename (used to infer format hint for pydub).

        Returns
        -------
        ReferenceStructure
            Always returns a valid object.  On failure, a minimal fallback
            structure is returned with ``analysis_quality = "insufficient"``.
        """
        if not _check_librosa():
            return self._fallback_structure(
                total_duration_sec=0.0,
                warning="librosa/numpy not installed — analysis unavailable",
            )

        try:
            return self._analyze_with_librosa(audio_bytes, filename)
        except Exception as exc:
            logger.warning("Reference analysis failed: %s", exc, exc_info=True)
            return self._fallback_structure(
                total_duration_sec=0.0,
                warning=f"Analysis failed: {exc}",
            )

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _analyze_with_librosa(
        self, audio_bytes: bytes, filename: str
    ) -> ReferenceStructure:
        import librosa  # type: ignore
        import numpy as np  # type: ignore

        warnings: List[str] = []

        # Load audio ----------------------------------------------------------------
        y, sr = self._load_audio(audio_bytes, filename)
        total_duration_sec = float(librosa.get_duration(y=y, sr=sr))

        logger.info(
            "ReferenceAnalyzer: loaded %.1fs audio (sr=%d)", total_duration_sec, sr
        )

        # Guard: too short
        if total_duration_sec < _MIN_AUDIO_SECONDS:
            return self._fallback_structure(
                total_duration_sec=total_duration_sec,
                warning=f"Audio too short ({total_duration_sec:.1f}s < {_MIN_AUDIO_SECONDS}s)",
            )

        # Guard: too long
        if total_duration_sec > _MAX_AUDIO_SECONDS:
            warnings.append(
                f"Audio exceeds V1 limit ({total_duration_sec:.0f}s > {_MAX_AUDIO_SECONDS:.0f}s); "
                "analysis may be lower quality"
            )
            # Truncate to limit
            y = y[: int(_MAX_AUDIO_SECONDS * sr)]
            total_duration_sec = min(total_duration_sec, _MAX_AUDIO_SECONDS)

        # Energy curve (windowed RMS) -----------------------------------------------
        window_samples = int(_WINDOW_SECONDS * sr)
        hop_samples = int(_HOP_SECONDS * sr)
        energy_curve_raw = self._compute_rms_curve(y, window_samples, hop_samples)
        energy_curve_normalized = self._normalize(energy_curve_raw)

        # Density curve (spectral flux proxy) ----------------------------------------
        density_curve_raw = self._compute_density_curve(y, sr, window_samples, hop_samples)
        density_curve_normalized = self._normalize(density_curve_raw)

        # Tempo estimate -------------------------------------------------------------
        tempo_estimate = self._estimate_tempo(y, sr, warnings)

        # Section segmentation -------------------------------------------------------
        boundary_times = self._segment_sections(
            energy_curve_normalized, density_curve_normalized, total_duration_sec, warnings
        )

        # Build section objects -----------------------------------------------------
        sections = self._build_sections(
            boundary_times=boundary_times,
            energy_curve=energy_curve_normalized,
            density_curve=density_curve_normalized,
            total_duration_sec=total_duration_sec,
            tempo_estimate=tempo_estimate,
        )

        # Overall confidence ---------------------------------------------------------
        confidence, quality = self._score_confidence(
            sections=sections,
            energy_curve=energy_curve_normalized,
            total_duration_sec=total_duration_sec,
            warnings=warnings,
        )

        # Summary --------------------------------------------------------------------
        summary = self._build_summary(sections, total_duration_sec, tempo_estimate, quality)

        logger.info(
            "ReferenceAnalyzer: %d sections detected, confidence=%.2f, quality=%s",
            len(sections),
            confidence,
            quality,
        )

        return ReferenceStructure(
            total_duration_sec=total_duration_sec,
            tempo_estimate=tempo_estimate,
            sections=sections,
            energy_curve=[round(float(v), 4) for v in energy_curve_normalized],
            summary=summary,
            analysis_confidence=round(confidence, 3),
            analysis_quality=quality,
            analysis_warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Audio loading
    # ------------------------------------------------------------------

    def _load_audio(self, audio_bytes: bytes, filename: str) -> Tuple:
        """Load audio bytes via librosa, trying pydub as a decode fallback."""
        import librosa  # type: ignore
        import numpy as np  # type: ignore

        # Try direct librosa load from bytes
        try:
            y, sr = librosa.load(io.BytesIO(audio_bytes), sr=None, mono=True)
            return y, sr
        except Exception as load_err:
            logger.debug("librosa direct load failed (%s), trying pydub decode", load_err)

        # Fallback: decode with pydub → export as WAV → librosa
        try:
            from pydub import AudioSegment

            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
            seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format=ext)
            # Convert to mono WAV PCM
            wav_buf = io.BytesIO()
            seg.set_channels(1).export(wav_buf, format="wav")
            wav_buf.seek(0)
            y, sr = librosa.load(wav_buf, sr=None, mono=True)
            return y, sr
        except Exception as pydub_err:
            raise RuntimeError(
                f"Could not decode reference audio via librosa or pydub: {pydub_err}"
            ) from pydub_err

    # ------------------------------------------------------------------
    # Energy & density
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_rms_curve(
        y,
        window_samples: int,
        hop_samples: int,
    ) -> List[float]:
        """Compute per-window RMS energy."""
        import numpy as np  # type: ignore

        n_samples = len(y)
        rms_values: List[float] = []
        offset = 0
        while offset < n_samples:
            chunk = y[offset : offset + window_samples]
            rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) > 0 else 0.0
            rms_values.append(rms)
            offset += hop_samples
        return rms_values

    @staticmethod
    def _compute_density_curve(
        y,
        sr: int,
        window_samples: int,
        hop_samples: int,
    ) -> List[float]:
        """Approximate density using high-frequency energy ratio (spectral flux proxy).

        High-frequency content tends to correlate with drum/percussion density.
        This is a fast V1 heuristic — not onset detection.
        """
        import numpy as np  # type: ignore

        n_samples = len(y)
        density_values: List[float] = []
        offset = 0
        while offset < n_samples:
            chunk = y[offset : offset + window_samples]
            if len(chunk) == 0:
                density_values.append(0.0)
                offset += hop_samples
                continue
            # Rough high-frequency energy: take top 40% of FFT bins
            fft = np.abs(np.fft.rfft(chunk))
            split = max(1, int(len(fft) * 0.6))
            hf_energy = float(np.mean(fft[split:])) if len(fft[split:]) > 0 else 0.0
            total_energy = float(np.mean(fft)) if len(fft) > 0 else 1e-9
            ratio = hf_energy / max(total_energy, 1e-9)
            density_values.append(ratio)
            offset += hop_samples
        return density_values

    # ------------------------------------------------------------------
    # Tempo estimation
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tempo(y, sr: int, warnings: List[str]) -> Optional[float]:
        """Estimate BPM using librosa.  Returns None if unreliable."""
        try:
            import librosa  # type: ignore
            import numpy as np  # type: ignore

            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            bpm = float(np.atleast_1d(tempo)[0])
            if bpm < 40.0 or bpm > 240.0:
                warnings.append(
                    f"Tempo estimate ({bpm:.1f} BPM) is outside reliable range — ignored"
                )
                return None
            return round(bpm, 1)
        except Exception as exc:
            warnings.append(f"Tempo estimation unavailable: {exc}")
            return None

    # ------------------------------------------------------------------
    # Section segmentation
    # ------------------------------------------------------------------

    def _segment_sections(
        self,
        energy_curve: List[float],
        density_curve: List[float],
        total_duration_sec: float,
        warnings: List[str],
    ) -> List[float]:
        """Return a list of boundary times (seconds), including 0.0 and total_duration_sec.

        Algorithm:
        1. Compute combined novelty = |energy delta| + 0.5 * |density delta|.
        2. Peak-pick candidates above threshold.
        3. Enforce minimum section length.
        4. Cap at MAX_SECTION_COUNT.
        """
        if len(energy_curve) < 4:
            return [0.0, total_duration_sec]

        combined = self._combined_novelty(energy_curve, density_curve)

        # Threshold-based peak picking
        mean_novelty = sum(combined) / max(len(combined), 1)
        std_novelty = math.sqrt(
            sum((v - mean_novelty) ** 2 for v in combined) / max(len(combined) - 1, 1)
        )
        threshold = mean_novelty + 0.5 * std_novelty + _ENERGY_NOVELTY_THRESHOLD

        boundaries = [0.0]
        for i, novelty in enumerate(combined):
            time_sec = i * _HOP_SECONDS
            if novelty >= threshold and (time_sec - boundaries[-1]) >= _MIN_SECTION_SECONDS:
                boundaries.append(time_sec)

        boundaries.append(total_duration_sec)

        # Cap
        if len(boundaries) - 1 > _MAX_SECTION_COUNT:
            warnings.append(
                f"Too many sections detected ({len(boundaries) - 1}); "
                f"capped at {_MAX_SECTION_COUNT}"
            )
            # Keep evenly spaced subset
            step = (len(boundaries) - 2) // (_MAX_SECTION_COUNT - 1)
            kept = [boundaries[0]]
            for i in range(1, len(boundaries) - 1, max(1, step)):
                kept.append(boundaries[i])
                if len(kept) >= _MAX_SECTION_COUNT:
                    break
            kept.append(boundaries[-1])
            boundaries = kept

        if len(boundaries) < _MIN_SECTION_COUNT + 1:
            # Ensure at least two sections
            mid = total_duration_sec / 2.0
            boundaries = [0.0, mid, total_duration_sec]

        return boundaries

    @staticmethod
    def _combined_novelty(
        energy_curve: List[float], density_curve: List[float]
    ) -> List[float]:
        """Compute frame-wise novelty as weighted delta of energy + density."""
        n = max(len(energy_curve), len(density_curve))
        result = []
        for i in range(n):
            e_curr = energy_curve[i] if i < len(energy_curve) else 0.0
            e_prev = energy_curve[i - 1] if i > 0 and i - 1 < len(energy_curve) else e_curr
            d_curr = density_curve[i] if i < len(density_curve) else 0.0
            d_prev = density_curve[i - 1] if i > 0 and i - 1 < len(density_curve) else d_curr
            novelty = abs(e_curr - e_prev) + 0.5 * abs(d_curr - d_prev)
            result.append(novelty)
        return result

    # ------------------------------------------------------------------
    # Section object construction
    # ------------------------------------------------------------------

    def _build_sections(
        self,
        boundary_times: List[float],
        energy_curve: List[float],
        density_curve: List[float],
        total_duration_sec: float,
        tempo_estimate: Optional[float],
    ) -> List[ReferenceSection]:
        """Build :class:`ReferenceSection` objects from boundary times."""
        sections: List[ReferenceSection] = []
        n_sections = len(boundary_times) - 1

        for i in range(n_sections):
            start = boundary_times[i]
            end = boundary_times[i + 1]
            duration = end - start

            avg_energy = self._avg_curve_slice(energy_curve, start, end, total_duration_sec)
            avg_density = self._avg_curve_slice(density_curve, start, end, total_duration_sec)

            # Transition strength = novelty at boundary vs mean energy
            trans_in = self._transition_strength(
                energy_curve, density_curve, start, total_duration_sec
            ) if i > 0 else 0.0
            trans_out = self._transition_strength(
                energy_curve, density_curve, end, total_duration_sec
            ) if i < n_sections - 1 else 0.0

            # Estimated bars
            bpm = tempo_estimate or 120.0
            bars = max(1, int(round((duration / 60.0) * bpm / 4.0)))

            # Section type heuristic
            section_type = self._classify_section(
                index=i,
                n_sections=n_sections,
                energy=avg_energy,
                density=avg_density,
                duration=duration,
                total_duration=total_duration_sec,
            )

            sections.append(
                ReferenceSection(
                    index=i,
                    start_time_sec=round(start, 2),
                    end_time_sec=round(end, 2),
                    estimated_bars=bars,
                    section_type_guess=section_type,
                    energy_level=round(avg_energy, 3),
                    density_level=round(avg_density, 3),
                    transition_in_strength=round(trans_in, 3),
                    transition_out_strength=round(trans_out, 3),
                    confidence=self._section_confidence(duration, total_duration_sec),
                )
            )

        return sections

    @staticmethod
    def _avg_curve_slice(
        curve: List[float],
        start_sec: float,
        end_sec: float,
        total_sec: float,
    ) -> float:
        """Average of curve values within [start_sec, end_sec]."""
        if not curve or total_sec <= 0:
            return 0.5
        n = len(curve)
        start_idx = max(0, int((start_sec / total_sec) * n))
        end_idx = min(n, int((end_sec / total_sec) * n))
        if start_idx >= end_idx:
            return curve[min(start_idx, n - 1)]
        values = curve[start_idx:end_idx]
        return sum(values) / len(values) if values else 0.5

    @staticmethod
    def _transition_strength(
        energy_curve: List[float],
        density_curve: List[float],
        boundary_sec: float,
        total_sec: float,
    ) -> float:
        """Estimate transition strength at a boundary as local energy delta."""
        if not energy_curve or total_sec <= 0:
            return 0.3
        n = len(energy_curve)
        idx = min(n - 1, max(0, int((boundary_sec / total_sec) * n)))
        before = energy_curve[max(0, idx - 2) : idx]
        after = energy_curve[idx : min(n, idx + 2)]
        avg_before = sum(before) / len(before) if before else 0.5
        avg_after = sum(after) / len(after) if after else 0.5
        return min(1.0, abs(avg_after - avg_before) * 3.0)

    @staticmethod
    def _classify_section(
        index: int,
        n_sections: int,
        energy: float,
        density: float,
        duration: float,
        total_duration: float,
    ) -> str:
        """Heuristic section type classification.

        Rules (V1):
        - First section → "intro"
        - Last section → "outro"
        - High energy + high density → "hook"
        - Low energy + low density → "breakdown"
        - Otherwise → "verse"
        - Short bridging section between hook and verse → "bridge"
        """
        if index == 0:
            return "intro"
        if index == n_sections - 1:
            return "outro"

        position_ratio = (index + 0.5) / n_sections  # 0.0 → 1.0

        if energy >= 0.7 and density >= 0.6:
            return "hook"
        if energy <= 0.35 and density <= 0.4:
            return "breakdown"
        # Short bridging sections in the second half
        if position_ratio > 0.5 and duration < total_duration * 0.10:
            return "bridge"
        return "verse"

    @staticmethod
    def _section_confidence(duration_sec: float, total_duration_sec: float) -> float:
        """Per-section confidence based on its relative length."""
        ratio = duration_sec / max(total_duration_sec, 1.0)
        if ratio < 0.03:
            return 0.3  # Very short section — uncertain
        if ratio > 0.4:
            return 0.5  # Very long — probably should split but we didn't
        return 0.7

    # ------------------------------------------------------------------
    # Overall confidence scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _score_confidence(
        sections: List[ReferenceSection],
        energy_curve: List[float],
        total_duration_sec: float,
        warnings: List[str],
    ) -> Tuple[float, str]:
        """Return (confidence_score 0–1, quality_band)."""
        if not sections:
            return 0.1, "insufficient"

        n = len(sections)
        score = 0.5

        # More sections → better differentiation
        if n >= 4:
            score += 0.15
        elif n <= 2:
            score -= 0.15

        # Energy variance → better dynamics
        if energy_curve:
            mean_e = sum(energy_curve) / len(energy_curve)
            variance = sum((v - mean_e) ** 2 for v in energy_curve) / len(energy_curve)
            std_e = math.sqrt(variance)
            if std_e < 0.05:
                score -= 0.2
                warnings.append("Low energy dynamics — reference may be a flat-energy track")
            elif std_e > 0.15:
                score += 0.1

        # Short audio penalises confidence
        if total_duration_sec < 30.0:
            score -= 0.2

        score = max(0.05, min(1.0, score))

        if score >= 0.65:
            quality = "high"
        elif score >= 0.45:
            quality = "medium"
        elif score >= 0.25:
            quality = "low"
        else:
            quality = "insufficient"

        return score, quality

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(
        sections: List[ReferenceSection],
        total_duration_sec: float,
        tempo_estimate: Optional[float],
        quality: str,
    ) -> str:
        n = len(sections)
        type_list = ", ".join(s.section_type_guess for s in sections)
        tempo_str = f"{tempo_estimate:.1f} BPM" if tempo_estimate else "unknown tempo"
        return (
            f"{n}-section structure ({type_list}) over "
            f"{total_duration_sec:.0f}s at {tempo_str}. "
            f"Analysis quality: {quality}."
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(values: List[float]) -> List[float]:
        """Normalize a list of floats to [0, 1]."""
        if not values:
            return values
        if len(values) == 1:
            return list(values)
        min_v = min(values)
        max_v = max(values)
        rng = max_v - min_v
        if rng < 1e-9:
            return [0.5] * len(values)
        return [(v - min_v) / rng for v in values]

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_structure(
        total_duration_sec: float, warning: str = ""
    ) -> ReferenceStructure:
        """Return a minimal fallback when analysis cannot complete."""
        warnings = [warning] if warning else []
        return ReferenceStructure(
            total_duration_sec=max(0.0, total_duration_sec),
            tempo_estimate=None,
            sections=[],
            energy_curve=[],
            summary="Analysis unavailable or insufficient.",
            analysis_confidence=0.0,
            analysis_quality="insufficient",
            analysis_warnings=warnings,
        )


# Module-level singleton
reference_analyzer = ReferenceAnalyzer()
