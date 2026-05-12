from app.services.style_intelligence.reference_style_parser import StyleResearchProvider, resolve_style_traits
from app.services.style_intelligence.style_context import StyleContext


class _FailProvider(StyleResearchProvider):
    def research_genre_traits(self, style_query: str) -> dict:
        raise RuntimeError("boom")


class _GoodProvider(StyleResearchProvider):
    def research_genre_traits(self, style_query: str) -> dict:
        return {"mood_vocab": ["dark", "focused"], "transition_density": "high"}


def test_style_prompt_honored_and_arbitrary_style_preserved():
    ctx = StyleContext(genre="afrobeat dance groove", mood="uplift", energy="high", bpm=108, key="D", style_prompt="smooth R&B late-night vibe")
    traits = resolve_style_traits(ctx)
    assert traits["melody_density"] == "high"


def test_web_research_failure_falls_back_safely():
    ctx = StyleContext(genre="dark atl trap bounce", mood="moody", energy="high", bpm=140, key="F")
    traits = resolve_style_traits(ctx, provider=_FailProvider())
    assert traits["research_used"] is False
    assert "research_fallback" in traits


def test_web_research_applied_when_available():
    ctx = StyleContext(genre="house", mood="club", energy="high", bpm=126, key="G")
    traits = resolve_style_traits(ctx, provider=_GoodProvider())
    assert traits["research_used"] is True
    assert traits["transition_density"] == "high"
