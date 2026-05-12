from __future__ import annotations

from typing import Dict

TASTE_PROFILES: Dict[str, Dict[str, float]] = {
    "mainstream_clean": {"transition_density": 0.7, "silence_usage": 0.2, "fill_frequency": 0.55, "energy_aggression": 1.0, "stem_density": 0.85, "hook_emphasis": 0.9, "bridge_isolation": 0.3},
    "dark_atl": {"transition_density": 0.58, "silence_usage": 0.35, "fill_frequency": 0.45, "energy_aggression": 1.08, "stem_density": 0.8, "hook_emphasis": 1.0, "bridge_isolation": 0.4},
    "emotional_melodic": {"transition_density": 0.48, "silence_usage": 0.24, "fill_frequency": 0.4, "energy_aggression": 0.92, "stem_density": 0.72, "hook_emphasis": 0.95, "bridge_isolation": 0.45},
    "soulful_smooth": {"transition_density": 0.42, "silence_usage": 0.28, "fill_frequency": 0.35, "energy_aggression": 0.88, "stem_density": 0.68, "hook_emphasis": 0.82, "bridge_isolation": 0.5},
    "aggressive_club": {"transition_density": 0.92, "silence_usage": 0.15, "fill_frequency": 0.78, "energy_aggression": 1.16, "stem_density": 0.95, "hook_emphasis": 1.15, "bridge_isolation": 0.25},
    "ambient_spacious": {"transition_density": 0.35, "silence_usage": 0.4, "fill_frequency": 0.22, "energy_aggression": 0.8, "stem_density": 0.6, "hook_emphasis": 0.75, "bridge_isolation": 0.62},
}


def resolve_taste_profile(name: str | None) -> Dict[str, float]:
    return dict(TASTE_PROFILES.get((name or "mainstream_clean").strip().lower(), TASTE_PROFILES["mainstream_clean"]))
