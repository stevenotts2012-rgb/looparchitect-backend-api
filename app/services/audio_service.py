"""
Audio analysis and processing service.

Handles:
- BPM detection
- Musical key detection
- Duration analysis
- Loop extension
- Beat generation

Uses librosa for analysis and pydub for manipulation.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import librosa
import numpy as np
from pydub import AudioSegment

logger = logging.getLogger(__name__)


class AudioService:
    """Service for audio analysis and processing operations."""

    def __init__(self):
        """Initialize audio service."""
        logger.info("AudioService initialized")

    def analyze_loop(self, audio_path: str) -> Dict[str, any]:
        """
        Analyze an audio file to detect BPM, key, and duration.

        This function is designed to be called in background tasks.

        Args:
            audio_path: Path to the audio file (local filesystem)

        Returns:
            Dictionary containing:
                - bpm: Detected beats per minute
                - key: Musical key (C, D, E, etc.)
                - duration: Duration in seconds
                - sample_rate: Sample rate in Hz
                - channels: Number of audio channels

        Raises:
            FileNotFoundError: If audio file doesn't exist
            Exception: If analysis fails
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        try:
            logger.info(f"Analyzing audio: {audio_path}")

            # Load audio file using librosa
            y, sr = librosa.load(audio_path, sr=None, mono=True)

            # Detect BPM
            bpm = self._detect_bpm(y, sr)

            # Detect musical key
            key = self._detect_key(y, sr)

            # Calculate duration
            duration = librosa.get_duration(y=y, sr=sr)

            # Get additional metadata using pydub
            audio = AudioSegment.from_file(audio_path)
            channels = audio.channels

            analysis_result = {
                "bpm": round(bpm, 2),
                "key": key,
                "duration_seconds": round(duration, 2),
                "sample_rate": sr,
                "channels": channels,
            }

            logger.info(f"Analysis complete: BPM={bpm}, Key={key}, Duration={duration}s")
            return analysis_result

        except Exception as e:
            logger.error(f"Audio analysis failed: {e}")
            raise

    def _detect_bpm(self, y: np.ndarray, sr: int) -> float:
        """
        Detect BPM using librosa's beat tracking.

        Args:
            y: Audio time series
            sr: Sample rate

        Returns:
            Detected BPM
        """
        try:
            # Use onset strength for tempo detection
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            tempo = librosa.beat.tempo(onset_envelope=onset_env, sr=sr)

            # tempo returns an array, get the first value
            bpm = float(tempo[0])

            # Validate BPM is in reasonable range (40-250)
            if bpm < 40:
                bpm = bpm * 2  # Might be half-time
            elif bpm > 250:
                bpm = bpm / 2  # Might be double-time

            return bpm
        except Exception as e:
            logger.warning(f"BPM detection failed, using default: {e}")
            return 120.0  # Default BPM

    def _detect_key(self, y: np.ndarray, sr: int) -> str:
        """
        Detect musical key using chroma features.

        Args:
            y: Audio time series
            sr: Sample rate

        Returns:
            Musical key (e.g., "C", "G#", "Dm")
        """
        try:
            # Compute chroma features
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)

            # Average chroma across time
            chroma_mean = np.mean(chroma, axis=1)

            # Find the most prominent pitch class
            key_index = np.argmax(chroma_mean)

            # Map index to pitch class
            pitch_classes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            key = pitch_classes[key_index]

            return key
        except Exception as e:
            logger.warning(f"Key detection failed, using default: {e}")
            return "C"  # Default key

    def extend_loop(
        self,
        audio_path: str,
        output_path: str,
        bars: int,
        bpm: Optional[float] = None
    ) -> Tuple[str, Dict[str, any]]:
        """
        Extend a loop by repeating it for a specified number of bars.

        This function is designed for background task execution.

        Args:
            audio_path: Path to source audio file
            output_path: Path where extended audio will be saved
            bars: Number of bars to extend to
            bpm: Beats per minute (detected if not provided)

        Returns:
            Tuple of (output_path, metadata_dict)

        Raises:
            FileNotFoundError: If source file doesn't exist
            Exception: If extension fails
        """
        source = Path(audio_path)
        if not source.exists():
            raise FileNotFoundError(f"Source audio not found: {audio_path}")

        try:
            logger.info(f"Extending loop: {audio_path} to {bars} bars")

            # Load audio
            audio = AudioSegment.from_file(audio_path)

            # If BPM not provided, detect it
            if bpm is None:
                y, sr = librosa.load(audio_path, sr=None)
                bpm = self._detect_bpm(y, sr)

            # Calculate target duration
            # 1 bar = 4 beats, duration = (bars * 4) / bpm * 60
            beats_per_bar = 4
            target_duration_ms = (bars * beats_per_bar * 60 / bpm) * 1000

            # Current duration
            current_duration_ms = len(audio)

            # Calculate number of loops needed
            loops_needed = int(np.ceil(target_duration_ms / current_duration_ms))

            # Repeat audio
            extended = audio * loops_needed

            # Trim to exact target duration
            extended = extended[:int(target_duration_ms)]

            # Export
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            extended.export(output_path, format="wav")

            metadata = {
                "bars": bars,
                "bpm": round(bpm, 2),
                "duration_seconds": round(target_duration_ms / 1000, 2),
                "loops_repeated": loops_needed,
            }

            logger.info(f"Loop extended successfully: {output_path}")
            return output_path, metadata

        except Exception as e:
            logger.error(f"Loop extension failed: {e}")
            raise

    def generate_full_beat(
        self,
        audio_path: str,
        output_path: str,
        target_length_seconds: int,
        bpm: Optional[float] = None
    ) -> Tuple[str, Dict[str, any]]:
        """
        Generate a full beat by extending and arranging a loop.

        This function is designed for background task execution.

        Args:
            audio_path: Path to source loop file
            output_path: Path where generated beat will be saved
            target_length_seconds: Desired length in seconds
            bpm: Beats per minute (detected if not provided)

        Returns:
            Tuple of (output_path, metadata_dict)

        Raises:
            FileNotFoundError: If source file doesn't exist
            Exception: If generation fails
        """
        source = Path(audio_path)
        if not source.exists():
            raise FileNotFoundError(f"Source audio not found: {audio_path}")

        try:
            logger.info(
                f"Generating full beat: {audio_path} -> {target_length_seconds}s"
            )

            # Load audio
            audio = AudioSegment.from_file(audio_path)

            # Detect BPM if not provided
            if bpm is None:
                y, sr = librosa.load(audio_path, sr=None)
                bpm = self._detect_bpm(y, sr)

            # Calculate repetitions needed
            current_duration_ms = len(audio)
            target_duration_ms = target_length_seconds * 1000
            loops_needed = int(np.ceil(target_duration_ms / current_duration_ms))

            # Repeat loop
            extended = audio * loops_needed

            # Trim to exact target
            extended = extended[:target_duration_ms]

            # Apply basic arrangement structure
            # Intro: fade in first 2 seconds
            # Outro: fade out last 2 seconds
            fade_duration = min(2000, target_duration_ms // 10)  # 2s or 10% of total

            if len(extended) > fade_duration * 2:
                extended = extended.fade_in(fade_duration).fade_out(fade_duration)

            # Export
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            extended.export(output_path, format="wav")

            metadata = {
                "target_length_seconds": target_length_seconds,
                "actual_duration_seconds": len(extended) / 1000,
                "bpm": round(bpm, 2),
                "loops_repeated": loops_needed,
                "fade_duration_ms": fade_duration,
            }

            logger.info(f"Beat generated successfully: {output_path}")
            return output_path, metadata

        except Exception as e:
            logger.error(f"Beat generation failed: {e}")
            raise

    def get_audio_info(self, audio_path: str) -> Dict[str, any]:
        """
        Get basic audio file information without full analysis.

        Args:
            audio_path: Path to audio file

        Returns:
            Dictionary with basic audio info
        """
        try:
            audio = AudioSegment.from_file(audio_path)

            return {
                "duration_seconds": len(audio) / 1000,
                "channels": audio.channels,
                "sample_width": audio.sample_width,
                "frame_rate": audio.frame_rate,
                "frame_count": audio.frame_count(),
            }
        except Exception as e:
            logger.error(f"Failed to get audio info: {e}")
            raise


# Global audio service instance
audio_service = AudioService()
