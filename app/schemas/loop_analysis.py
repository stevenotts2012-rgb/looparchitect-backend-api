"""Pydantic schemas for loop analysis API.

These models define the request/response contracts for automatic loop metadata analysis.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


class LoopAnalysisRequest(BaseModel):
    """Request for loop metadata analysis.
    
    This analyzer works with metadata only - no audio file processing required.
    Useful for quick genre/mood detection without expensive audio analysis.
    """
    
    bpm: Optional[float] = Field(
        default=None,
        ge=60.0,
        le=200.0,
        description="Beats per minute (60-200). Key indicator for genre detection."
    )
    
    tags: Optional[List[str]] = Field(
        default=None,
        description="User-provided tags like ['dark', 'aggressive', 'trap', '808']"
    )
    
    filename: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Original filename - often contains genre/mood hints"
    )
    
    mood_keywords: Optional[List[str]] = Field(
        default=None,
        description="Mood descriptors like ['dark', 'emotional', 'energetic']"
    )
    
    genre_hint: Optional[str] = Field(
        default=None,
        description="User's genre hint or preference"
    )
    
    bars: Optional[int] = Field(
        default=None,
        ge=1,
        le=256,
        description="Number of bars in the loop"
    )
    
    musical_key: Optional[str] = Field(
        default=None,
        description="Musical key (e.g., 'C Minor', 'D Major')"
    )
    
    @field_validator('tags', 'mood_keywords', mode='before')
    @classmethod
    def normalize_to_lowercase(cls, v):
        """Normalize tags and keywords to lowercase for consistent matching."""
        if v is None:
            return None
        return [tag.lower().strip() for tag in v if tag]
    
    class Config:
        json_schema_extra = {
            "example": {
                "bpm": 140.0,
                "tags": ["dark", "trap", "808", "aggressive"],
                "filename": "dark_trap_140bpm.wav",
                "mood_keywords": ["dark", "aggressive"],
                "genre_hint": None,
                "bars": 4,
                "musical_key": "C Minor"
            }
        }


class LoopAnalysisResponse(BaseModel):
    """Response containing loop analysis results.
    
    Provides genre, mood, energy level, and arrangement recommendations
    based on rule-based metadata analysis.
    """
    
    detected_genre: str = Field(
        ...,
        description="Detected genre (trap, dark_trap, melodic_trap, drill, rage, etc.)"
    )
    
    detected_mood: str = Field(
        ...,
        description="Detected mood (dark, aggressive, emotional, cinematic, energetic)"
    )
    
    energy_level: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Energy level from 0.0 (calm) to 1.0 (intense)"
    )
    
    recommended_template: str = Field(
        ...,
        description="Recommended arrangement template (standard, progressive, looped, minimal)"
    )
    
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall confidence score for the analysis (0.0-1.0)"
    )
    
    suggested_instruments: List[str] = Field(
        ...,
        description="Recommended instruments based on detected genre and mood"
    )
    
    analysis_version: str = Field(
        default="1.0.0",
        description="Version of the analysis algorithm used"
    )
    
    source_signals: Dict[str, Any] = Field(
        ...,
        description="Signals used to make the detection (for debugging and transparency)"
    )
    
    reasoning: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of the analysis logic"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "detected_genre": "dark_trap",
                "detected_mood": "dark",
                "energy_level": 0.75,
                "recommended_template": "standard",
                "confidence": 0.85,
                "suggested_instruments": ["kick", "snare", "hats", "808_bass", "dark_pad", "fx"],
                "analysis_version": "1.0.0",
                "source_signals": {
                    "bpm_match": True,
                    "tag_matches": ["dark", "trap"],
                    "mood_matches": ["dark"],
                    "filename_hints": ["dark", "trap"]
                },
                "reasoning": "Detected dark_trap based on: BPM 140 in trap range (130-160), "
                            "dark mood keywords, trap-related tags."
            }
        }


class LoopMetadataInput(BaseModel):
    """Simplified input for embedding in other requests.
    
    Used when loop analysis is part of a larger operation (e.g., arrangement generation).
    """
    
    bpm: Optional[float] = None
    tags: Optional[List[str]] = None
    filename: Optional[str] = None
    genre: Optional[str] = None
    mood: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "bpm": 145.0,
                "tags": ["drill", "uk", "sliding_808"],
                "filename": "uk_drill_145.wav",
                "genre": None,
                "mood": None
            }
        }
