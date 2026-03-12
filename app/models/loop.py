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
    
    # STEM-DRIVEN ENGINE fields (NEW)
    is_stem_pack = Column(String, default="false", nullable=True)  # "true" if this is multi-stem, "false" if single loop
    stem_roles_json = Column(Text, nullable=True)  # JSON: {role: file_key, ...}
    stem_files_json = Column(Text, nullable=True)  # JSON: {role: {filename, url, duration}, ...}
    stem_validation_json = Column(Text, nullable=True)  # Validation status: {status, errors, ...}

    @property
    def stem_metadata(self):
        """Get stem separation metadata from analysis."""
        if not self.analysis_json:
            return None
        try:
            payload = json.loads(self.analysis_json)
            if isinstance(payload, dict):
                return payload.get("stem_separation")
        except Exception:
            return None
        return None
    
    @property
    def stems_dict(self) -> dict:
        """Get parsed stem files as dict."""
        if not self.stem_files_json:
            return {}
        try:
            return json.loads(self.stem_files_json)
        except Exception:
            return {}
    
    @property
    def stem_roles(self) -> dict:
        """Get stem role mapping."""
        if not self.stem_roles_json:
            return {}
        try:
            return json.loads(self.stem_roles_json)
        except Exception:
            return {}
