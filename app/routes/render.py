import os
import uuid
import re
import math
import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pydub import AudioSegment
from pydub.effects import normalize
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.services.arranger import create_arrangement
from app.services.instrumental_renderer import render_and_export_instrumental
from app.services.render_service import render_loop as render_loop_async

UPLOADS_DIR = "uploads"
RENDERS_DIR = "renders"
GENERIC_VARIATIONS = ["Commercial", "Creative", "Experimental"]

# Safety limits to protect server from realtime generation overload
MAX_SECONDS = 21600  # 6 hours
MAX_BARS = 4096

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Request Models ────────────────────────────────────────────────────────────

class RenderConfig(BaseModel):
    genre: Optional[str] = "Trap"
    length_seconds: Optional[int] = 180
    energy: Optional[str] = "high"
    variations: Optional[int] = 3
    variation_styles: Optional[List[str]] = None
    custom_style: Optional[str] = None


class RenderRequest(BaseModel):
    length_seconds: Optional[int] = None
    total_bars: Optional[int] = None
    bpm: Optional[float] = None


class ArrangementConfig(BaseModel):
    genre: Optional[str] = "Trap"
    length_seconds: Optional[int] = 180
    structure: Optional[str] = "default"
    energy: Optional[str] = "high"
    bpm: Optional[float] = None
    key: Optional[str] = None
    variation_styles: Optional[List[str]] = None
    custom_style: Optional[str] = None


# ── Response Models ───────────────────────────────────────────────────────────

class Section(BaseModel):
    name: str
    start_bar: int
    end_bar: int


class ArrangementPlan(BaseModel):
    loop_id: int
    genre: str
    bpm: Optional[float]
    key: Optional[str]
    structure: str
    sections: List[Section]


class VariationResult(BaseModel):
    name: str
    style_hint: Optional[str]
    file_url: str


class MultiRenderResponse(BaseModel):
    loop_id: int
    variations: List[VariationResult]


class RenderResponse(BaseModel):
    render_url: str
    loop_id: int


class RenderPipelineResponse(BaseModel):
    """Response from full render pipeline."""
    status: str
    render_id: str
    loop_id: int
    download_url: str
    analysis: Optional[dict] = None
    arrangement: Optional[dict] = None
    error: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert text to safe filename slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '_', text)
    return text


def _resolve_audio_file_path(file_url: str) -> Optional[Path]:
    """Resolve loop audio file path from file_url.
    
    Returns:
        Path object for local files, None for remote URLs (http/https)
    """
    if file_url.startswith("http"):
        # Remote URL - return None to indicate simulation mode
        # TODO: In real implementation, download the file
        return None

    if file_url.startswith("/uploads/"):
        file_path = file_url.replace("/uploads/", "")
    elif file_url.startswith("uploads/"):
        file_path = file_url.replace("uploads/", "")
    else:
        file_path = file_url

    full_path = Path(UPLOADS_DIR) / file_path

    if not full_path.exists():
        raise HTTPException(status_code=400, detail=f"Audio file not found: {file_path}")

    return full_path


