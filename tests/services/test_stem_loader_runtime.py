from pydub import AudioSegment

from app.services.stem_loader import map_instruments_to_stems


def test_map_instruments_to_stems_excludes_full_mix_when_isolated_layers_exist() -> None:
    available = {
        "full_mix": AudioSegment.silent(duration=500),
        "drums": AudioSegment.silent(duration=500),
        "bass": AudioSegment.silent(duration=500),
        "melody": AudioSegment.silent(duration=500),
        "pads": AudioSegment.silent(duration=500),
    }

    enabled = map_instruments_to_stems(
        ["drums", "bass", "melody", "pads", "full_mix"],
        available,
    )

    assert list(enabled.keys()) == ["drums", "bass", "melody", "pads"]


def test_map_instruments_to_stems_preserves_exact_runtime_roles() -> None:
    available = {
        "pads": AudioSegment.silent(duration=500),
        "harmony": AudioSegment.silent(duration=500),
        "percussion": AudioSegment.silent(duration=500),
    }

    enabled = map_instruments_to_stems(["pads", "percussion"], available)

    assert list(enabled.keys()) == ["pads", "percussion"]
