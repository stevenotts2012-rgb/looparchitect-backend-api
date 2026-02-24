"""Pydantic schemas for the Loop Library CRUD API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class LoopCreate(BaseModel):
    """Schema for creating a new loop record."""

    name: str
    filename: Optional[str] = None
    file_url: Optional[str] = None
    title: Optional[str] = None
    tempo: Optional[float] = None
    bpm: Optional[int] = None
    key: Optional[str] = None
    musical_key: Optional[str] = None
    genre: Optional[str] = None
    duration_seconds: Optional[float] = None


class LoopUpdate(BaseModel):
    """Schema for partially updating an existing loop record (all fields optional)."""

    name: Optional[str] = None
    filename: Optional[str] = None
    file_url: Optional[str] = None
    title: Optional[str] = None
    tempo: Optional[float] = None
    bpm: Optional[int] = None
    key: Optional[str] = None
    musical_key: Optional[str] = None
    genre: Optional[str] = None
    duration_seconds: Optional[float] = None


class LoopResponse(BaseModel):
    """Schema for serializing a loop record in API responses."""

    id: int
    name: str
    filename: Optional[str]
    file_url: Optional[str]
    title: Optional[str]
    tempo: Optional[float]
    bpm: Optional[int]
    key: Optional[str]
    musical_key: Optional[str]
    genre: Optional[str]
    duration_seconds: Optional[float]
    created_at: datetime

    class Config:
        from_attributes = True
