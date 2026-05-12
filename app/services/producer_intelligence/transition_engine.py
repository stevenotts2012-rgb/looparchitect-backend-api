from __future__ import annotations

from typing import Dict, List


def plan_transitions(sections: List[str], energies: Dict[str, float], density: float) -> List[Dict[str, str]]:
    plans: List[Dict[str, str]] = []
    for i in range(len(sections) - 1):
        src, dst = sections[i], sections[i + 1]
        up = energies[dst] > energies[src]
        fx = "riser+fill" if up else "downlifter+filter_sweep"
        if density > 0.75:
            fx += "+reverse_fx"
        plans.append({"from": src, "to": dst, "fx": fx})
    return plans
