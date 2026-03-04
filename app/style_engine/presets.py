from __future__ import annotations

from app.style_engine.types import SectionTemplate, StyleParameters, StylePreset, StylePresetName


DEFAULT_TEMPLATE: tuple[SectionTemplate, ...] = (
    SectionTemplate(name="intro", bars=8, energy=0.30),
    SectionTemplate(name="hook", bars=8, energy=0.82),
    SectionTemplate(name="verse", bars=16, energy=0.62),
    SectionTemplate(name="bridge", bars=8, energy=0.52),
    SectionTemplate(name="drop", bars=8, energy=0.92),
    SectionTemplate(name="outro", bars=8, energy=0.40),
)


PRESETS: dict[StylePresetName, StylePreset] = {
    StylePresetName.ATL: StylePreset(
        id=StylePresetName.ATL,
        display_name="ATL / Mainstream Trap",
        description="Punchy drums, modern transitions, radio-ready trap structure.",
        defaults=StyleParameters(
            tempo_multiplier=1.0,
            drum_density=0.72,
            hat_roll_probability=0.36,
            glide_probability=0.24,
            swing=0.08,
            aggression=0.68,
            melody_complexity=0.46,
            fx_intensity=0.62,
        ),
        section_templates=DEFAULT_TEMPLATE,
    ),
    StylePresetName.DARK: StylePreset(
        id=StylePresetName.DARK,
        display_name="Dark / Aggressive",
        description="Heavier bass, sparse melodies, aggressive transitions.",
        defaults=StyleParameters(
            tempo_multiplier=1.0,
            drum_density=0.66,
            hat_roll_probability=0.28,
            glide_probability=0.42,
            swing=0.04,
            aggression=0.90,
            melody_complexity=0.30,
            fx_intensity=0.78,
        ),
        section_templates=DEFAULT_TEMPLATE,
    ),
    StylePresetName.MELODIC: StylePreset(
        id=StylePresetName.MELODIC,
        display_name="Melodic",
        description="Richer harmony, smoother transitions, less percussive pressure.",
        defaults=StyleParameters(
            tempo_multiplier=0.98,
            drum_density=0.52,
            hat_roll_probability=0.18,
            glide_probability=0.12,
            swing=0.10,
            aggression=0.35,
            melody_complexity=0.82,
            fx_intensity=0.44,
        ),
        section_templates=DEFAULT_TEMPLATE,
    ),
    StylePresetName.DRILL: StylePreset(
        id=StylePresetName.DRILL,
        display_name="Drill",
        description="Syncopated bounce, active hats, sliding bass movement.",
        defaults=StyleParameters(
            tempo_multiplier=1.04,
            drum_density=0.74,
            hat_roll_probability=0.48,
            glide_probability=0.45,
            swing=0.12,
            aggression=0.84,
            melody_complexity=0.42,
            fx_intensity=0.58,
        ),
        section_templates=DEFAULT_TEMPLATE,
    ),
    StylePresetName.CINEMATIC: StylePreset(
        id=StylePresetName.CINEMATIC,
        display_name="Cinematic",
        description="Longer builds, spacious atmosphere, bigger drops.",
        defaults=StyleParameters(
            tempo_multiplier=0.95,
            drum_density=0.50,
            hat_roll_probability=0.14,
            glide_probability=0.18,
            swing=0.06,
            aggression=0.48,
            melody_complexity=0.70,
            fx_intensity=0.86,
        ),
        section_templates=DEFAULT_TEMPLATE,
    ),
    StylePresetName.CLUB: StylePreset(
        id=StylePresetName.CLUB,
        display_name="Club",
        description="Groove-forward, repetitive drive, high dance-floor energy.",
        defaults=StyleParameters(
            tempo_multiplier=1.02,
            drum_density=0.80,
            hat_roll_probability=0.26,
            glide_probability=0.16,
            swing=0.10,
            aggression=0.62,
            melody_complexity=0.34,
            fx_intensity=0.50,
        ),
        section_templates=DEFAULT_TEMPLATE,
    ),
    StylePresetName.EXPERIMENTAL: StylePreset(
        id=StylePresetName.EXPERIMENTAL,
        display_name="Experimental",
        description="Surprising but bounded randomization for patterns and transitions.",
        defaults=StyleParameters(
            tempo_multiplier=1.0,
            drum_density=0.67,
            hat_roll_probability=0.40,
            glide_probability=0.34,
            swing=0.14,
            aggression=0.74,
            melody_complexity=0.76,
            fx_intensity=0.82,
        ),
        section_templates=DEFAULT_TEMPLATE,
    ),
}


def list_presets() -> list[StylePreset]:
    return list(PRESETS.values())


def get_preset(name: StylePresetName | str) -> StylePreset:
    key = StylePresetName(str(name).lower())
    return PRESETS[key]
