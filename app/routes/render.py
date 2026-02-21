import os
import uuid
import re
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from pydub import AudioSegment
from pydub.effects import normalize
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop

UPLOADS_DIR = "uploads"
RENDERS_DIR = "renders"
GENERIC_VARIATIONS = ["Commercial", "Creative", "Experimental"]

router = APIRouter()


# ── Request Models ────────────────────────────────────────────────────────────

class RenderConfig(BaseModel):
    genre: Optional[str] = "Trap"
    length_seconds: Optional[int] = 180
    energy: Optional[str] = "high"
    variations: Optional[int] = 3
    variation_styles: Optional[List[str]] = None
    custom_style: Optional[str] = None


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert text to safe filename slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '_', text)
    return text


def _resolve_audio_file_path(file_url: str) -> Path:
    """Resolve loop audio file path from file_url."""
    if file_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Remote file_url not supported yet")

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
def create_arrangement(
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
                file_url=f"/renders/{filename}",
            )
        )

    return MultiRenderResponse(loop_id=loop_id, variations=results)

