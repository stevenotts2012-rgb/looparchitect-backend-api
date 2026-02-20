import os
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydub import AudioSegment
from pydub.effects import low_pass_filter, high_pass_filter, normalize
import random

from app.db import get_db
from app.models.loop import Loop

router = APIRouter()

RENDERS_DIR = "renders"
UPLOADS_DIR = "uploads"


# Pydantic models for request/response
from pydantic import BaseModel


class ArrangementConfig(BaseModel):
    genre: Optional[str] = "Trap"
    length_seconds: Optional[int] = 180
    structure: Optional[str] = "default"
    energy: Optional[str] = "high"
    bpm: Optional[float] = None
    key: Optional[str] = None


class ArrangementSection(BaseModel):
    name: str
    start_time: float
    duration: float
    transformations: list[str]


class ArrangementPlan(BaseModel):
    loop_id: int
    total_duration: float
    bpm: Optional[float]
    key: Optional[str]
    sections: list[ArrangementSection]


class RenderResponse(BaseModel):
    loop_id: int
    wav_url: str
    mp3_url: str


@router.post("/loops/{loop_id}/arrange", response_model=ArrangementPlan)
def create_arrangement(
    loop_id: int,
    config: ArrangementConfig = ArrangementConfig(),
    db: Session = Depends(get_db)
):
    """Generate an arrangement plan for a loop."""
    # Find the loop
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    # Use config BPM/key or fall back to loop's stored values or defaults
    bpm = config.bpm or loop.tempo or 140.0
    key = config.key or loop.key or "C minor"
    
    # Generate arrangement sections based on structure
    sections = _generate_sections(config, bpm)
    
    return ArrangementPlan(
        loop_id=loop_id,
        total_duration=config.length_seconds,
        bpm=bpm,
        key=key,
        sections=sections
    )


def _generate_sections(config: ArrangementConfig, bpm: float) -> list[ArrangementSection]:
    """Generate arrangement sections based on config."""
    sections = []
    duration = config.length_seconds
    
    if config.structure == "default":
        # Simple structure: intro, build, drop, outro
        intro_duration = 16 * (60 / bpm) * 4  # 16 bars
        build_duration = 16 * (60 / bpm) * 4
        drop_duration = 32 * (60 / bpm) * 4
        outro_duration = duration - intro_duration - build_duration - drop_duration
        
        current_time = 0.0
        
        sections.append(ArrangementSection(
            name="intro",
            start_time=current_time,
            duration=intro_duration,
            transformations=["lowpass", "fade_in"]
        ))
        current_time += intro_duration
        
        sections.append(ArrangementSection(
            name="build",
            start_time=current_time,
            duration=build_duration,
            transformations=["highpass", "stutter"]
        ))
        current_time += build_duration
        
        sections.append(ArrangementSection(
            name="drop",
            start_time=current_time,
            duration=drop_duration,
            transformations=["normalize", "pitch_shift_down"]
        ))
        current_time += drop_duration
        
        sections.append(ArrangementSection(
            name="outro",
            start_time=current_time,
            duration=outro_duration,
            transformations=["reverse", "fade_out"]
        ))
    
    return sections


@router.post("/loops/{loop_id}/render", response_model=RenderResponse)
async def render_arrangement(
    loop_id: int,
    config: Optional[ArrangementConfig] = None,
    db: Session = Depends(get_db)
):
    """Render a full arrangement from a loop."""
    # Find the loop
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    if not loop.file_url:
        raise HTTPException(status_code=400, detail="Loop has no audio file")
    
    # Load the audio file
    file_path = loop.file_url.replace("/uploads/", "")
    full_path = Path(UPLOADS_DIR) / file_path
    
    if not full_path.exists():
        raise HTTPException(status_code=400, detail=f"Audio file not found: {file_path}")
    
    try:
        # Load audio
        audio = AudioSegment.from_file(str(full_path))
        
        # Generate arrangement plan if not provided
        if config is None:
            config = ArrangementConfig()
        
        arrangement_plan = create_arrangement(loop_id, config, db)
        
        # Build the full arrangement
        full_arrangement = _build_arrangement(audio, arrangement_plan)
        
        # Create renders directory
        os.makedirs(RENDERS_DIR, exist_ok=True)
        
        # Generate unique filename
        render_id = uuid.uuid4()
        wav_filename = f"{render_id}.wav"
        mp3_filename = f"{render_id}.mp3"
        
        wav_path = Path(RENDERS_DIR) / wav_filename
        mp3_path = Path(RENDERS_DIR) / mp3_filename
        
        # Export WAV
        full_arrangement.export(str(wav_path), format="wav")
        
        # Export MP3
        full_arrangement.export(str(mp3_path), format="mp3", bitrate="320k")
        
        return RenderResponse(
            loop_id=loop_id,
            wav_url=f"/renders/{wav_filename}",
            mp3_url=f"/renders/{mp3_filename}"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {str(e)}")


def _build_arrangement(audio: AudioSegment, plan: ArrangementPlan) -> AudioSegment:
    """Build full arrangement by applying transformations to loop."""
    full_track = AudioSegment.silent(duration=0)
    loop_duration_ms = len(audio)
    
    for section in plan.sections:
        section_duration_ms = int(section.duration * 1000)
        section_audio = AudioSegment.silent(duration=0)
        
        # Repeat loop to fill section duration
        while len(section_audio) < section_duration_ms:
            loop_copy = audio[:]
            
            # Apply transformations
            for transform in section.transformations:
                loop_copy = _apply_transformation(loop_copy, transform)
            
            section_audio += loop_copy
        
        # Trim to exact section duration
        section_audio = section_audio[:section_duration_ms]
        
        # Add to full track
        full_track += section_audio
    
    return full_track


def _apply_transformation(audio: AudioSegment, transform: str) -> AudioSegment:
    """Apply a single transformation to audio."""
    if transform == "lowpass":
        return low_pass_filter(audio, 500)
    
    elif transform == "highpass":
        return high_pass_filter(audio, 300)
    
    elif transform == "normalize":
        return normalize(audio)
    
    elif transform == "pitch_shift_up":
        # Pitch shift up by changing sample rate
        return audio._spawn(audio.raw_data, overrides={
            "frame_rate": int(audio.frame_rate * 1.5)
        }).set_frame_rate(audio.frame_rate)
    
    elif transform == "pitch_shift_down":
        # Pitch shift down by changing sample rate
        return audio._spawn(audio.raw_data, overrides={
            "frame_rate": int(audio.frame_rate * 0.75)
        }).set_frame_rate(audio.frame_rate)
    
    elif transform == "reverse":
        return audio.reverse()
    
    elif transform == "stutter":
        # Create stutter effect by repeating small slices
        slice_duration = 125  # ms
        stuttered = AudioSegment.silent(duration=0)
        for i in range(0, len(audio), slice_duration * 2):
            slice_audio = audio[i:i+slice_duration]
            stuttered += slice_audio * 2
        return stuttered[:len(audio)]
    
    elif transform == "fade_in":
        return audio.fade_in(2000)
    
    elif transform == "fade_out":
        return audio.fade_out(2000)
    
    else:
        return audio
