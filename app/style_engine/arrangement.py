from __future__ import annotations

from app.style_engine.energy_curve import scale_section_energies
from app.style_engine.presets import get_preset
from app.style_engine.seed import create_rng
from app.style_engine.types import SectionPlanItem, StylePresetName


def _target_bars_from_duration(target_seconds: int, bpm: float) -> int:
    if target_seconds <= 0 or bpm <= 0:
        raise ValueError("target_seconds and bpm must be positive")
    bar_seconds = (60.0 / bpm) * 4.0
    return max(4, int(round(target_seconds / bar_seconds)))


def generate_section_plan(
    style_preset: StylePresetName | str,
    target_seconds: int,
    bpm: float,
    loop_bars: int = 4,
    seed: int | str | None = None,
) -> tuple[int, list[SectionPlanItem]]:
    if loop_bars < 4 or loop_bars > 8:
        raise ValueError("loop_bars must be between 4 and 8")

    seed_used, rng = create_rng(seed)
    preset = get_preset(style_preset)
    target_bars = _target_bars_from_duration(target_seconds=target_seconds, bpm=bpm)

    section_pool = list(preset.section_templates)
    if not section_pool:
        return seed_used, []

    planned: list[SectionPlanItem] = []
    consumed = 0
    idx = 0
    while consumed < target_bars:
        template = section_pool[idx % len(section_pool)]
        remaining = target_bars - consumed
        bars = min(template.bars, remaining)
        bars = max(loop_bars, bars) if remaining >= loop_bars else remaining
        bars = min(bars, remaining)

        jitter = rng.uniform(-0.03, 0.03)
        energy = max(0.0, min(1.0, template.energy + jitter))

        planned.append(SectionPlanItem(name=template.name, bars=bars, energy=energy))
        consumed += bars
        idx += 1

    return seed_used, scale_section_energies(planned)
