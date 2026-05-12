from __future__ import annotations

from typing import Dict, List


def plan_stem_choreography(sections: List[str], stems: List[str], energies: Dict[str, float], silence_usage: float = 0.2) -> Dict[str, List[str]]:
    """Context-aware micro-arrangement choreography (deterministic)."""
    result: Dict[str, List[str]] = {}
    previous: List[str] = []

    for idx, section in enumerate(sections):
        target_count = max(1, min(len(stems), round(len(stems) * energies[section])))
        active = stems[:target_count]
        lname = section.lower()

        if "pre_hook" in lname and len(active) > 2:
            active = [s for s in active if s not in {"bass"}]  # tension pull
        if "hook" in lname and idx > 0 and "hook_1" in lname and len(active) > 2:
            active = active[:-1]  # anticipation slot before bigger hook return
        if "hook_2" in lname and len(stems) > 2:
            active = stems[: max(2, target_count - 1)] + [stems[-1]]  # selective re-entry accent
        if "bridge" in lname and silence_usage >= 0.3 and len(active) > 1:
            active = active[:-1]  # transition silence moment / isolation

        if active == previous and len(stems) > 1:
            pivot = (idx + target_count) % len(stems)
            active = active[:-1] + [stems[pivot]]  # fatigue prevention stem rotation

        result[section] = active
        previous = active
    return result
