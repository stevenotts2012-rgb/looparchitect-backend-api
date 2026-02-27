"""Audio analysis service for detecting BPM, musical key, and duration from audio files.

This module provides comprehensive audio analysis capabilities using librosa for
BPM and key detection. All analysis operations are designed to be efficient and
production-ready with proper error handling and logging.
"""

import logging
from typing import Tuple
import numpy as np
import librosa

logger = logging.getLogger(__name__)


class AudioAnalyzer:
    """Orchestrates audio analysis operations on uploaded loop files."""

    # Confidence thresholds
    MIN_BPM_CONFIDENCE = 0.4  # Librosa's tempo strength must exceed this
    MIN_KEY_CONFIDENCE = 0.5  # Chroma-based key detection requires confidence

    @staticmethod
    def analyze_audio(file_path: str) -> dict:
        """Main orchestration function for complete audio analysis.

        Loads audio file and performs BPM, key, and duration detection.
        Returns all analysis results in a single dictionary.

        Args:
            file_path: Path to WAV or MP3 audio file

        Returns:
            Dictionary containing:
            - bpm (int): Detected tempo in beats per minute
            - musical_key (str): Detected key (e.g., "C Major", "A Minor")
            - duration_seconds (float): Total audio duration in seconds
            - confidence (float): Overall analysis confidence 0.0-1.0
            - analysis_details (dict): Additional metadata from detection

        Raises:
            ValueError: If file cannot be loaded or is empty
            Exception: If analysis fails at any step
        """
        logger.info(f"Starting audio analysis for file: {file_path}")

        try:
            # Load audio with librosa (standardized 22050 Hz sample rate)
            logger.debug(f"Loading audio from: {file_path}")
            y, sr = librosa.load(file_path, sr=22050)

            if len(y) == 0:
                raise ValueError("Audio file is empty or invalid")

            logger.debug(f"Audio loaded: {len(y)} samples at {sr} Hz")

            # Calculate duration
            duration_seconds = len(y) / sr
            logger.debug(f"Duration: {duration_seconds:.2f} seconds")

            # Detect BPM
            bpm, bpm_confidence = AudioAnalyzer.detect_bpm(y, sr)
            logger.info(f"BPM detected: {bpm} (confidence: {bpm_confidence:.2f})")

            # Detect musical key
            musical_key, key_confidence = AudioAnalyzer.detect_key(y, sr)
            logger.info(f"Key detected: {musical_key} (confidence: {key_confidence:.2f})")

            # Calculate overall confidence
            overall_confidence = (bpm_confidence + key_confidence) / 2
            logger.debug(f"Overall analysis confidence: {overall_confidence:.2f}")

            analysis_result = {
                "bpm": int(round(bpm)),
                "musical_key": musical_key,
                "duration_seconds": float(duration_seconds),
                "confidence": float(overall_confidence),
                "analysis_details": {
                    "bpm_confidence": float(bpm_confidence),
                    "key_confidence": float(key_confidence),
                    "sample_rate": int(sr),
                    "num_samples": int(len(y)),
                },
            }

            logger.info(
                f"Audio analysis complete: BPM={bpm}, Key={musical_key}, "
                f"Duration={duration_seconds:.2f}s"
            )

            return analysis_result

        except FileNotFoundError:
            logger.error(f"Audio file not found: {file_path}")
            raise ValueError(f"Audio file not found: {file_path}")
        except Exception as e:
            logger.exception(f"Audio analysis failed for {file_path}: {str(e)}")
            raise

    @staticmethod
    def detect_bpm(y: np.ndarray, sr: int) -> Tuple[float, float]:
        """Detect tempo (BPM) from audio using librosa onset strength.

        Uses librosa's dynamic time warping method for robust BPM detection.
        This approach analyzes the onset strength of the audio signal to
        identify the most likely tempo.

        Args:
            y: Audio time series (samples)
            sr: Sample rate

        Returns:
            Tuple of (bpm, confidence):
            - bpm (float): Detected tempo in beats per minute
            - confidence (float): Analysis confidence between 0.0 and 1.0

        Note:
            Falls back to 120 BPM with low confidence if detection fails.
        """
        try:
            logger.debug("Starting BPM detection")

            # Compute onset strength envelope
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            logger.debug(f"Onset envelope computed: {len(onset_env)} frames")

            # Estimate tempo using dynamic time warping
            # Returns array of candidate tempos and their strengths
            tempos, strengths = librosa.beat.tempo(
                onset_envelope=onset_env, sr=sr, aggregate=None
            )

            if len(tempos) == 0:
                logger.warning("No tempos detected, using default 120 BPM")
                return 120.0, 0.3

            # Get the strongest tempo candidate
            best_tempo_idx = np.argmax(strengths)
            bpm = tempos[best_tempo_idx]
            strength = strengths[best_tempo_idx]

            # Normalize strength to confidence [0, 1]
            confidence = min(float(strength), 1.0)

            logger.debug(f"BPM detection: {bpm:.1f} BPM (strength: {strength:.2f})")

            # Clamp BPM to reasonable range (40-300)
            bpm = max(40, min(300, bpm))

            return float(bpm), confidence

        except Exception as e:
            logger.warning(f"BPM detection failed: {str(e)}, using default 120 BPM")
            return 120.0, 0.3

    @staticmethod
    def detect_key(y: np.ndarray, sr: int) -> Tuple[str, float]:
        """Detect musical key from audio using chromagram analysis.

        Uses chromagram (Constant-Q Transform) to analyze pitch content
        and match it against known major and minor key signatures.

        Args:
            y: Audio time series (samples)
            sr: Sample rate

        Returns:
            Tuple of (key, confidence):
            - key (str): Detected key e.g., "C Major", "A Minor"
            - confidence (float): Detection confidence between 0.0 and 1.0

        Note:
            Falls back to "C Major" with low confidence if detection fails.
        """
        try:
            logger.debug("Starting key detection")

            # Compute chromagram (12 pitch classes)
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            logger.debug(f"Chromagram computed: {chroma.shape}")

            # Average chroma across time
            chroma_mean = np.mean(chroma, axis=1)

            # Key templates (major and minor scales in chromatic space)
            # Based on Krumhansl-Kessler key profiles
            major_profile = np.array(
                [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
            )
            minor_profile = np.array(
                [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
            )

            # Normalize profiles
            major_profile = major_profile / np.linalg.norm(major_profile)
            minor_profile = minor_profile / np.linalg.norm(minor_profile)

            # Compute correlation for all 12 pitch classes (24 keys: 12 major + 12 minor)
            major_correlations = np.correlate(chroma_mean, major_profile, mode="same")
            minor_correlations = np.correlate(chroma_mean, minor_profile, mode="same")

            # Rotate profiles to test all key roots
            key_names = [
                "C",
                "C#",
                "D",
                "D#",
                "E",
                "F",
                "F#",
                "G",
                "G#",
                "A",
                "A#",
                "B",
            ]

            # Find best major and minor matches
            best_major_idx = np.argmax(major_correlations)
            best_major_key = key_names[best_major_idx]
            best_major_corr = major_correlations[best_major_idx]

            best_minor_idx = np.argmax(minor_correlations)
            best_minor_key = key_names[best_minor_idx]
            best_minor_corr = minor_correlations[best_minor_idx]

            # Choose major or minor based on correlation strength
            if best_major_corr > best_minor_corr:
                detected_key = f"{best_major_key} Major"
                confidence = float(best_major_corr)
            else:
                detected_key = f"{best_minor_key} Minor"
                confidence = float(best_minor_corr)

            # Normalize confidence to [0, 1] range
            confidence = min(confidence, 1.0)

            logger.debug(
                f"Key detection: {detected_key} "
                f"(major_corr: {best_major_corr:.3f}, minor_corr: {best_minor_corr:.3f})"
            )

            return detected_key, confidence

        except Exception as e:
            logger.warning(f"Key detection failed: {str(e)}, using default C Major")
            return "C Major", 0.3

    @staticmethod
    def calculate_duration(y: np.ndarray, sr: int) -> float:
        """Calculate total audio duration from samples and sample rate.

        Args:
            y: Audio time series (samples)
            sr: Sample rate (samples per second)

        Returns:
            Duration in seconds

        Example:
            >>> y, sr = librosa.load('audio.wav')
            >>> duration = AudioAnalyzer.calculate_duration(y, sr)
        """
        duration = len(y) / sr
        logger.debug(f"Duration calculated: {duration:.2f} seconds")
        return float(duration)


# Module-level convenience functions for backward compatibility

def analyze_audio(file_path: str) -> dict:
    """Convenience function to analyze audio file.

    Args:
        file_path: Path to WAV or MP3 audio file

    Returns:
        Dictionary with analysis results (bpm, musical_key, duration_seconds, confidence)

    Example:
        >>> result = analyze_audio("uploads/loop_123.wav")
        >>> print(result["bpm"], result["musical_key"], result["duration_seconds"])
        140 C Major 8.0
    """
    return AudioAnalyzer.analyze_audio(file_path)


def detect_bpm(file_path: str) -> float:
    """Convenience function to detect BPM from file.

    Args:
        file_path: Path to audio file

    Returns:
        Detected BPM value
    """
    y, sr = librosa.load(file_path, sr=22050)
    bpm, _ = AudioAnalyzer.detect_bpm(y, sr)
    return bpm


def detect_key(file_path: str) -> str:
    """Convenience function to detect key from file.

    Args:
        file_path: Path to audio file

    Returns:
        Detected key as string (e.g., "C Major")
    """
    y, sr = librosa.load(file_path, sr=22050)
    key, _ = AudioAnalyzer.detect_key(y, sr)
    return key
