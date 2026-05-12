from __future__ import annotations

from typing import Dict, List


def escalate_hooks(sections: List[str], energies: Dict[str, float], hook_emphasis: float = 1.0) -> Dict[str, float]:
    levels: Dict[str, float] = {}
    count = 0
    for section in sections:
        if "hook" in section.lower():
            count += 1
            stereo_bonus = 0.03 * hook_emphasis
            density_bonus = 0.05 * count * hook_emphasis
            levels[section] = round(min(1.25, energies[section] + density_bonus + stereo_bonus), 3)
    return levels
