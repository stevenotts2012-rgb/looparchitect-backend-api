from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StyleContext:
    genre: str
    mood: str
    energy: str
    bpm: float
    key: str
    style_prompt: str | None = None
