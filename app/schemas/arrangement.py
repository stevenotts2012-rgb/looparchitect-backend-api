"""Pydantic schemas for arrangement generation API."""

from datetime import datetime
from typing import Optional, List, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ============================================================================
# Producer Engine V2 schemas (Phase 1 + Phase 5)
# ============================================================================


class ProducerSectionSummaryItem(BaseModel):
    """Lightweight per-section summary for API responses."""

    index: int = Field(..., description="0-based section index")
    section_type: str = Field(..., description="Section type: intro, verse, hook, etc.")
    label: str = Field(..., description="Human-readable label, e.g. 'Hook 1'")
    start_bar: int
    length_bars: int
    target_energy: int = Field(..., description="Energy level 1–5")
    density: str = Field(..., description="sparse | medium | full")
    active_roles: List[str] = Field(default_factory=list)
    muted_roles: List[str] = Field(default_factory=list)
    variation_strategy: str = ""
    transition_in: str = ""
    transition_out: str = ""
    notes: str = ""
    rationale: str = ""


class ProducerDecisionLogEntry(BaseModel):
    """Single entry in the producer decision log."""

    section_index: int
    section_label: str
    decision: str
    reason: str
    flag: str = ""


class ProducerPlanV2(BaseModel):
    """
    Full V2 producer plan exposed in API responses.

    Present only when PRODUCER_ENGINE_V2=true.  Old fields remain unchanged.
    """

    builder_version: str = "2.0"
    genre: str = ""
    style_tags: List[str] = Field(default_factory=list)
    tempo: float = 120.0
    total_bars: int = 0
    source_type: str = "loop"
    available_roles: List[str] = Field(default_factory=list)
    rules_applied: List[str] = Field(default_factory=list)
    sections: List[ProducerSectionSummaryItem] = Field(default_factory=list)
    decision_log: List[ProducerDecisionLogEntry] = Field(default_factory=list)


class QualityScoreSchema(BaseModel):
    """Heuristic quality score for an arrangement plan."""

    structure_score: float = Field(default=100.0, description="0–100")
    transition_score: float = Field(default=100.0, description="0–100")
    audio_quality_score: float = Field(default=100.0, description="0–100")
    overall_score: float = Field(default=100.0, description="Weighted composite 0–100")
    flags: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)



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
    bars_total: Optional[int] = Field(
        default=None,
        description="Backward-compatible alias for total_bars",
    )
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
    
    arrangement_json: Optional[str] = None
    layering_plan: Optional[list] = None

    class Config:
        from_attributes = True


# ============================================================================
# Audio Arrangement Generation Schemas (Phase B)
# ============================================================================

