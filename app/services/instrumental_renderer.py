"""Helpers for instrumental_renderer - copied/adapted from arrangement_jobs.py"""

import io
import os
import uuid
from pathlib import Path
from typing import List

from pydub import AudioSegment

RENDERS_DIR = "renders"


def _load_audio_segment_from_wav_bytes(wav_bytes: bytes) -> AudioSegment:
    """Load audio bytes multi-format fallback."""
    if not wav_bytes or len(wav_bytes) < 44:
        raise ValueError(f"Audio file too small")
    
    try:
        return AudioSegment.from_file(io.BytesIO(wav_bytes))
    except:
        try:
            return AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
        except:
            # ffmpeg fallback stub - add subprocess if needed
            raise ValueError("Audio decode failed")


def _repeat_to_duration(audio: AudioSegment, target_ms: int) -> AudioSegment:
    """Repeat audio to reach target duration."""
    if target_ms <= 0:
        return AudioSegment.silent(duration=0)
    repeats = (target_ms // len(audio)) + 1
    return (audio * repeats)[:target_ms]


def render_and_export_instrumental(
    loop_id: int,
    file_path: str,
    arrangement: List[str],
    bpm: int,
    target_length_seconds: int,
) -> dict:
    """Render an arrangement of a loop audio file and export it as a WAV.

    Loads the audio at *file_path*, divides *target_length_seconds* evenly
    across the requested *arrangement* sections, loops/trims each section to
    its target duration, concatenates the sections, and writes the result to
    ``renders/render_<loop_id>_<uuid>.wav``.

    Args:
        loop_id: Database ID of the source loop.
        file_path: Absolute or relative path to the source audio file.
        arrangement: Ordered list of section names (e.g. ["Intro", "Verse", "Chorus"]).
        bpm: Tempo in beats-per-minute (accepted for API compatibility; reserved
            for future bar-aligned rendering).
        target_length_seconds: Total desired output duration in seconds.

    Returns:
        A dict with keys:
            ``render_url`` – relative URL path to the rendered file.
            ``status``     – ``"completed"`` on success.

    Raises:
        FileNotFoundError: If *file_path* does not exist.
        ValueError: If the audio file cannot be decoded.
    """
    resolved = Path(file_path)
    if not resolved.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    loop_audio = AudioSegment.from_file(str(resolved))
    if len(loop_audio) == 0:
        raise ValueError("Audio file is empty")

    target_ms = target_length_seconds * 1000
    sections = arrangement if arrangement else ["Main"]
    section_ms = target_ms // len(sections)

    final_audio = AudioSegment.empty()
    for _ in sections:
        final_audio += _repeat_to_duration(loop_audio, section_ms)

    # Trim to exact target length in case of rounding
    final_audio = final_audio[:target_ms]

    os.makedirs(RENDERS_DIR, exist_ok=True)
    filename = f"render_{loop_id}_{uuid.uuid4().hex[:8]}.wav"
    out_path = Path(RENDERS_DIR) / filename
    final_audio.export(str(out_path), format="wav")

    return {
        "render_url": f"/api/v1/renders/{filename}",
        "status": "completed",
    }
