from __future__ import annotations

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class DrumPattern:
    kick_steps: tuple[int, ...]
    snare_steps: tuple[int, ...]
    hat_steps: tuple[int, ...]
    perc_steps: tuple[int, ...]


def generate_drum_pattern(rng: random.Random, density: float, hat_roll_probability: float) -> DrumPattern:
    density = max(0.0, min(1.0, density))
    hat_roll_probability = max(0.0, min(1.0, hat_roll_probability))

    kick = tuple(step for step in range(16) if rng.random() < (0.12 + density * 0.28))
    snare = tuple(step for step in (4, 12) if rng.random() < 0.95)
    hat = tuple(step for step in range(16) if rng.random() < (0.25 + density * 0.45))
    perc = tuple(step for step in range(16) if rng.random() < (0.05 + density * 0.2))

    if rng.random() < hat_roll_probability:
        hat = tuple(sorted(set(hat + (7, 8, 9))))

    return DrumPattern(kick_steps=kick, snare_steps=snare, hat_steps=hat, perc_steps=perc)