class AudioArrangementGenerateRequest(BaseModel):
    """Request to generate an audio arrangement from a loop."""

    loop_id: int = Field(..., ge=1, description="ID of the source loop")
    target_seconds: Optional[int] = Field(
        default=None,
        ge=10,
        le=3600,
        description="Target duration in seconds (10s to 60 minutes). Optional when bars is provided.",
    )
    bars: Optional[int] = Field(
        default=None,
        ge=4,
        le=4096,
        description="Optional bar count. When provided, server derives target_seconds from loop BPM",
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
    style_preset: Optional[str] = Field(
        default=None,
        description="Optional style preset id (atl, dark, melodic, drill, cinematic, club, experimental)",
    )
    style_params: Optional[dict] = Field(
        default=None,
        description="Optional style parameter overrides",
    )
    style_text_input: Optional[str] = Field(
        default=None,
        max_length=500,
        description="V2: Natural language style description (e.g., 'Southside type, aggressive, beat switch at bar 32')",
    )
    use_ai_parsing: bool = Field(
        default=False,
        description="V2: Use LLM to parse style_text_input instead of style_preset",
    )
    producer_moves: Optional[List[str]] = Field(
        default=None,
        description="Optional producer move directives (e.g., beat_switch, halftime_drop, stop_time)",
    )
    arrangement_plan: Optional[dict] = Field(
        default=None,
        description="Optional validated arrangement plan to drive deterministic producer arrangement generation.",
    )
    seed: Optional[int | str] = Field(
        default=None,
        description="Optional deterministic seed",
    )
    variation_count: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Optional number of variations to queue (feature-flagged)",
    )
    auto_save: bool = Field(
        default=False,
        description="Whether generated arrangements should be persisted to user history immediately",
    )

    # ---- Arrangement Preset ----
    arrangement_preset: Optional[str] = Field(
        default="trap",
        description=(
            "Genre preset that shapes section density, role priorities, and transitions. "
            "Supported values: trap (default), drill, cinematic, lofi, house, afrobeats."
        ),
    )

    @field_validator("arrangement_preset", mode="before")
    @classmethod
    def normalise_arrangement_preset(cls, v: object) -> str:
        """Normalise to a known preset key, falling back to 'trap' for unknowns."""
        from app.services.arrangement_presets import resolve_preset_name
        return resolve_preset_name(str(v) if v is not None else None)

    reference_analysis_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional: ID returned by POST /api/v1/reference/analyze. "
            "When provided (and REFERENCE_GUIDED_ARRANGEMENT=true), the analyzed "
            "reference structure is used as a structural blueprint for section ordering, "
            "energy curve, and density progression. "
            "Musical content is NOT copied from the reference."
        ),
    )
    reference_guidance_mode: Optional[str] = Field(
        default=None,
        description=(
            "Override the guidance mode from the reference analysis: "
            "structure_only | energy_only | structure_and_energy"
        ),
    )
    reference_adaptation_strength: Optional[str] = Field(
        default=None,
        description=(
            "Override the adaptation strength from the reference analysis: "
            "loose | medium | close"
        ),
    )
    
    @model_validator(mode='after')
    def validate_duration_params(self):
        """Ensure at least one of target_seconds or bars is provided."""
        if self.target_seconds is None and self.bars is None:
            raise ValueError("Either target_seconds or bars must be provided")
        return self


class StructurePreviewItem(BaseModel):
    name: str
    bars: int
    energy: float


class ArrangementPreviewCandidate(BaseModel):
    arrangement_id: int
    status: str
    created_at: datetime
    render_job_id: Optional[str] = None
    seed_used: Optional[int] = None


