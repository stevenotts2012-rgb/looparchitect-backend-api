"""Helpers for instrumental_renderer - copied/adapted from arrangement_jobs.py"""

import io

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