def _generate_sections(structure: str, length_seconds: int) -> List[Section]:
    """Generate arrangement sections based on structure type."""
    bars = max(1, length_seconds // 2)
    if structure == "default":
        return [
            Section(name="intro", start_bar=0, end_bar=bars // 8),
            Section(name="verse", start_bar=bars // 8, end_bar=bars // 2),
            Section(name="chorus", start_bar=bars // 2, end_bar=3 * bars // 4),
            Section(name="outro", start_bar=3 * bars // 4, end_bar=bars),
        ]
    return [Section(name="main", start_bar=0, end_bar=bars)]


def _get_transformations_for_style(style: str) -> List[str]:
    """Return audio transformations appropriate for a named style."""
    style_lower = style.lower()
    if "atl" in style_lower or "trap" in style_lower:
        return ["normalize", "low_pass_filter", "fade_in", "fade_out"]
    if "detroit" in style_lower:
        return ["normalize", "high_pass", "fade_in", "fade_out"]
    if "lofi" in style_lower or "lo-fi" in style_lower:
        return ["normalize", "low_pass_filter", "fade_in", "fade_out"]
    return ["normalize", "fade_in", "fade_out"]


def _get_default_transformations(name: str) -> List[str]:
    """Return default transformations for generic variation names."""
    if name == "commercial":
        return ["normalize", "fade_in", "fade_out"]
    if name == "creative":
        return ["normalize", "high_pass", "fade_in", "fade_out"]
    if name == "experimental":
        return ["normalize", "low_pass_filter", "fade_in", "fade_out"]
    return ["normalize", "fade_in", "fade_out"]


def _compute_variation_profiles(config: RenderConfig) -> List[dict]:
    """Compute variation profiles based on config."""
    profiles: List[dict] = []

    if config.variation_styles:
        for style in config.variation_styles[: config.variations]:
            profiles.append(
                {
                    "name": style.strip(),
                    "style_hint": style.strip(),
                    "transformations": _get_transformations_for_style(style),
                }
            )
    elif config.custom_style:
        profiles.append(
            {
                "name": "Custom",
                "style_hint": config.custom_style,
                "transformations": ["normalize", "fade_in", "fade_out"],
            }
        )

    while len(profiles) < config.variations:
        idx = len(profiles)
        if idx < len(GENERIC_VARIATIONS):
            name = GENERIC_VARIATIONS[idx]
            profiles.append(
                {
                    "name": name,
                    "style_hint": None,
                    "transformations": _get_default_transformations(name.lower()),
                }
            )
        else:
            break

    return profiles


def _apply_transformation(audio: AudioSegment, transformation: str) -> AudioSegment:
    """Apply a named transformation to an AudioSegment."""
    if transformation == "normalize":
        return normalize(audio)
    if transformation == "fade_in":
        return audio.fade_in(500)
    if transformation == "fade_out":
        return audio.fade_out(500)
    if transformation == "low_pass_filter":
        from pydub.effects import low_pass_filter
        return low_pass_filter(audio, 3000)
    if transformation == "high_pass":
        from pydub.effects import high_pass_filter
        return high_pass_filter(audio, 200)
    return audio


def _build_variation(audio: AudioSegment, transformations: List[str]) -> AudioSegment:
    """Apply a list of transformations sequentially."""
    for t in transformations:
        audio = _apply_transformation(audio, t)
    return audio


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/loops/{loop_id}/arrange", response_model=ArrangementPlan)
def arrange_loop(
    loop_id: int,
    config: ArrangementConfig = Body(default=ArrangementConfig()),
    db: Session = Depends(get_db),
):
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    genre = config.genre or loop.genre or "Trap"
    bpm = config.bpm or loop.tempo
    key = config.key or loop.key
    sections = _generate_sections(config.structure, config.length_seconds)

    return ArrangementPlan(
        loop_id=loop_id,
        genre=genre,
        bpm=bpm,
        key=key,
        structure=config.structure,
        sections=sections,
    )


@router.post("/loops/{loop_id}/render", response_model=MultiRenderResponse)
async def render_arrangement(
    loop_id: int,
    config: RenderConfig = Body(default=RenderConfig()),
    db: Session = Depends(get_db),
):
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    if not loop.file_url:
        raise HTTPException(status_code=400, detail="Loop has no associated audio file")

    audio_path = _resolve_audio_file_path(loop.file_url)
    
    # Handle remote URLs with simulation
    if audio_path is None:
        # SIMULATION: Remote file - generate fake renders
        os.makedirs(RENDERS_DIR, exist_ok=True)
        profiles = _compute_variation_profiles(config)
        results: List[VariationResult] = []
        
        for profile in profiles:
            slug = _slugify(profile["name"])
            filename = f"instrumental_{loop_id}_{slug}.wav"
            # TODO: Actually download and process remote file
            results.append(
                VariationResult(
                    name=profile["name"],
                    style_hint=profile.get("style_hint"),
                    file_url=f"/api/v1/renders/{filename}"
                )
            )
        
        return MultiRenderResponse(loop_id=loop_id, variations=results)
    
    # Local file processing (existing code)
    try:
        audio = AudioSegment.from_file(str(audio_path))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to load audio file: {exc}") from exc

    os.makedirs(RENDERS_DIR, exist_ok=True)
    profiles = _compute_variation_profiles(config)
    results: List[VariationResult] = []

    for profile in profiles:
        variation_audio = _build_variation(audio, profile["transformations"])
        slug = _slugify(profile["name"])
        filename = f"loop_{loop_id}_{slug}_{uuid.uuid4().hex[:8]}.wav"
        out_path = Path(RENDERS_DIR) / filename
        try:
            variation_audio.export(str(out_path), format="wav")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to export variation '{profile['name']}': {exc}") from exc
        results.append(
            VariationResult(
                name=profile["name"],
                style_hint=profile["style_hint"],
                file_url=f"/api/v1/renders/{filename}",
            )
        )

    return MultiRenderResponse(loop_id=loop_id, variations=results)


@router.post("/render/{loop_id}", response_model=RenderResponse)
def render_loop(
    loop_id: int,
    request: RenderRequest = Body(default=RenderRequest()),
    db: Session = Depends(get_db),
):
    """
    Render a loop by arranging it into sections.
    
    Creates a full instrumental track by extending the loop audio to match
    the arrangement sections, concatenates them, and saves as WAV.
    
    Accepts flexible length specification (same as arrange endpoint):
    - total_bars: Directly specify bar count (preferred if both provided)
    - length_seconds: Specify duration in seconds (converted to bars using BPM)
    - bpm: Optional BPM override (defaults to loop's tempo or 140)
    
    Args:
        loop_id: The ID of the loop to render
        request: RenderRequest with optional length_seconds, total_bars, or bpm
        db: Database session
    
    Returns:
        URL of the rendered audio file and loop_id
    
    Raises:
        HTTPException 404: If loop not found
        HTTPException 400: If loop has no audio file or parameters exceed safety limits
        HTTPException 422: If audio file cannot be loaded
        HTTPException 500: If arrangement generation or audio export fails
    """
    # Load loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    if not loop.file_url:
        raise HTTPException(status_code=400, detail="Loop has no associated audio file")

    # Load loop audio file
    audio_path = _resolve_audio_file_path(loop.file_url)
    
    # Handle remote URLs with simulation
    if audio_path is None:
        # SIMULATION: Remote file - generate fake render
        os.makedirs(RENDERS_DIR, exist_ok=True)
        filename = f"instrumental_{loop_id}.wav"
        # TODO: Actually download and process remote file
        return RenderResponse(
            render_url=f"/api/v1/renders/{filename}",
            loop_id=loop_id
        )
    
    # Local file processing (existing code)
    try:
        loop_audio = AudioSegment.from_file(str(audio_path))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to load audio file: {exc}") from exc

    # Determine BPM to use
    bpm = request.bpm or loop.tempo or 140.0
    
    # Determine bars_total based on priority: total_bars > length_seconds > default
    if request.total_bars is not None:
        bars_total = request.total_bars
    else:
        # Use length_seconds (default to 180 if not provided)
        length_seconds = request.length_seconds or 180
        
        # Validate length_seconds against safety limit
        if length_seconds > MAX_SECONDS:
            raise HTTPException(
                status_code=400,
                detail=f"Length {length_seconds}s exceeds maximum {MAX_SECONDS}s (6 hours). "
                        "Please request a shorter render for realtime generation."
            )
        if length_seconds < 1:
            raise HTTPException(status_code=400, detail="Length must be at least 1 second")
        
        # Convert length_seconds to bars: bars = round((length_seconds / 60) * (bpm / 4))
        bars_total = max(4, round((length_seconds / 60) * (bpm / 4)))
    
    # Validate bars_total against safety limit
    if bars_total > MAX_BARS:
        raise HTTPException(
            status_code=400,
            detail=f"Arrangement size {bars_total} bars exceeds maximum {MAX_BARS} bars. "
                    "Please request a shorter render for realtime generation."
        )
    if bars_total < 4:
        bars_total = 4
    
    # Get arrangement sections
    try:
        sections = create_arrangement()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate arrangement: {exc}") from exc

    # Scale sections to match bars_total
    current_total_bars = sum(section.get("bars", 4) for section in sections)
    
    if current_total_bars > 0 and bars_total > 0:
        scale_factor = bars_total / current_total_bars
        scaled_sections = []
        
        for i, section in enumerate(sections):
            bars = section.get("bars", 4)
            # For the last section, use remaining bars to ensure we hit exactly bars_total
            if i == len(sections) - 1:
                scaled_bars = bars_total - sum(s.get("bars", 4) for s in scaled_sections)
            else:
                scaled_bars = max(1, round(bars * scale_factor))
            
            scaled_section = section.copy()
            scaled_section["bars"] = scaled_bars
            scaled_sections.append(scaled_section)
    else:
        scaled_sections = sections

    # Calculate ms per bar
    ms_per_bar = (4 * 60 * 1000) / bpm
    
    # Concatenate sections
    final_audio = AudioSegment.empty()
    
    try:
        for section in scaled_sections:
            bars = section.get("bars", 4)
            section_duration_ms = int(bars * ms_per_bar)
            
            # Extend loop audio to match section duration by looping
            section_audio = AudioSegment.empty()
            current_duration = 0
            
            while current_duration < section_duration_ms:
                remaining = section_duration_ms - current_duration
                if remaining >= len(loop_audio):
                    section_audio += loop_audio
                    current_duration += len(loop_audio)
                else:
                    section_audio += loop_audio[:remaining]
                    current_duration += remaining
            
            # Concatenate to final track
            final_audio += section_audio
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build arrangement: {exc}") from exc

    # Export final render
    os.makedirs(RENDERS_DIR, exist_ok=True)
    filename = f"render_{loop_id}_{uuid.uuid4().hex[:8]}.wav"
    out_path = Path(RENDERS_DIR) / filename
    
    try:
        final_audio.export(str(out_path), format="wav")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to export render: {exc}") from exc

    return RenderResponse(
        render_url=f"/api/v1/renders/{filename}",
        loop_id=loop_id
    )


@router.post("/render-simulated/{loop_id}")
def render_loop_simulated(
    loop_id: int,
    db: Session = Depends(get_db),
):
    """
    Simulated render endpoint using the upgraded instrumental_renderer service.
    
    This endpoint demonstrates the new file upload support:
    1. Validates that the loop exists and has an uploaded audio file
    2. Checks that the file exists locally in /uploads
    3. Simulates rendering by calling render_and_export_instrumental
    4. Returns render_url and status
    
    NOTE: This is a simulation. No actual audio file is created yet.
    The real audio processing will be added later (see TODOs in instrumental_renderer.py).
    
    Args:
        loop_id: The ID of the loop to render
        db: Database session
    
    Returns:
        {
            "render_url": "/renders/render_<loop_id>_<uuid>.wav",
            "status": "completed",
            "loop_id": <loop_id>
        }
    
    Raises:
        HTTPException 404: If loop not found
        HTTPException 400: If loop has no associated audio file
        HTTPException 404: If audio file not found locally
    """
    # Step 1: Load loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    # Step 2: Validate that loop has an uploaded file
    if not loop.file_url:
        raise HTTPException(status_code=400, detail="Loop has no associated audio file")

    # Step 3: Define arrangement (hardcoded for simulation)
    # TODO: Accept arrangement from request body or generate dynamically
    arrangement = ["Intro", "Verse", "Chorus", "Verse", "Chorus", "Outro"]
    
    # Step 4: Get BPM (use loop's tempo or default)
    bpm = int(loop.tempo) if loop.tempo else 140
    
    # Step 5: Set target length (default 180 seconds = 3 minutes)
    target_length_seconds = 180
    
    # Step 6: Call the upgraded instrumental renderer service
    try:
        result = render_and_export_instrumental(
            loop_id=loop_id,
            file_path=loop.file_url,
            arrangement=arrangement,
            bpm=bpm,
            target_length_seconds=target_length_seconds
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Render failed: {str(e)}")
    
    # Step 7: Return success response
    return {
        "render_url": result["render_url"],
        "status": result["status"],
        "loop_id": loop_id
    }


@router.post("/render-pipeline/{loop_id}", response_model=RenderPipelineResponse)
async def render_with_pipeline(
    loop_id: int,
    request: Optional[RenderRequest] = Body(default=RenderRequest()),
    db: Session = Depends(get_db),
):
    """
    Render loop using full AI music pipeline.
    
    Complete processing pipeline:
    1. Analyze loop (detect BPM, key, duration)
    2. Slice loop into bar segments
    3. Generate song structure arrangement (Intro→Hook→Verse→Bridge→Outro)
    4. Render individual stems (drums, bass, melody, etc.)
    5. Mix down stems into final instrumental
    
    Args:
        loop_id: The ID of the loop to render
        request: RenderRequest with optional length_seconds override
        db: Database session
    
    Returns:
        RenderPipelineResponse with:
        - status: "render_started" or "completed"
        - render_id: Unique render session ID
        - download_url: URL to download final file
        - analysis: Detected BPM, key, duration, confidence
        - arrangement: Song structure with section timings
    
    Raises:
        HTTPException 404: If loop not found
        HTTPException 400: If loop has no audio file
    """
    # Load loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    if not loop.file_url:
        raise HTTPException(status_code=400, detail="Loop has no associated audio file")

    # Resolve audio file path
    file_path_obj = _resolve_audio_file_path(loop.file_url)
    if file_path_obj:
        file_path = str(file_path_obj)
    else:
        # For remote URLs, use the URL directly
        file_path = loop.file_url

    # Get target duration (default 180 seconds / 3 minutes)
    target_duration = request.length_seconds if request else 180
    if target_duration and target_duration > MAX_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Duration {target_duration}s exceeds maximum {MAX_SECONDS}s"
        )

    # Run async render pipeline
    logger.info(f"Starting render pipeline for loop {loop_id}")
    
    try:
        result = await render_loop_async(
            loop_id=loop_id,
            file_path=file_path,
            target_duration_seconds=target_duration or 180
        )
        
        if result.get("status") == "failed":
            raise HTTPException(status_code=500, detail=result.get("error", "Render failed"))
        
        return RenderPipelineResponse(
            status="completed",
            render_id=result.get("render_id", "unknown"),
            loop_id=loop_id,
            download_url=result.get("download_url", ""),
            analysis=result.get("analysis"),
            arrangement=result.get("arrangement")
        )
        
    except Exception as e:
        logger.error(f"Render pipeline failed: {e}")
        return RenderPipelineResponse(
            status="failed",
            render_id="error",
            loop_id=loop_id,
            download_url="",
            error=str(e)
        )


@router.get("/renders/{filename}")
def download_render(filename: str):
    """
    Download a rendered audio file.
    
    Security features:
    - Prevents path traversal attacks (rejects ".." and "/")
    - Only serves files from the renders directory
    - Returns 404 if file doesn't exist
    - Sets correct audio/wav media type
    
    Args:
        filename: Name of the rendered file (e.g., "instrumental_123.wav")
    
    Returns:
        FileResponse with the audio file
    
    Raises:
        HTTPException 400: If filename contains invalid characters
        HTTPException 404: If file not found
    """
    # Security: Prevent path traversal attacks
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=400, 
            detail="Invalid filename: path traversal not allowed"
        )
    
    # Construct safe file path
    file_path = Path(RENDERS_DIR) / filename
    
    # Check if file exists
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=404, 
            detail=f"Rendered file not found: {filename}"
        )
    
    # Return file with correct media type
    return FileResponse(
        path=str(file_path),
        media_type="audio/wav",
        filename=filename
    )


