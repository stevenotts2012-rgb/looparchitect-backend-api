from __future__ import annotations

from app.style_engine.types import SectionPlanItem


def scale_section_energies(
    sections: list[SectionPlanItem],
    base_multiplier: float = 1.0,
) -> list[SectionPlanItem]:
    if not sections:
        return []
    scaled: list[SectionPlanItem] = []
    for item in sections:
        energy = max(0.0, min(1.0, item.energy * base_multiplier))
        scaled.append(SectionPlanItem(name=item.name, bars=item.bars, energy=energy))
    return scaled
