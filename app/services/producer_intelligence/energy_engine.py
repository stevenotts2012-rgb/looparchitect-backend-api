from __future__ import annotations

from typing import Dict, List

_BASE = {"intro": 0.24, "verse": 0.45, "pre_hook": 0.62, "hook": 0.8, "bridge": 0.4, "outro": 0.34}
_CURVE_OFFSETS = {
    "smooth": [0.0, 0.01, 0.0, 0.015],
    "aggressive": [0.02, 0.03, 0.01, 0.04],
    "emotional": [-0.02, 0.0, 0.015, 0.01],
}


def build_energy_curve(sections: List[str], curve: str, energy_bias: float = 1.0) -> Dict[str, float]:
    offsets = _CURVE_OFFSETS.get(curve, _CURVE_OFFSETS["smooth"])
    hook_count = 0
    out: Dict[str, float] = {}
    for idx, section in enumerate(sections):
        kind = _canonical(section)
        value = _BASE.get(kind, 0.5)
        value += offsets[idx % len(offsets)]
        value *= energy_bias
        if kind == "hook":
            hook_count += 1
            value += (hook_count - 1) * 0.08
        if kind == "bridge":
            value = min(value, 0.5)
        if kind == "outro":
            value = min(value, 0.4)
        out[section] = round(max(0.08, min(value, 1.0)), 3)
    return out


def _canonical(section_name: str) -> str:
    n = section_name.lower()
    if "pre" in n and "hook" in n:
        return "pre_hook"
    for token in ("intro", "verse", "hook", "bridge", "outro"):
        if token in n:
            return token
    return "verse"
