from __future__ import annotations

def simplify_outro(energy: float) -> float:
    return round(max(0.08, energy - 0.18), 3)
