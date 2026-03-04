from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class StylePresetName(StrEnum):
    ATL = "atl"
    DARK = "dark"
    MELODIC = "melodic"
    DRILL = "drill"
    CINEMATIC = "cinematic"
    CLUB = "club"
    EXPERIMENTAL = "experimental"


@dataclass(frozen=True)
class SectionTemplate:
    name: str
    bars: int
    energy: float


@dataclass(frozen=True)
class SectionPlanItem:
    name: str
    bars: int
    energy: float


@dataclass(frozen=True)
class StyleParameters:
    tempo_multiplier: float = 1.0
    drum_density: float = 0.6
    hat_roll_probability: float = 0.2
    glide_probability: float = 0.15
    swing: float = 0.0
    aggression: float = 0.5
    melody_complexity: float = 0.5
    fx_intensity: float = 0.5


@dataclass(frozen=True)
class StylePreset:
    id: StylePresetName
    display_name: str
    description: str
    defaults: StyleParameters
    section_templates: tuple[SectionTemplate, ...] = field(default_factory=tuple)


StyleParamOverrides = Mapping[str, Any]
