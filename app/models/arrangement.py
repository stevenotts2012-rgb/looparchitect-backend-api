"""SQLAlchemy model for Arrangement (audio generation workflow)."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey, Index, Float
from sqlalchemy.orm import relationship

from app.models.base import Base


class Arrangement(Base):
    """Represents a generated arrangement/render of a loop with specific parameters."""

    __tablename__ = "arrangements"

    id = Column(Integer, primary_key=True, index=True)
    loop_id = Column(Integer, ForeignKey("loops.id"), nullable=False, index=True)
    status = Column(String, default="queued", nullable=False)  # queued, processing, done, failed
    progress = Column(Float, default=0.0, nullable=True)  # 0-100 percentage
    progress_message = Column(String(256), nullable=True)  # Human-readable message
    target_seconds = Column(Integer, nullable=False)  # User-requested duration
    genre = Column(String, nullable=True)
    intensity = Column(String, nullable=True)
    include_stems = Column(Boolean, default=False)
    
    # Output paths
    output_s3_key = Column(String, nullable=True)  # S3 key like "arrangements/{id}.wav"
    output_url = Column(String, nullable=True)  # Presigned URL to download
    output_file_url = Column(String, nullable=True)  # Legacy local path (deprecated)
    stems_zip_url = Column(String, nullable=True)  # Path to stems ZIP (if generated)
    
    # Metadata
    arrangement_json = Column(Text, nullable=True)  # JSON timeline with sections
    style_profile_json = Column(Text, nullable=True)  # V2: LLM-generated StyleProfile as JSON
    ai_parsing_used = Column(Boolean, nullable=True, default=False)  # V2: Whether LLM parsing was used
    producer_arrangement_json = Column(Text, nullable=True)  # Producer-style arrangement structure
    render_plan_json = Column(Text, nullable=True)  # Detailed render plan with events
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to Loop
    loop = relationship("Loop", backref="arrangements")
    
    # Index for efficient status queries
    __table_args__ = (Index("idx_arrangement_loop_status", "loop_id", "status"),)
