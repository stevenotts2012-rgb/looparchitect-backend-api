from app.style_engine.arrangement import generate_section_plan


def test_generate_section_plan_is_deterministic_for_same_seed() -> None:
    seed_1, sections_1 = generate_section_plan(
        style_preset="atl",
        target_seconds=120,
        bpm=140,
        loop_bars=4,
        seed=42,
    )
    seed_2, sections_2 = generate_section_plan(
        style_preset="atl",
        target_seconds=120,
        bpm=140,
        loop_bars=4,
        seed=42,
    )

    assert seed_1 == seed_2
    assert sections_1 == sections_2


def test_generate_section_plan_has_positive_bars() -> None:
    _, sections = generate_section_plan(
        style_preset="dark",
        target_seconds=90,
        bpm=150,
        loop_bars=4,
        seed=99,
    )
    assert sections
    assert all(section.bars > 0 for section in sections)
