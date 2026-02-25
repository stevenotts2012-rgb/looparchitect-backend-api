"""Pydantic schemas for arrangement generation API."""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator


class ArrangementSection(BaseModel):
    """A single section of an arrangement."""

    name: str = Field(..., description="Section name (e.g., 'Intro', 'Verse', 'Chorus')")
    bars: int = Field(..., description="Number of 4/4 bars in this section")
    start_bar: int = Field(..., description="Starting bar number (0-indexed)")
    end_bar: int = Field(..., description="Ending bar number (inclusive)")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Verse",
                "bars": 8,
                "start_bar": 16,
                "end_bar": 23,
            }
        }


class ArrangeGenerateRequest(BaseModel):
    """Request to generate an arrangement for a loop.

    Supports flexible duration specification:
    - duration_seconds: Generate arrangement for exact duration (preferred)
    - bars: Directly specify bar count
    - sections: Advanced - specific section structure (future use)

    Priority: bars > duration_seconds > default (180 seconds)
    """

    duration_seconds: Optional[int] = Field(
        default=180,
        ge=15,
        le=3600,
        description="Target duration in seconds (15s to 60 minutes). Default: 180s",
    )
    bars: Optional[int] = Field(
        default=None,
        ge=4,
        le=4096,
        description="Directly specify total bars. Takes priority over duration_seconds",
    )
    sections: Optional[List[dict]] = Field(
        default=None,
        description="Advanced: Specific section structure (reserved for future use)",
    )
    
    @field_validator("duration_seconds", mode="before")
    @classmethod
    def validate_duration(cls, v):
        """Ensure duration is within valid range."""
        if v is None:
            return 180
        if not isinstance(v, int):
            raise ValueError("duration_seconds must be an integer")
        if v < 15:
            raise ValueError("duration_seconds must be at least 15 seconds")
        if v > 3600:
            raise ValueError("duration_seconds cannot exceed 3600 seconds (60 minutes)")
        return v

    @field_validator("bars", mode="before")
    @classmethod
    def validate_bars(cls, v):
        """Ensure bars are within valid range."""
        if v is None:
            return None
        if not isinstance(v, int):
            raise ValueError("bars must be an integer")
        if v < 4:
            raise ValueError("bars must be at least 4")
        if v > 4096:
            raise ValueError("bars cannot exceed 4096")
        return v

    class Config:
        json_schema_extra = {
            "example_1": {
                "duration_seconds": 180,
                "description": "Generate 3-minute arrangement",
            },
            "example_2": {
                "bars": 64,
                "description": "Generate arrangement with exactly 64 bars",
            },
            "example_3": {
                "duration_seconds": 120,
                "description": "Generate 2-minute arrangement (overridden by bars if provided)",
            },
        }


class ArrangeGenerateResponse(BaseModel):
    """Response containing generated arrangement details."""

    loop_id: int = Field(..., description="ID of the source loop")
    bpm: float = Field(..., description="BPM used for arrangement generation")
    key: Optional[str] = Field(
        default=None, description="Musical key of the loop (if detected)"
    )
    target_duration_seconds: int = Field(
        ..., description="Requested duration in seconds"
    )
    actual_duration_seconds: int = Field(
        ..., description="Actual duration generated (may differ slightly due to bar rounding)"
    )
    total_bars: int = Field(..., description="Total number of 4/4 bars in arrangement")
    sections: List[ArrangementSection] = Field(
        ..., description="List of arrangement sections with bar positions"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "loop_id": 1,
                "bpm": 140.0,
                "key": "D Minor",
                "target_duration_seconds": 180,
                "actual_duration_seconds": 180,
                "total_bars": 84,
                "sections": [
                    {
                        "name": "Intro",
                        "bars": 4,
                        "start_bar": 0,
                        "end_bar": 3,
                    },
                    {
                        "name": "Verse",
                        "bars": 8,
                        "start_bar": 4,
                        "end_bar": 11,
                    },
                    {
                        "name": "Chorus",
                        "bars": 8,
                        "start_bar": 12,
                        "end_bar": 19,
                    },
                ],
            }
        }


class ArrangementInfo(BaseModel):
    """Simplified arrangement info for embedded responses."""

    total_bars: int
    sections: List[dict]
    
    class Config:
        from_attributes = True


# ============================================================================
# Audio Arrangement Generation Schemas (Phase B)
# ============================================================================

class AudioArrangementGenerateRequest(BaseModel):
    """Request to generate an audio arrangement from a loop."""

    loop_id: int = Field(..., ge=1, description="ID of the source loop")
    target_seconds: int = Field(
        ...,
        ge=10,
        le=3600,
        description="Target duration in seconds (10s to 60 minutes)",
    )
    genre: Optional[str] = Field(
        default=None,
        description="Genre hint for arrangement (optional)",
    )
    intensity: Optional[str] = Field(
        default=None,
        description="Intensity level: low, medium, high (optional)",
    )
    include_stems: bool = Field(
        default=False,
        description="Whether to generate separate audio stems (future feature)",
    )


class AudioArrangementGenerateResponse(BaseModel):
    """Response from audio arrangement generation request."""

    arrangement_id: int = Field(..., description="ID of created arrangement")
    loop_id: int = Field(..., description="ID of source loop")
    status: str = Field(..., description="Current status: queued, processing, complete, failed")
    created_at: datetime = Field(..., description="Timestamp of creation")

    class Config:
        from_attributes = True


class AudioArrangementResponse(BaseModel):
    """Full arrangement status and details."""

    id: int = Field(..., description="Arrangement ID")
    loop_id: int = Field(..., description="Source loop ID")
    status: str = Field(..., description="Status: queued, processing, complete, failed")
    target_seconds: int = Field(..., description="Requested duration")
    genre: Optional[str] = Field(default=None, description="Genre hint")
    intensity: Optional[str] = Field(default=None, description="Intensity level")
    include_stems: bool = Field(default=False, description="Stems included")
    output_file_url: Optional[str] = Field(
        default=None, description="URL to download generated audio"
    )
    stems_zip_url: Optional[str] = Field(
        default=None, description="URL to download stems ZIP (if generated)"
    )
    arrangement_json: Optional[str] = Field(
        default=None, description="JSON timeline with sections"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if status=failed"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        from_attributes = True
