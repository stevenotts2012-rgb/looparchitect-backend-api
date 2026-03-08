from datetime import datetime
import json

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.models.base import Base


class Loop(Base):
    """SQLAlchemy model representing a music loop in the library."""

    __tablename__ = "loops"

    id = Column(Integer, primary_key=True, index=True)
    # Legacy fields kept for backward compatibility
    name = Column(String, nullable=False)
    tempo = Column(Float, nullable=True)
    key = Column(String, nullable=True)
    # New fields added as part of Loop Library CRUD
    filename = Column(String, nullable=True)
    file_url = Column(String, nullable=True)
    file_key = Column(String, nullable=True)  # S3 key (e.g., "uploads/uuid.wav")
    title = Column(String, nullable=True)
    bpm = Column(Integer, nullable=True)
    bars = Column(Integer, nullable=True)  # Number of bars in the loop
    musical_key = Column(String, nullable=True)
    genre = Column(String, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Background task processing fields
    status = Column(String, default="pending", nullable=True)  # pending | processing | complete | failed
    processed_file_url = Column(String, nullable=True)  # URL to generated/processed audio
    analysis_json = Column(Text, nullable=True)  # JSON string with analysis results

    @property
    def stem_metadata(self):
        if not self.analysis_json:
            return None
        try:
            payload = json.loads(self.analysis_json)
            if isinstance(payload, dict):
                return payload.get("stem_separation")
        except Exception:
            return None
        return None
