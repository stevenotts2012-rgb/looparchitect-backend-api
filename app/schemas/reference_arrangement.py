"""
Reference-Guided Arrangement Mode — Domain Schemas (Phase 1).

Defines all types for reference audio analysis and structural guidance.

Design guardrails:
- Reference audio is used ONLY for structure and energy guidance.
- Musical content (melody, harmony, drum patterns) is never copied.
- The system produces an original arrangement from the user's source material.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ReferenceGuidanceMode(str, Enum):
    """Controls which aspects of the reference are used as guidance."""

    STRUCTURE_ONLY = "structure_only"
    """Use only section order and lengths; ignore energy/density curves."""

    ENERGY_ONLY = "energy_only"
    """Use only the energy/density progression; ignore section boundaries."""

    STRUCTURE_AND_ENERGY = "structure_and_energy"
    """Use both section structure and energy/density curves (recommended)."""


class ReferenceAdaptationStrength(str, Enum):
    """How closely the user's arrangement should follow the reference structure."""

    LOOSE = "loose"
    """Reference is used as a loose inspiration — general arc only."""

    MEDIUM = "medium"
    """Reference guides section order and energy peaks (recommended default)."""

    CLOSE = "close"
    """Reference guides section order, lengths, energy, and density closely."""


# ---------------------------------------------------------------------------
# Core data models
# ---------------------------------------------------------------------------


class ReferenceSection(BaseModel):
    """A single detected section from the reference audio analysis."""

    index: int = Field(..., ge=0, description="0-based section index")
    start_time_sec: float = Field(..., ge=0.0, description="Section start time in seconds")
    end_time_sec: float = Field(..., gt=0.0, description="Section end time in seconds")
    estimated_bars: int = Field(..., ge=1, description="Estimated bar count for this section")
    section_type_guess: str = Field(
        ...,
        description="Heuristic section type guess: intro, verse, hook, breakdown, outro, unknown",
    )
    energy_level: float = Field(
        ..., ge=0.0, le=1.0, description="Normalized energy level (0=silent, 1=max)"
    )
    density_level: float = Field(
        ..., ge=0.0, le=1.0, description="Normalized density level (0=sparse, 1=dense)"
    )
    transition_in_strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Strength of the transition entering this section (0=smooth, 1=dramatic)",
    )
    transition_out_strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Strength of the transition leaving this section (0=smooth, 1=dramatic)",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence that this section boundary/type is accurate",
    )

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_time_sec - self.start_time_sec)


class ReferenceStructure(BaseModel):
    """Full structural analysis of a reference audio track.

    This object captures high-level arrangement guidance only.
    It does NOT contain any musical content (notes, chords, rhythm patterns).
    """

    total_duration_sec: float = Field(..., ge=0.0, description="Total reference audio duration")
    tempo_estimate: Optional[float] = Field(
        default=None,
        description="BPM estimate (nullable when analysis is unreliable)",
    )
    sections: List[ReferenceSection] = Field(
        default_factory=list,
        description="Detected section boundaries and characteristics",
    )
    energy_curve: List[float] = Field(
        default_factory=list,
        description="Normalized energy values (0–1) sampled at regular time windows",
    )
    summary: str = Field(
        default="",
        description="Human-readable summary of the detected structure",
    )
    analysis_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Overall confidence score for the analysis (0=low, 1=high)",
    )
    analysis_quality: str = Field(
        default="medium",
        description="Quality band: high | medium | low | insufficient",
    )
    analysis_warnings: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings raised during analysis",
    )


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ReferenceAnalysisRequest(BaseModel):
    """Parameters for a reference audio analysis request."""

    guidance_mode: ReferenceGuidanceMode = Field(
        default=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
        description="Which aspects of the reference to use as guidance",
    )
    adaptation_strength: ReferenceAdaptationStrength = Field(
        default=ReferenceAdaptationStrength.MEDIUM,
        description="How closely to follow the reference structure",
    )


class ReferenceAnalysisResponse(BaseModel):
    """Response returned after a reference audio analysis is complete."""

    analysis_id: str = Field(
        ..., description="Unique ID to pass back in arrangement generation requests"
    )
    structure: ReferenceStructure = Field(
        ..., description="Detected structural information from the reference audio"
    )
    guidance_mode: ReferenceGuidanceMode
    adaptation_strength: ReferenceAdaptationStrength
    created_at: datetime
    legal_disclaimer: str = Field(
        default=(
            "Reference audio is used for structural and energy guidance only. "
            "Musical content (melody, harmony, drum patterns) is not copied or reproduced. "
            "Your arrangement will be generated entirely from your own source material."
        ),
        description="Legal/product disclaimer confirming no musical content is cloned",
    )


# ---------------------------------------------------------------------------
# Adapter guidance output (internal, used by reference_plan_adapter)
# ---------------------------------------------------------------------------


class ReferenceSectionGuidance(BaseModel):
    """Per-section guidance extracted from the reference for the producer plan adapter."""

    index: int
    section_type: str
    target_bars: int
    target_energy: int = Field(..., ge=1, le=5, description="Energy level 1–5")
    target_density: str = Field(..., description="sparse | medium | full")
    transition_in_intent: str = Field(default="none")
    transition_out_intent: str = Field(default="none")
    confidence: float = Field(default=0.5)
    adaptation_note: str = Field(default="")


class ReferenceProducerGuidance(BaseModel):
    """Adapter output: structured guidance to inject into the producer plan builder."""

    section_guidance: List[ReferenceSectionGuidance] = Field(default_factory=list)
    suggested_total_bars: Optional[int] = None
    energy_arc_summary: str = ""
    adaptation_mode: str = ""
    adaptation_strength: str = ""
    reference_confidence: float = 0.5
    decision_log: List[str] = Field(default_factory=list)
    legal_note: str = (
        "Arrangement is generated from user's source material. "
        "Reference audio provides structural blueprint only."
    )
