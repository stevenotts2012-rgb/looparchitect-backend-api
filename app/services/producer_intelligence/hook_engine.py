from __future__ import annotations

from typing import Dict, List


def escalate_hooks(sections: List[str], energies: Dict[str, float]) -> Dict[str, float]:
    intensities: Dict[str, float] = {}
    n = 0
    for s in sections:
        if "hook" in s.lower():
            n += 1
            intensities[s] = round(energies[s] + (0.04 * n), 3)
    return intensities
