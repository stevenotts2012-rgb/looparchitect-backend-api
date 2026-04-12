"""Pydantic schemas for LLM-powered style engine (Style Engine V2)."""

from typing import Optional, List
from pydantic import BaseModel, Field


class StyleIntent(BaseModel):
    """LLM-parsed intent from user's natural language input."""
    
    archetype: str = Field(
        ...,
        description="Mapped archetype (atl_aggressive, dark_drill, melodic_trap, etc.)",
    )
    attributes: dict[str, float] = Field(
        default_factory=dict,
        description="Attribute modifiers (aggression, darkness, bounce, etc.) in range [0, 1]",
    )
    transitions: List[dict] = Field(
        default_factory=list,
        description="Special transitions like beat switches",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="LLM confidence score for parsing quality",
    )
    raw_input: str = Field(
        default="",
        description="Original user input for audit trail",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "archetype": "atl_aggressive",
                "attributes": {
                    "aggression": 0.85,
                    "darkness": 0.70,
                    "bounce": 0.60,
                },
                "transitions": [
                    {"type": "beat_switch", "bar": 32, "new_energy": 0.95}
                ],
                "confidence": 0.92,
                "raw_input": "Southside type, aggressive, beat switch after hook",
            }
        }


class StyleOverrides(BaseModel):
    """User-specified overrides from frontend sliders."""
    
    # Attribute dimension overrides (0-1 range)
    aggression: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override aggression (drum intensity, transition harshness)",
    )
    darkness: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override darkness (bass weight, minor tonality)",
    )
    bounce: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override bounce (swing, groove emphasis)",
    )
    melody_complexity: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override melody complexity (melody density, harmonic richness)",
    )
    energy_variance: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override energy variance (section energy fluctuation)",
    )
    transition_intensity: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override transition intensity (abruptness of section changes)",
    )
    fx_density: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override fx density (reverb, delay, filter sweeps)",
    )
    bass_presence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override bass presence (low-end weight)",
    )
    
    # Legacy StyleParameters overrides
    tempo_multiplier: Optional[float] = Field(
        default=None,
        ge=0.5,
        le=2.0,
        description="Legacy: tempo adjustment multiplier",
    )
    drum_density: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Legacy: drum pattern density",
    )
    hat_roll_probability: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Legacy: hat roll occurrence probability",
    )
    glide_probability: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Legacy: bass glide probability",
    )
    swing: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Legacy: swing/shuffle amount",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "aggression": 0.80,
                "darkness": 0.70,
                "bounce": 0.65,
                "melody_complexity": 0.50,
            }
        }


class StyleProfile(BaseModel):
    """Complete style profile for arrangement rendering."""
    
    intent: StyleIntent = Field(
        ...,
        description="LLM-parsed style intent from user input",
    )
    overrides: Optional[StyleOverrides] = Field(
        default=None,
        description="User-specified slider overrides",
    )
    resolved_preset: str = Field(
        ...,
        description="Base preset after archetype mapping (atl, dark, melodic, etc.)",
    )
    resolved_params: dict = Field(
        ...,
        description="Final StyleParameters as dict after all modifiers applied",
    )
    sections: List[dict] = Field(
        ...,
        description="Section plan with beat switches and transitions",
    )
    seed: Optional[int] = Field(
        default=None,
        description="Seed for deterministic audio synthesis",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "intent": {
                    "archetype": "atl_aggressive",
                    "attributes": {
                        "aggression": 0.85,
                        "darkness": 0.60,
                        "bounce": 0.70,
                    },
                    "transitions": [
                        {"type": "beat_switch", "bar": 32, "new_energy": 0.95}
                    ],
                    "confidence": 0.92,
                    "raw_input": "Southside type, aggressive, beat switch after hook",
                },
                "overrides": None,
                "resolved_preset": "atl",
                "resolved_params": {
                    "aggression": 0.88,
                    "drum_density": 0.82,
                    "hat_roll_probability": 0.42,
                    "glide_probability": 0.30,
                    "swing": 0.10,
                    "melody_complexity": 0.40,
                    "fx_intensity": 0.68,
                    "tempo_multiplier": 1.0,
                },
                "sections": [
                    {
                        "name": "intro",
                        "bars": 8,
                        "energy": 0.35,
                        "start_bar": 0,
                        "end_bar": 7,
                    },
                    {
                        "name": "hook",
                        "bars": 8,
                        "energy": 0.85,
                        "start_bar": 8,
                        "end_bar": 15,
                    },
                    {
                        "name": "beat_switch",
                        "bars": 8,
                        "energy": 0.95,
                        "start_bar": 32,
                        "end_bar": 39,
                    },
                ],
                "seed": 42,
            }
        }
