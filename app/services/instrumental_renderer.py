# app/services/instrumental_renderer.py

import os
import uuid
from pathlib import Path
from typing import Dict, List
from pydub import AudioSegment

UPLOADS_DIR = "uploads"
RENDERS_DIR = "renders"


def resolve_audio_file_path(file_url: str) -> Path:
    """
    Resolve loop audio file path from file_url.
    
    Args:
        file_url: File URL (e.g. "/uploads/filename.wav" or "uploads/filename.wav")
        
    Returns:
        Full path to the audio file
        
    Raises:
        FileNotFoundError: If audio file does not exist
    """
    if file_url.startswith("http"):
        raise ValueError("Remote file_url not supported yet")

    if file_url.startswith("/uploads/"):
        file_path = file_url.replace("/uploads/", "")
    elif file_url.startswith("uploads/"):
        file_path = file_url.replace("uploads/", "")
    else:
        file_path = file_url

    full_path = Path(UPLOADS_DIR) / file_path

    if not full_path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    return full_path


def load_loop_audio(file_url: str) -> AudioSegment:
    """
    Load loop audio from file_url.
    
    Args:
        file_url: File URL to load
        
    Returns:
        AudioSegment object
        
    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file cannot be parsed as audio
    """
    audio_path = resolve_audio_file_path(file_url)
    
    try:
        audio = AudioSegment.from_file(str(audio_path))
        return audio
    except Exception as exc:
        raise ValueError(f"Failed to load audio file: {str(exc)}") from exc


def extend_audio_to_duration(loop_audio: AudioSegment, duration_ms: int) -> AudioSegment:
    """
    Extend loop audio to match requested duration by repeating.
    
    Args:
        loop_audio: Original loop audio segment
        duration_ms: Target duration in milliseconds
        
    Returns:
        Extended audio segment matching the target duration
    """
    if duration_ms <= 0:
        return AudioSegment.empty()
    
    extended_audio = AudioSegment.empty()
    current_duration = 0
    
    while current_duration < duration_ms:
        remaining = duration_ms - current_duration
        if remaining >= len(loop_audio):
            extended_audio += loop_audio
            current_duration += len(loop_audio)
        else:
            extended_audio += loop_audio[:remaining]
            current_duration += remaining
    
    return extended_audio


def render_instrumental(
    loop_audio: AudioSegment,
    arrangement: List[Dict],
    bpm: float = 140.0
) -> AudioSegment:
    """
    Render a full instrumental track by repeating loop audio across arrangement sections.
    
    Takes a loop and an arrangement (list of sections with bar counts) and builds
    a full instrumental by repeating the loop to match each section's duration.
    
    Args:
        loop_audio: AudioSegment of the original loop
        arrangement: List of dicts with keys: "section" and "bars"
                     Example: [{"section": "Intro", "bars": 4}, ...]
        bpm: Tempo in beats per minute (default 140)
        
    Returns:
        AudioSegment containing the full instrumental track
        
    Raises:
        ValueError: If arrangement is invalid or rendering fails
    """
    if not arrangement:
        raise ValueError("Arrangement cannot be empty")
    
    if bpm <= 0:
        raise ValueError("BPM must be positive")
    
    # Calculate milliseconds per bar: (60 / bpm) * 4 * 1000
    ms_per_bar = (60 / bpm) * 4 * 1000
    
    final_audio = AudioSegment.empty()
    
    try:
        for section in arrangement:
            bars = section.get("bars", 4)
            if bars < 1:
                continue
            
            section_duration_ms = int(bars * ms_per_bar)
            
            # Extend loop audio to match section duration
            section_audio = extend_audio_to_duration(loop_audio, section_duration_ms)
            
            # Concatenate to final track
            final_audio += section_audio
    except Exception as exc:
        raise ValueError(f"Failed to render instrumental: {str(exc)}") from exc
    
    return final_audio


def export_instrumental(
    audio: AudioSegment,
    loop_id: int,
    format: str = "wav"
) -> str:
    """
    Export instrumental audio to /renders folder.
    
    Args:
        audio: AudioSegment to export
        loop_id: Loop ID (used in filename)
        format: Audio format (default "wav")
        
    Returns:
        Relative file URL (e.g. "/renders/render_1_abc123.wav")
        
    Raises:
        ValueError: If export fails
    """
    # Create renders directory if it doesn't exist
    os.makedirs(RENDERS_DIR, exist_ok=True)
    
    # Generate unique filename
    filename = f"render_{loop_id}_{uuid.uuid4().hex[:8]}.{format}"
    out_path = Path(RENDERS_DIR) / filename
    
    try:
        audio.export(str(out_path), format=format)
    except Exception as exc:
        raise ValueError(f"Failed to export instrumental: {str(exc)}") from exc
    
    return f"/renders/{filename}"


def render_and_export(
    file_url: str,
    arrangement: List[Dict],
    loop_id: int,
    bpm: float = 140.0
) -> str:
    """
    Complete pipeline: load audio → render instrumental → export to file.
    
    Convenience function that combines load_loop_audio, render_instrumental,
    and export_instrumental.
    
    Args:
        file_url: File URL of the loop audio
        arrangement: List of arrangement sections with bar counts
        loop_id: Loop ID (used in filename)
        bpm: Tempo in beats per minute (default 140)
        
    Returns:
        File URL of the rendered instrumental
        
    Raises:
        FileNotFoundError: If audio file not found
        ValueError: If rendering or export fails
    """
    # Load loop audio
    loop_audio = load_loop_audio(file_url)
    
    # Render instrumental
    instrumental = render_instrumental(loop_audio, arrangement, bpm)
    
    # Export to file
    render_url = export_instrumental(instrumental, loop_id)
    
    return render_url
