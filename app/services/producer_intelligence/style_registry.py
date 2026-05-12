from __future__ import annotations

from typing import Any, Dict

_BASE = {
    "energy_curve": "smooth",
    "energy_bias": 1.0,
    "transition_density": 0.6,
    "fx_density": 0.5,
    "producer_personality": "intentional",
    "section_behavior": {"bridge_reset": 0.22, "outro_simplify": 0.2},
}

_PROFILES: Dict[str, Dict[str, Any]] = {
    "edm": {"energy_curve": "aggressive", "energy_bias": 1.08, "transition_density": 0.92, "fx_density": 0.82},
    "pop": {"energy_curve": "smooth", "energy_bias": 1.02, "transition_density": 0.66, "fx_density": 0.54},
    "rnb": {"energy_curve": "emotional", "energy_bias": 0.94, "transition_density": 0.5, "fx_density": 0.4},
    "hip hop": {"energy_curve": "aggressive", "energy_bias": 1.0, "transition_density": 0.58, "fx_density": 0.42},
}

_MOOD_OVERRIDES = {
    "emotional": {"energy_curve": "emotional", "producer_personality": "expressive"},
    "melancholic": {"energy_curve": "emotional", "energy_bias": 0.92},
    "hype": {"energy_curve": "aggressive", "energy_bias": 1.1},
}


def resolve_style(style: str | None, mood: str | None = None) -> Dict[str, Any]:
    """Resolve style config; unknown user-entered styles gracefully fallback."""
    resolved = dict(_BASE)
    key = (style or "").strip().lower()
    resolved.update(_PROFILES.get(key, {}))
    mood_key = (mood or "").strip().lower()
    resolved.update(_MOOD_OVERRIDES.get(mood_key, {}))
    resolved["style_key"] = key or "custom"
    resolved["mood_key"] = mood_key or "default"
    return resolved
