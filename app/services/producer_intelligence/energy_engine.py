from __future__ import annotations

from typing import Dict, List


_BASE = {"intro": 0.25, "verse": 0.45, "pre_hook": 0.62, "hook": 0.8, "bridge": 0.42, "outro": 0.35}
_MULT = {"smooth": 1.0, "aggressive": 1.12, "emotional": 0.95}


def build_energy_curve(sections: List[str], curve: str = "smooth") -> Dict[str, float]:
    mult = _MULT.get(curve, 1.0)
    hooks_seen = 0
    values: Dict[str, float] = {}
    for name in sections:
        token = _canonical(name)
        val = _BASE.get(token, 0.5) * mult
        if token == "hook":
            hooks_seen += 1
            if hooks_seen >= 2:
                val += 0.08
        if token == "bridge":
            val = min(val, 0.5)
        if token == "outro":
            val = min(val, 0.4)
        values[name] = round(max(0.05, min(val, 1.0)), 3)
    return values


def _canonical(section_name: str) -> str:
    n = section_name.lower()
    if "pre" in n and "hook" in n:
        return "pre_hook"
    for t in ("intro", "verse", "hook", "bridge", "outro"):
        if t in n:
            return t
    return "verse"
