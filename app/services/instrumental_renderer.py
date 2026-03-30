"""Helpers for instrumental_renderer - copied/adapted from arrangement_jobs.py"""

import io
import os
import uuid
from pydub import AudioSegment

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
    arrangement: list,
    bpm: float,
    target_length_seconds: float = 180,
) -> dict:
    """Render a loop file to a target length and export it.

    Args:
        loop_id: ID of the source loop.
        file_path: Path to the source audio file.
        arrangement: List of section names (e.g. ["Intro", "Verse", "Chorus"]).
        bpm: BPM of the source loop.
        target_length_seconds: Desired render length in seconds.

    Returns:
        dict with keys ``render_url`` (str) and ``status`` (str).

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
        ValueError: If the audio cannot be decoded.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    with open(file_path, "rb") as fh:
        audio = _load_audio_segment_from_wav_bytes(fh.read())

    target_ms = int(target_length_seconds * 1000)
    rendered = _repeat_to_duration(audio, target_ms)

    os.makedirs("renders", exist_ok=True)
    render_filename = f"render_{loop_id}_{uuid.uuid4()}.wav"
    render_path = os.path.join("renders", render_filename)
    rendered.export(render_path, format="wav")

    return {
        "render_url": f"/renders/{render_filename}",
        "status": "completed",
    }
