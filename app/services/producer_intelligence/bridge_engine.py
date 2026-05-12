from __future__ import annotations

def apply_bridge_reset(energy: float) -> float:
    return round(max(0.1, energy - 0.2), 3)
