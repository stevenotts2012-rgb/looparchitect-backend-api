from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    message: str


class StatusResponse(BaseModel):
    status: str
    version: str
    environment: str


class ErrorResponse(BaseModel):
    error: str
    detail: str


class LoopCreate(BaseModel):
    name: str
    tempo: float | None = None
    key: str | None = None
    genre: str | None = None
    file_url: str | None = None


class LoopUpdate(BaseModel):
    name: str | None = None
    tempo: float | None = None
    key: str | None = None
    genre: str | None = None
    file_url: str | None = None


class LoopResponse(BaseModel):
    id: int
    name: str
    tempo: float | None
    key: str | None
    genre: str | None
    file_url: str | None
    created_at: datetime

    class Config:
        from_attributes = True