class AudioArrangementGenerateResponse(BaseModel):
    """Response from audio arrangement generation request."""

    arrangement_id: Optional[int] = Field(default=None, description="ID of first created arrangement")
    loop_id: int = Field(..., description="ID of source loop")
    status: Optional[str] = Field(default=None, description="Current status: queued, processing, done, failed")
    created_at: Optional[datetime] = Field(default=None, description="Timestamp of first creation")
    job_id: Optional[str] = Field(
        default=None,
        description="Primary render job ID to poll for status. None when no job was created.",
    )
    poll_url: Optional[str] = Field(
        default=None,
        description=(
            "URL to poll for job status: /api/v1/jobs/{job_id}. "
            "Present when job_id is present; both are None when no job was created."
        ),
    )
    render_job_ids: List[str] = Field(default_factory=list, description="All render job IDs (one per variation)")
    seed_used: Optional[int] = Field(default=None, description="Resolved seed used for deterministic generation")
    style_preset: Optional[str] = Field(default=None, description="Resolved style preset id")
    arrangement_preset: Optional[str] = Field(
        default=None,
        description="Resolved arrangement preset applied (trap, drill, cinematic, lofi, house, afrobeats).",
    )
    style_profile: Optional[dict] = Field(
        default=None,
        description="V2: Parsed style profile from LLM (includes intent, attributes, sections)",
    )
    structure_preview: List[StructurePreviewItem] = Field(
        default_factory=list,
        description="Section plan preview generated at request time",
    )
    candidates: List[ArrangementPreviewCandidate] = Field(
        default_factory=list,
        description="Generated preview candidates. Save one explicitly to add to history.",
    )

    # ---- Duration fields for the preview player ----
    target_seconds: Optional[int] = Field(
        default=None,
        description="Requested arrangement duration in seconds (mirrors the request value). "
                    "Use this to seed the audio player duration display before the render completes.",
    )
    bpm: Optional[float] = Field(
        default=None,
        description="Tempo of the source loop in BPM. Together with structure_preview bars this "
                    "allows the frontend to derive per-section timestamps.",
    )

    # ---- Phase 5: Producer intelligence fields (backward-compatible, all optional) ----
    producer_plan: Optional[ProducerPlanV2] = Field(
        default=None,
        description="V2 producer plan (present when PRODUCER_ENGINE_V2=true)",
    )
    producer_notes: List[str] = Field(
        default_factory=list,
        description="Human-readable producer decision notes from the V2 plan",
    )
    quality_score: Optional[QualityScoreSchema] = Field(
        default=None,
        description="Heuristic quality score for the generated arrangement plan",
    )
    section_summary: List[ProducerSectionSummaryItem] = Field(
        default_factory=list,
        description="Section-by-section summary from the V2 producer plan",
    )
    decision_log: List[ProducerDecisionLogEntry] = Field(
        default_factory=list,
        description="Producer decision log explaining why each section was planned as-is",
    )

    # ---- Reference-Guided Arrangement Mode fields (backward-compatible, all optional) ----
    reference_guided: bool = Field(
        default=False,
        description="True when a reference analysis was applied to guide this arrangement",
    )
    reference_summary: Optional[str] = Field(
        default=None,
        description="Human-readable summary of the detected reference structure",
    )
    reference_structure_summary: Optional[dict] = Field(
        default=None,
        description=(
            "Condensed reference structure: section count, tempo estimate, energy arc. "
            "Reference audio is used for structural guidance only — "
            "musical content is not copied."
        ),
    )
    adaptation_mode: Optional[str] = Field(
        default=None,
        description="Reference guidance mode used: structure_only | energy_only | structure_and_energy",
    )
    adaptation_strength: Optional[str] = Field(
        default=None,
        description="Adaptation strength applied: loose | medium | close",
    )
    reference_analysis_confidence: Optional[float] = Field(
        default=None,
        description="Confidence score of the reference analysis (0–1)",
    )

    class Config:
        from_attributes = True


# ============================================================================
# Phase B: Async Arrangement Pipeline Schemas
# ============================================================================

class ArrangementCreateRequest(BaseModel):
    """Request to create an arrangement generation job."""

    loop_id: int = Field(..., ge=1, description="ID of the source loop")
    target_duration_seconds: int = Field(
        default=180,
        ge=30,
        le=3600,
        description="Target duration in seconds (default 180)",
    )


