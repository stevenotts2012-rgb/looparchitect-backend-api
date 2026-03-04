from __future__ import annotations

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class TransitionEvent:
    section_index: int
    kind: str
    intensity: float


def generate_transitions(rng: random.Random, section_count: int, fx_intensity: float) -> tuple[TransitionEvent, ...]:
    fx_intensity = max(0.0, min(1.0, fx_intensity))
    events: list[TransitionEvent] = []
    for idx in range(max(0, section_count - 1)):
        if rng.random() < (0.15 + fx_intensity * 0.6):
            kind = rng.choice(("riser", "fill", "drop_fx"))
            events.append(TransitionEvent(section_index=idx, kind=kind, intensity=fx_intensity))
    return tuple(events)
