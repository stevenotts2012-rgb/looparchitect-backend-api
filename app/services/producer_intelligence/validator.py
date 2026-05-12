from __future__ import annotations

from typing import Dict, List


def validate_plan(sections: List[str], energies: Dict[str, float], stem_map: Dict[str, List[str]], transitions: List[Dict[str, str]], hook_levels: Dict[str, float]) -> List[str]:
    issues: List[str] = []
    if len(set(energies.values())) <= 2:
        issues.append("flat_arrangement")
    if len(transitions) < max(0, len(sections) - 1):
        issues.append("missing_transitions")
    fingerprints = [tuple(stem_map[s]) for s in sections]
    if len(set(fingerprints)) == 1:
        issues.append("identical_sections")
    hooks = [s for s in sections if "hook" in s.lower()]
    if len(hooks) >= 2 and hook_levels.get(hooks[-1], 0) <= hook_levels.get(hooks[0], 0):
        issues.append("repetitive_hook_reuse")
    if any("bridge" in s.lower() for s in sections) and hooks:
        bridge = next(s for s in sections if "bridge" in s.lower())
        if energies[bridge] >= max(energies[h] for h in hooks):
            issues.append("bridge_not_reset")
    if any("outro" in s.lower() for s in sections):
        outro = next(s for s in sections if "outro" in s.lower())
        if energies[outro] > energies[sections[-2]]:
            issues.append("unresolved_ending")
    return issues
