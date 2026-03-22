"""Instrumental renderer service with pydub helpers."""

import io
import uuid
from pathlib import Path
from typing import List, Dict, Any
from pydub import AudioSegment
from app.services.storage import storage

def render_and_export_instrumental(
    loop_id: int,
    file_path: str,
    arrangement: List[str],
    bpm: float,
    target_length_seconds: int
) -> Dict[str, Any]:
    """Render instrumental track from loop using arrangement."""
    # Load audio
    if Path(file_path).exists():
        audio = AudioSegment.from_file(file_path)
    else:
        # Remote/S3 presign handled by storage
        signed_url = storage.create_presigned_get_url(file_path)
        audio = AudioSegment.from_file(signed_url)
    
    # Simple repeat to target length
    ms_per_beat = (60 * 1000) / bpm
    bars_total = int((target_length_seconds * bpm) / (4 * 60))
    ms_total = bars_total * 4 * ms_per_beat
    render_audio = _repeat_to_duration(audio, ms_total)
    
    # Export
    filename = f"render_{loop_id}_{uuid.uuid4().hex[:8]}.wav"
    out_path = Path("renders") / filename
    out_path.parent.mkdir(exist_ok=True)
    render_audio.export(out_path, format="wav")
    
    return {
        "render_url": f"/api/v1/renders/{filename}",
        "status": "completed",
        "arrangement": arrangement,
        "bpm": bpm,
        "length_seconds": target_length_seconds
    }

# Helper functions (from previous fixes)
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
            raise ValueError("Audio decode failed")

def _repeat_to_duration(audio: AudioSegment, target_ms: int) -> AudioSegment:
    """Repeat audio to reach target duration."""
    if target_ms <= 0:
        return AudioSegment.silent(duration=0)
    repeats = (target_ms // len(audio)) + 1
    return (audio * repeats)[:target_ms]
