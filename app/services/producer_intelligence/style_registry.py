from __future__ import annotations

from typing import Any, Dict

_DEFAULT_STYLE: Dict[str, Any] = {
    "energy_curve": "smooth",
    "transition_density": 0.6,
    "fx_density": 0.5,
    "producer_personality": "intentional",
    "section_behavior": {"bridge_reset": 0.5, "outro_simplify": 0.4},
}

_STYLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "edm": {"energy_curve": "aggressive", "transition_density": 0.9, "fx_density": 0.8},
    "pop": {"energy_curve": "smooth", "transition_density": 0.6, "fx_density": 0.5},
    "rnb": {"energy_curve": "emotional", "transition_density": 0.45, "fx_density": 0.35},
}


def resolve_style(style: str | None, mood: str | None = None) -> Dict[str, Any]:
    key = (style or "").lower().strip()
    base = dict(_DEFAULT_STYLE)
    base.update(_STYLE_PRESETS.get(key, {}))
    if mood and mood.lower() in {"melancholic", "emotional"}:
        base["energy_curve"] = "emotional"
    return base
