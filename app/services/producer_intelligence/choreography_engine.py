from __future__ import annotations

from typing import Dict, List

_MELODIC_TOKENS = ("melody", "pad", "harmony", "vocal", "synth", "arp")
_LOW_TOKENS = ("drum", "bass", "808", "kick")


def _is_melodic(role: str) -> bool:
    n = role.lower()
    return any(t in n for t in _MELODIC_TOKENS)


def _is_low(role: str) -> bool:
    n = role.lower()
    return any(t in n for t in _LOW_TOKENS)


def plan_stem_choreography(sections: List[str], stems: List[str], energies: Dict[str, float], silence_usage: float = 0.2) -> Dict[str, List[str]]:
    """Context-aware micro-arrangement choreography with melody-priority guard."""
    result: Dict[str, List[str]] = {}
    previous: List[str] = []
    melodic_pool = [s for s in stems if _is_melodic(s)]

    for idx, section in enumerate(sections):
        target_count = max(1, min(len(stems), round(len(stems) * energies[section])))
        active = stems[:target_count]
        lname = section.lower()

        if "pre_hook" in lname and len(active) > 2:
            active = [s for s in active if "bass" not in s.lower()]
        if "hook" in lname and idx > 0 and "hook_1" in lname and len(active) > 2:
            active = active[:-1]
        if "hook_2" in lname and len(stems) > 2:
            active = stems[: max(2, target_count - 1)] + [stems[-1]]
        if "bridge" in lname and silence_usage >= 0.3 and len(active) > 1:
            active = active[:-1]

        # Melody priority system by section purpose
        if melodic_pool and not any(_is_melodic(a) for a in active):
            active = active[:-1] + [melodic_pool[idx % len(melodic_pool)]]

        if any(k in lname for k in ("intro", "bridge", "outro")) and melodic_pool:
            m = melodic_pool[idx % len(melodic_pool)]
            if m not in active:
                active = [m] + active[:-1]

        # Avoid drums/bass-only sections
        if all(_is_low(a) for a in active) and melodic_pool:
            active = active[:-1] + [melodic_pool[0]]

        if active == previous and len(stems) > 1:
            pivot = (idx + target_count) % len(stems)
            active = active[:-1] + [stems[pivot]]

        result[section] = list(dict.fromkeys(active))
        previous = result[section]
    return result
