from __future__ import annotations

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class BassEvent:
    step: int
    note: int
    glide_to: int | None = None


def generate_bassline(rng: random.Random, root_note: int, glide_probability: float) -> tuple[BassEvent, ...]:
    glide_probability = max(0.0, min(1.0, glide_probability))
    events: list[BassEvent] = []
    for step in (0, 3, 6, 8, 10, 12, 14):
        note = root_note + rng.choice((0, 0, 0, -2, 3))
        glide_to = None
        if rng.random() < glide_probability:
            glide_to = note + rng.choice((-2, 2, 5))
        events.append(BassEvent(step=step, note=note, glide_to=glide_to))
    return tuple(events)
