"""Pydantic schemas for render jobs."""

from typing import Any, Dict, List, Optional
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class OutputFile(BaseModel):
    """File output from a render job."""

    name: str = Field(..., description="Friendly name (e.g., 'Commercial Variation')")
    s3_key: str = Field(..., description="S3 object key")
    content_type: str = Field(default="audio/wav")
    signed_url: Optional[str] = Field(None, description="Temporary presigned URL (generated on-demand)")


class RenderJobRequest(BaseModel):
    """Request to enqueue a render job."""

    genre: Optional[str] = "Trap"
    length_seconds: Optional[int] = 180
    intensity: Optional[str] = "medium"
    variations: Optional[List[str]] = ["Commercial", "Creative", "Experimental"]

    # Backward-compatible fields still supported by some routes/workers
    energy: Optional[str] = "high"
    variation_styles: Optional[List[str]] = None
    custom_style: Optional[str] = None


class RenderJobResponse(BaseModel):
    """Response from job creation (immediate return with job_id and status)."""

    job_id: str = Field(..., description="Unique job identifier")
    loop_id: int = Field(..., description="Associated loop")
    status: str = Field(..., description="queued | processing | succeeded | failed")
    created_at: datetime
    poll_url: str = Field(..., description="URL to check job status: /api/v1/jobs/{job_id}")
    deduplicated: bool = Field(False, description="True if request matched existing queued/processing job")


class RenderJobStatusResponse(BaseModel):
    """Full job status for polling endpoint."""

    job_id: str
    loop_id: int
    job_type: str
    status: str  # queued|processing|completed|failed  (succeeded is normalised to completed)
    progress: float = Field(0.0, ge=0.0, le=100.0, description="Progress percentage")
    progress_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # Outputs only when completed
    output_files: Optional[List[OutputFile]] = None

    # Error details when failed
    error_message: Optional[str] = None
    retry_count: int = Field(0, ge=0)

    # Phase 3 render observability — populated after job completes.
    # Contains render_path_used, worker_mode, job_terminal_state, failure_stage,
    # fallback_triggered_count, fallback_reasons, section_execution_report,
    # render_signatures, unique_render_signature_count, phrase_split_count,
    # source_quality_mode_used, mastering_applied, feature_flags_snapshot.
    # Optional and additive — absent for jobs completed before this feature.
    render_metadata: Optional[Dict[str, Any]] = Field(
        None, description="Phase 3 render observability metadata"
    )

    # ID of the Arrangement record created or updated when the render succeeds.
    # Absent for jobs that have not yet completed or that pre-date this feature.
    arrangement_id: Optional[int] = Field(
        None, description="Arrangement DB record linked to this completed job"
    )

    @field_validator("status", mode="before")
    @classmethod
    def normalize_succeeded(cls, v: str) -> str:
        """Normalize the internal 'succeeded' state to 'completed' for the API."""
        if v == "succeeded":
            return "completed"
        return v


class RenderJobHistoryResponse(BaseModel):
    """List of jobs for a loop."""

    loop_id: int
    jobs: List[RenderJobStatusResponse]
