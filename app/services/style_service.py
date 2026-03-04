from __future__ import annotations

from app.style_engine import build_style_render_plan, list_presets
from app.style_engine.types import StylePresetName


class StyleService:
    @staticmethod
    def get_styles() -> list[dict[str, object]]:
        styles = []
        for preset in list_presets():
            styles.append(
                {
                    "id": preset.id.value,
                    "display_name": preset.display_name,
                    "description": preset.description,
                    "defaults": {
                        "tempo_multiplier": preset.defaults.tempo_multiplier,
                        "drum_density": preset.defaults.drum_density,
                        "hat_roll_probability": preset.defaults.hat_roll_probability,
                        "glide_probability": preset.defaults.glide_probability,
                        "swing": preset.defaults.swing,
                        "aggression": preset.defaults.aggression,
                        "melody_complexity": preset.defaults.melody_complexity,
                        "fx_intensity": preset.defaults.fx_intensity,
                    },
                }
            )
        return styles

    @staticmethod
    def preview_structure(
        style_preset: str,
        target_seconds: int,
        bpm: float,
        loop_bars: int = 4,
        seed: int | str | None = None,
    ) -> dict[str, object]:
        plan = build_style_render_plan(
            style_preset=StylePresetName(style_preset),
            target_seconds=target_seconds,
            bpm=bpm,
            loop_bars=loop_bars,
            seed=seed,
        )
        return {
            "seed_used": plan.seed_used,
            "style_preset": plan.style_preset,
            "sections": [
                {"name": item.name, "bars": item.bars, "energy": item.energy}
                for item in plan.sections
            ],
        }


style_service = StyleService()
