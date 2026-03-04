from __future__ import annotations

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class MelodyEvent:
    step: int
    note: int
    length_steps: int


def generate_melody(rng: random.Random, root_note: int, complexity: float) -> tuple[MelodyEvent, ...]:
    complexity = max(0.0, min(1.0, complexity))
    step_count = 4 + int(complexity * 8)
    events: list[MelodyEvent] = []
    scale = (0, 2, 3, 5, 7, 10)
    for _ in range(step_count):
        step = rng.randint(0, 15)
        note = root_note + rng.choice(scale) + rng.choice((0, 12))
        length = 1 if rng.random() < 0.7 else 2
        events.append(MelodyEvent(step=step, note=note, length_steps=length))
    events.sort(key=lambda item: item.step)
    return tuple(events)
