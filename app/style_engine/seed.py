from __future__ import annotations

import hashlib
import random
from typing import Any


def normalize_seed(seed: int | str | None) -> int:
    if seed is None:
        return random.SystemRandom().randint(0, 2**31 - 1)
    if isinstance(seed, int):
        return seed & 0x7FFFFFFF
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def create_rng(seed: int | str | None) -> tuple[int, random.Random]:
    normalized = normalize_seed(seed)
    return normalized, random.Random(normalized)


def choice_weighted(rng: random.Random, options: list[Any], weights: list[float]) -> Any:
    if not options or len(options) != len(weights):
        raise ValueError("options and weights must be non-empty and same length")
    total = sum(weights)
    if total <= 0:
        raise ValueError("weights must sum to a positive value")
    threshold = rng.uniform(0, total)
    running = 0.0
    for option, weight in zip(options, weights):
        running += weight
        if running >= threshold:
            return option
    return options[-1]
