"""Pydantic schemas for Track Technical Quality Analysis API.

These models define the request/response contracts for the track quality
analysis endpoint, which measures technical audio characteristics and
provides actionable mixing/mastering suggestions.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TonalBandStatus(str, Enum):
    """Frequency band energy status relative to reference levels."""

    TOO_HIGH = "Too High"
    TOO_LOW = "Too Low"
    OPTIMAL = "Optimal"


class StereoFieldWidth(str, Enum):
    """Stereo field width classification based on mid/side energy ratio."""

    NARROW = "Narrow"
    NORMAL = "Normal"
    WIDE = "Wide"


class ClippingLevel(str, Enum):
    """Clipping severity detected in the audio signal."""

    NONE = "None"
    MINOR = "Minor"
    SEVERE = "Severe"


class TonalProfile(BaseModel):
    """Frequency band energy balance across four broad spectral regions."""

    low: TonalBandStatus = Field(
        ...,
        description="Low-frequency band energy status (20–250 Hz): sub-bass and bass.",
    )
    low_mid: TonalBandStatus = Field(
        ...,
        description="Low-mid band energy status (250–2000 Hz): body, warmth, mud.",
    )
    mid: TonalBandStatus = Field(
        ...,
        description="Mid-frequency band energy status (2000–8000 Hz): presence, clarity.",
    )
    high: TonalBandStatus = Field(
        ...,
        description="High-frequency band energy status (8000–20000 Hz): air, brilliance.",
    )


class TrackQualitySuggestion(BaseModel):
    """A single actionable improvement suggestion."""

    category: str = Field(
        ...,
        description=(
            "Suggestion category: 'compression', 'loudness', 'mono_compatibility', "
            "'stereo_field', or 'tonal_balance'."
        ),
    )
    message: str = Field(
        ...,
        description="Human-readable improvement tip tailored to the detected issue.",
    )


class TrackQualityAnalysisResponse(BaseModel):
    """Response containing technical quality metrics and improvement suggestions.

    All measurements are derived from the uploaded audio file using DSP
    heuristics.  Integrated loudness is a simplified BS.1770-3 approximation
    (no K-weighting filter applied); values will be close to true LUFS but
    not identical to a certified loudness meter.
    """

    sample_rate: int = Field(
        ...,
        description="Sample rate of the audio file in Hz (e.g. 44100).",
    )
    bit_depth: int = Field(
        ...,
        description="Bit depth of the audio file (e.g. 16, 24, 32).",
    )
    clipping: ClippingLevel = Field(
        ...,
        description="Clipping level: 'None', 'Minor' (< 0.1 % of samples), 'Severe' (≥ 0.1 %).",
    )
    mono_compatibility: bool = Field(
        ...,
        description=(
            "True if the stereo mix sums to mono without significant phase cancellation. "
            "False indicates audible energy loss when collapsed to mono."
        ),
    )
    integrated_loudness: float = Field(
        ...,
        description=(
            "Integrated loudness in LUFS (approximate BS.1770-3). "
            "Typical streaming targets: −14 LUFS. Broadcast: −23 LUFS."
        ),
    )
    true_peak: float = Field(
        ...,
        description="Maximum sample amplitude in dBFS (e.g. −4.5).",
    )
    phase_issues: bool = Field(
        ...,
        description=(
            "True if significant phase cancellation is detected between L and R channels. "
            "False means the stereo image is phase-coherent."
        ),
    )
    stereo_field: StereoFieldWidth = Field(
        ...,
        description="Stereo field width classification based on mid/side energy ratio.",
    )
    tonal_profile: TonalProfile = Field(
        ...,
        description="Frequency band balance across four spectral regions.",
    )
    suggestions: List[TrackQualitySuggestion] = Field(
        default_factory=list,
        description="Ordered list of actionable improvement suggestions.",
    )
    analysis_version: str = Field(
        default="1.0.0",
        description="Version of the analysis algorithm used.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "sample_rate": 44100,
                "bit_depth": 24,
                "clipping": "None",
                "mono_compatibility": False,
                "integrated_loudness": -25.1,
                "true_peak": -4.5,
                "phase_issues": False,
                "stereo_field": "Narrow",
                "tonal_profile": {
                    "low": "Too High",
                    "low_mid": "Too Low",
                    "mid": "Optimal",
                    "high": "Optimal",
                },
                "suggestions": [
                    {
                        "category": "compression",
                        "message": (
                            "Unless this is a deliberate artistic decision, you could consider "
                            "applying more compression to make adjustments."
                        ),
                    }
                ],
                "analysis_version": "1.0.0",
            }
        }
