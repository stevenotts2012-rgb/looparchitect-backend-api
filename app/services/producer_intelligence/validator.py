from __future__ import annotations

from typing import Dict, List


def validate_plan(sections: List[str], energies: Dict[str, float], stem_map: Dict[str, List[str]], transitions: List[Dict[str, str]], hook_levels: Dict[str, float]) -> List[str]:
    issues: List[str] = []

    if len(set(energies.values())) <= 2:
        issues.append("robotic_repetition")
    if max(energies.values()) - min(energies.values()) < 0.2:
        issues.append("static_density")

    if len(transitions) != max(0, len(sections) - 1):
        issues.append("missing_transitions")
    transition_fingerprints = [t["fx"] for t in transitions]
    if len(transition_fingerprints) > 2 and len(set(transition_fingerprints)) <= 1:
        issues.append("repetitive_transitions")

    fingerprints = [tuple(stem_map[s]) for s in sections]
    if len(set(fingerprints)) == 1:
        issues.append("robotic_repetition")

    hooks = [s for s in sections if "hook" in s.lower()]
    if len(hooks) >= 2 and hook_levels[hooks[-1]] <= hook_levels[hooks[0]]:
        issues.append("flat_hook_payoff")

    if hooks and hooks[-1] in hook_levels and hook_levels[hooks[-1]] < 0.82:
        issues.append("unresolved_final_hook")

    return issues