class ArrangementResponse(BaseModel):
    """Response schema for arrangement records."""

    id: int
    loop_id: int
    status: str
    progress: Optional[float] = Field(default=0.0, ge=0.0, le=100.0, description="Progress percentage (0-100)")
    progress_message: Optional[str] = Field(default=None, description="Human-readable progress message")
    error_message: Optional[str] = None
    output_s3_key: Optional[str] = None
    output_url: Optional[str] = None
    # output_file_url is an alias for output_url populated at response time with a fresh presigned URL
    output_file_url: Optional[str] = Field(
        default=None,
        description="URL to stream/download the generated audio (alias of output_url, always fresh)",
    )
    stems_zip_url: Optional[str] = None
    mastering_metadata: Optional[dict] = None
    arrangement_json: Optional[str] = Field(default=None, description="JSON timeline with sections")
    # Duration fields — populated from the arrangement DB row so the preview player
    # can show the expected length before/after render without an extra API call.
    duration_seconds: Optional[int] = Field(
        default=None,
        description="Target duration in seconds (mirrors target_seconds from the generate request).",
    )
    created_at: datetime
    updated_at: datetime

    # ---- Phase 5: Producer intelligence fields (backward-compatible, all optional) ----
    producer_plan: Optional[ProducerPlanV2] = Field(
        default=None,
        description="V2 producer plan (present when PRODUCER_ENGINE_V2=true)",
    )
    quality_score: Optional[QualityScoreSchema] = Field(
        default=None,
        description="Heuristic quality score for the generated arrangement plan",
    )
    section_summary: List[ProducerSectionSummaryItem] = Field(
        default_factory=list,
        description="Section-by-section summary from the V2 producer plan",
    )
    decision_log: List[ProducerDecisionLogEntry] = Field(
        default_factory=list,
        description="Producer decision log explaining why each section was planned as-is",
    )

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
    mastering_metadata: Optional[dict] = Field(
        default=None, description="Final mastering metadata/profile applied to render"
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


class ArrangementPlannerInput(BaseModel):
    """Input payload consumed by the AI arrangement planner."""

    bpm: Optional[float] = Field(default=None, gt=0)
    key: Optional[str] = None
    time_signature: Optional[str] = None
    bars_available: Optional[int] = Field(default=None, ge=1)
    genre_hint: Optional[str] = None
    mood_hint: Optional[str] = None
    detected_roles: List[str] = Field(default_factory=list)
    preferred_structure: Optional[List[str]] = None
    target_total_bars: Optional[int] = Field(default=None, ge=4, le=512)
    source_type: Literal["loop", "stem_pack", "unknown"] = "unknown"
    arrangement_preset: Optional[str] = Field(
        default=None,
        description="Genre preset to apply (trap, drill, cinematic, lofi, house, afrobeats).",
    )


class ArrangementPlannerConfig(BaseModel):
    """Runtime planner behavior flags."""

    strict: bool = True
    max_sections: int = Field(default=10, ge=1, le=16)
    allow_full_mix: bool = True


class ArrangementPlanSection(BaseModel):
    """Single section in an arrangement plan."""

    index: int = Field(..., ge=0)
    type: Literal["intro", "verse", "pre_hook", "hook", "bridge", "breakdown", "outro"]
    bars: int = Field(..., ge=1)
    energy: int = Field(..., ge=1, le=5)
    density: Literal["sparse", "medium", "full"]
    active_roles: List[str] = Field(default_factory=list)
    transition_into: Literal[
        "none",
        "drum_fill",
        "fx_rise",
        "fx_hit",
        "mute_drop",
        "bass_drop",
        "vocal_chop",
        "arp_lift",
        "percussion_fill",
    ]
    notes: str = Field(default="", max_length=240)


class ArrangementPlannerNotes(BaseModel):
    """Top-level planner metadata notes."""

    strategy: str = Field(default="", max_length=240)
    fallback_used: bool = False


class ArrangementPlan(BaseModel):
    """Engine-friendly arrangement plan generated by AI or fallback logic."""

    structure: List[Literal["intro", "verse", "pre_hook", "hook", "bridge", "breakdown", "outro"]] = Field(default_factory=list)
    total_bars: int = Field(default=0, ge=0)
    sections: List[ArrangementPlanSection] = Field(default_factory=list)
    planner_notes: ArrangementPlannerNotes = Field(default_factory=ArrangementPlannerNotes)


class ArrangementPlanValidation(BaseModel):
    """Validation result for generated planner payload."""

    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ArrangementPlannerMeta(BaseModel):
    """Operational metadata for planner call execution."""

    model: Optional[str] = None
    latency_ms: int = 0
    tokens: Optional[int] = None
    fallback_used: bool = False


class ArrangementPlanRequest(BaseModel):
    """Request body for planner endpoint."""

    input: ArrangementPlannerInput
    user_request: Optional[str] = Field(default=None, max_length=1000)
    planner_config: ArrangementPlannerConfig = Field(default_factory=ArrangementPlannerConfig)


class ArrangementPlanResponse(BaseModel):
    """Response payload for planner endpoint."""

    plan: ArrangementPlan
    validation: ArrangementPlanValidation
    planner_meta: ArrangementPlannerMeta
