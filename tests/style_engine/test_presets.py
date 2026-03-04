from app.style_engine.presets import list_presets


def test_style_presets_count_and_uniqueness() -> None:
    presets = list_presets()
    assert len(presets) == 7

    ids = [preset.id.value for preset in presets]
    assert len(ids) == len(set(ids))
