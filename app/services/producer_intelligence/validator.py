from __future__ import annotations

from typing import Dict, List


def validate_plan(sections: List[str], energies: Dict[str, float], stem_map: Dict[str, List[str]], transitions: List[Dict[str, str]], hook_levels: Dict[str, float]) -> List[str]:
    issues: List[str] = []

    if len(set(energies.values())) <= 2:
        issues.append("flat_arrangements")
    if max(energies.values()) - min(energies.values()) < 0.2:
        issues.append("no_energy_evolution")

    if len(transitions) != max(0, len(sections) - 1):
        issues.append("missing_transitions")

    fingerprints = [tuple(stem_map[s]) for s in sections]
    if len(set(fingerprints)) == 1:
        issues.append("identical_sections")

    hooks = [s for s in sections if "hook" in s.lower()]
    if len(hooks) >= 2 and hook_levels[hooks[-1]] <= hook_levels[hooks[0]]:
        issues.append("repetitive_hook_reuse")

    if any("outro" in s.lower() for s in sections):
        outro = next(s for s in sections if "outro" in s.lower())
        if energies[outro] >= energies[sections[-2]]:
            issues.append("unresolved_endings")

    return issues
