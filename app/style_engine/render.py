from __future__ import annotations

from dataclasses import dataclass

from app.style_engine.arrangement import generate_section_plan
from app.style_engine.seed import create_rng
from app.style_engine.types import SectionPlanItem, StylePresetName


@dataclass(frozen=True)
class StyleRenderPlan:
    seed_used: int
    style_preset: str
    sections: tuple[SectionPlanItem, ...]


def build_style_render_plan(
    style_preset: StylePresetName | str,
    target_seconds: int,
    bpm: float,
    loop_bars: int,
    seed: int | str | None,
) -> StyleRenderPlan:
    seed_used, _ = create_rng(seed)
    normalized_seed, sections = generate_section_plan(
        style_preset=style_preset,
        target_seconds=target_seconds,
        bpm=bpm,
        loop_bars=loop_bars,
        seed=seed_used,
    )
    return StyleRenderPlan(
        seed_used=normalized_seed,
        style_preset=str(style_preset),
        sections=tuple(sections),
    )
