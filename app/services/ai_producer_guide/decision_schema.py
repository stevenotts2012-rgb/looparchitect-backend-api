from __future__ import annotations

from typing import Any, Dict, List


REQUIRED_TOP_KEYS = {
    "style_traits",
    "arrangement_advice",
    "mix_priorities",
    "variation_strategy",
    "do_not_do",
}


class GuideSchemaError(ValueError):
    pass


def validate_guide_schema(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise GuideSchemaError("Guide payload must be an object")
    missing = REQUIRED_TOP_KEYS - set(payload.keys())
    if missing:
        raise GuideSchemaError(f"Missing keys: {sorted(missing)}")

    traits = payload["style_traits"]
    for k in ["tempo_feel", "drum_feel", "bass_behavior", "melody_behavior", "transition_density", "section_pacing", "energy_curve"]:
        if not isinstance(traits.get(k), str):
            raise GuideSchemaError(f"style_traits.{k} must be string")

    advice = payload["arrangement_advice"]
    for sec in ["intro", "verse", "pre_hook", "hook", "bridge", "outro"]:
        if not isinstance(advice.get(sec), list):
            raise GuideSchemaError(f"arrangement_advice.{sec} must be list")

    mix = payload["mix_priorities"]
    for num in ["melody_priority", "hook_melody_lift_db", "bass_aggression"]:
        if not isinstance(mix.get(num), (int, float)):
            raise GuideSchemaError(f"mix_priorities.{num} must be number")
    if not isinstance(mix.get("drum_bass_ducking_needed"), bool):
        raise GuideSchemaError("mix_priorities.drum_bass_ducking_needed must be bool")

    variations = payload["variation_strategy"]
    if not isinstance(variations, list) or len(variations) < 2:
        raise GuideSchemaError("variation_strategy must contain at least two entries")
    for i, item in enumerate(variations):
        for key, t in [("variation_index", int), ("personality", str), ("focus", str), ("avoid", list)]:
            if not isinstance(item.get(key), t):
                raise GuideSchemaError(f"variation_strategy[{i}].{key} invalid")

    if not isinstance(payload["do_not_do"], list):
        raise GuideSchemaError("do_not_do must be list")
    return payload
