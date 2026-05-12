from __future__ import annotations

from typing import Dict, List


def escalate_hooks(sections: List[str], energies: Dict[str, float]) -> Dict[str, float]:
    levels: Dict[str, float] = {}
    count = 0
    for section in sections:
        if "hook" in section.lower():
            count += 1
            levels[section] = round(min(1.0, energies[section] + (0.05 * count)), 3)
    return levels
