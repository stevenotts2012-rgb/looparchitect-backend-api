"""SQLAlchemy model for async render jobs."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Float, Index

from app.models.base import Base


class RenderJob(Base):
    """Track render jobs: status, progress, outputs, errors, retries."""

    __tablename__ = "render_jobs"

    id = Column(String(36), primary_key=True, index=True)  # UUID
    loop_id = Column(Integer, ForeignKey("loops.id"), nullable=False, index=True)
    job_type = Column(String(64), default="render_arrangement", nullable=False)
    
    # Job parameters as JSON
    params_json = Column(Text, nullable=True)  # RenderConfig serialized
    
    # Status lifecycle: queued -> processing -> succeeded/failed
    status = Column(String(32), default="queued", nullable=False, index=True)  # queued|processing|succeeded|failed
    progress = Column(Float, default=0.0, nullable=True)  # 0-100 percentage
    progress_message = Column(String(256), nullable=True)  # "Processing variation 2 of 3"
    
    # Output artifacts (list of dicts with name, s3_key, content_type)
    output_files_json = Column(Text, nullable=True)  # JSON array [{name, s3_key, signed_url}]
    
    # Error handling
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    
    # Deduplication: hash of (loop_id, params) for idempotency
    dedupe_hash = Column(String(64), nullable=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    queued_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    
    # TTL for completed jobs (optional future cleanup)
    expires_at = Column(DateTime, nullable=True)

    # Phase 3 render observability — JSON blob with execution metadata:
    # render_path_used, worker_mode, job_terminal_state, failure_stage,
    # fallback_triggered_count, fallback_reasons, planned/actual stem maps,
    # section_execution_report, render_signatures, phrase_split_count,
    # source_quality_mode_used, mastering_applied, feature_flags_snapshot.
    render_metadata_json = Column(Text, nullable=True)

    def __init__(self, **kwargs):
        if "retry_count" not in kwargs or kwargs.get("retry_count") is None:
            kwargs["retry_count"] = 0
        if "progress" not in kwargs or kwargs.get("progress") is None:
            kwargs["progress"] = 0.0
        if "status" not in kwargs or kwargs.get("status") is None:
            kwargs["status"] = "queued"
        if "job_type" not in kwargs or kwargs.get("job_type") is None:
            kwargs["job_type"] = "render_arrangement"
        super().__init__(**kwargs)


# Add composite index for deduplication window (loop_id + dedupe_hash, ordered by created_at)
Index("ix_render_jobs_dedupe", RenderJob.loop_id, RenderJob.dedupe_hash, RenderJob.created_at)
