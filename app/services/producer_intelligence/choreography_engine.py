from __future__ import annotations

from typing import Dict, List


def plan_stem_choreography(sections: List[str], stems: List[str], energies: Dict[str, float]) -> Dict[str, List[str]]:
    """Create intentional muting/unmuting with anti-copy behavior."""
    result: Dict[str, List[str]] = {}
    previous: List[str] = []

    for idx, section in enumerate(sections):
        target_count = max(1, min(len(stems), round(len(stems) * energies[section])))
        active = stems[:target_count]

        if "verse_2" in section.lower() and len(stems) >= 3:
            active = [stems[0], stems[2]] + stems[3:target_count]

        if "hook" in section.lower() and idx > 0:
            # anticipation: keep one slot open for impact, then re-enable in next hook
            if "hook_1" in section.lower() and target_count == len(stems):
                active = stems[:-1]
            if "hook_2" in section.lower() and len(stems) > 2:
                active = stems[: target_count - 1] + [stems[-1]]

        if active == previous and len(stems) > 1:
            pivot = (idx + target_count) % len(stems)
            active = active[:-1] + [stems[pivot]]

        result[section] = active
        previous = active
    return result
