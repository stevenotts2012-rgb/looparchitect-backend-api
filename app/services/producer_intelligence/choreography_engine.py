from __future__ import annotations

from typing import Dict, List


def plan_stem_choreography(sections: List[str], stems: List[str], energies: Dict[str, float]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for idx, section in enumerate(sections):
        e = energies[section]
        keep = max(1, round(len(stems) * e))
        active = stems[:keep]
        if idx > 0 and out[sections[idx - 1]] == active and len(stems) > keep:
            active = stems[: max(1, keep - 1)] + [stems[min(len(stems) - 1, keep)]]
        out[section] = active
    return out
