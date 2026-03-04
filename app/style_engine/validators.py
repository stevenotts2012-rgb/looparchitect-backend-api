from __future__ import annotations

from app.style_engine.types import StyleParamOverrides


ALLOWED_PARAM_KEYS = {
    "tempo_multiplier",
    "drum_density",
    "hat_roll_probability",
    "glide_probability",
    "swing",
    "aggression",
    "melody_complexity",
    "fx_intensity",
}


def validate_style_overrides(overrides: StyleParamOverrides | None) -> dict[str, float]:
    if not overrides:
        return {}

    validated: dict[str, float] = {}
    for key, value in overrides.items():
        if key not in ALLOWED_PARAM_KEYS:
            continue
        numeric = float(value)
        if key == "tempo_multiplier":
            validated[key] = max(0.5, min(1.5, numeric))
        else:
            validated[key] = max(0.0, min(1.0, numeric))
    return validated


def validate_variation_count(variation_count: int, enabled: bool) -> int:
    if not enabled:
        return 1
    return max(1, min(3, variation_count))
