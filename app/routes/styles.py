from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.style_service import style_service
from app.services.style_validation import style_validation_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/styles")
def list_styles() -> dict[str, object]:
    """Phase 0 skeleton endpoint (not yet registered in router map)."""
    return {"styles": style_service.get_styles()}


class SimpleStyleProfile(BaseModel):
    """Simple style profile for UI input and validation."""

    intent: str = Field(
        ..., min_length=1, max_length=500, description="Style description"
    )
    energy: float = Field(default=0.5, ge=0, le=1, description="Energy: 0=quiet, 1=loud")
    darkness: float = Field(
        default=0.5, ge=0, le=1, description="Darkness: 0=bright, 1=dark"
    )
    bounce: float = Field(
        default=0.5, ge=0, le=1, description="Bounce: 0=laid-back, 1=driving"
    )
    warmth: float = Field(
        default=0.5, ge=0, le=1, description="Warmth: 0=cold, 1=warm"
    )
    texture: str = Field(default="balanced", description="Texture: smooth|balanced|gritty")
    references: List[str] = Field(default_factory=list, description="Reference artists")
    avoid: List[str] = Field(default_factory=list, description="Elements to avoid")
    seed: int = Field(default=42, description="Random seed")
    confidence: float = Field(default=0.8, ge=0, le=1, description="Parser confidence")


class StyleValidationRequest(BaseModel):
    """Request to validate a style profile."""

    profile: SimpleStyleProfile = Field(..., description="StyleProfile to validate")


class StyleValidationResponse(BaseModel):
    """Response from style validation endpoint."""

    valid: bool = Field(..., description="Whether the style is valid")
    normalized_profile: SimpleStyleProfile = Field(
        ..., description="Normalized style profile"
    )
    warnings: List[str] = Field(default_factory=list, description="Non-blocking warnings")
    message: str = Field(..., description="Validation result message")


@router.post("/validate")
async def validate_style(request: StyleValidationRequest) -> StyleValidationResponse:
    """Validate and normalize a style profile without rendering audio.
    
    This endpoint checks style parameters for validity without triggering
    audio generation. Useful for real-time validation on the frontend.
    """
    try:
        normalized, warnings = style_validation_service.validate_and_normalize(
            request.profile.model_dump()
        )
        return StyleValidationResponse(
            valid=True,
            normalized_profile=SimpleStyleProfile(**normalized),
            warnings=warnings,
            message="Style profile is valid and normalized"
        )
    except (ValueError, KeyError) as e:
        return StyleValidationResponse(
            valid=False,
            normalized_profile=request.profile,
            warnings=[str(e)],
            message=f"Style validation failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error validating style: {e}")
        return StyleValidationResponse(
            valid=False,
            normalized_profile=request.profile,
            warnings=[f"Unexpected error: {str(e)}"],
            message="An unexpected error occurred during validation"
        )
