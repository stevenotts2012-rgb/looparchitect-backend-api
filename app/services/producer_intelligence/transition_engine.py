from __future__ import annotations

from typing import Dict, List


def plan_transitions(sections: List[str], energies: Dict[str, float], transition_density: float, fx_density: float, fill_frequency: float = 0.5, silence_usage: float = 0.2) -> List[Dict[str, str]]:
    plans: List[Dict[str, str]] = []
    for idx in range(len(sections) - 1):
        src = sections[idx]
        dst = sections[idx + 1]
        rising = energies[dst] >= energies[src]

        fx_chain = ["riser" if rising else "downlifter", "filter_sweep"]
        if transition_density >= 0.5 and (idx % 2 == 0 or fill_frequency > 0.6):
            fx_chain.append("drum_fill")
        if fx_density >= 0.6:
            fx_chain.append("reverse_fx")
        if not rising and (energies[src] - energies[dst] > 0.2 or silence_usage > 0.3):
            fx_chain.append("silence_moment")
        if rising and "hook" in dst.lower():
            fx_chain.append("staggered_reentry")

        plans.append({"from": src, "to": dst, "fx": "+".join(fx_chain), "handoff": "tight" if rising else "reset"})
    return plans
