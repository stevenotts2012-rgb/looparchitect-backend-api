from app.services.stem_classifier import classify_stem


class _StubAudio:
    def __init__(self, rms: int) -> None:
        self.rms = rms

    def low_pass_filter(self, _freq: int):
        return _StubAudio(700)

    def high_pass_filter(self, _freq: int):
        if _freq >= 2500:
            return _StubAudio(400)
        return _StubAudio(800)


def test_classify_stem_uses_full_mix_fallback_when_no_hint_or_band_match() -> None:
    result = classify_stem("mystery_layer.wav", _StubAudio(1000))
    assert result.role == "full_mix"
    assert "full_mix" in result.reason
