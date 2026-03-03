from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class LoopBase(BaseModel):
    """Base model for Loop with common fields."""
    name: str
    tempo: Optional[float] = None
    bpm: Optional[int] = None
    key: Optional[str] = None
    bars: Optional[int] = None
    genre: Optional[str] = None
    musical_key: Optional[str] = None
    duration_seconds: Optional[float] = None


class LoopCreate(LoopBase):
    """Schema for creating a new Loop."""
    pass


class LoopUpdate(BaseModel):
    """Schema for updating an existing Loop."""
    filename: Optional[str] = None
    file_url: Optional[str] = None
    file_key: Optional[str] = None
    title: Optional[str] = None
    name: Optional[str] = None
    tempo: Optional[float] = None
    bpm: Optional[int] = None
    key: Optional[str] = None
    bars: Optional[int] = None
    genre: Optional[str] = None
    musical_key: Optional[str] = None
    duration_seconds: Optional[float] = None


class LoopResponse(LoopBase):
    """Schema for Loop response with id and timestamps."""
    id: int
    filename: Optional[str] = None
    file_url: Optional[str] = None
    file_key: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    processed_file_url: Optional[str] = None
    analysis_json: Optional[str] = None
    created_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    """Schema for health check response."""
    status: str
    message: Optional[str] = None


class StatusResponse(BaseModel):
    """Schema for API status response."""
    status: str
    version: Optional[str] = None
    environment: Optional[str] = None



