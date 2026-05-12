from __future__ import annotations

import logging

from .genre_rules import derive_genre_traits
from .style_context import StyleContext
from .style_prompt_interpreter import interpret_style_prompt
from .vibe_rules import derive_vibe_traits


class StyleResearchProvider:
    def research_genre_traits(self, style_query: str) -> dict:
        # Architecture hook: no web dependency required for success.
        raise RuntimeError("external research provider not configured")

    def summarize_style_traits(self) -> dict:
        return {"source": "fallback", "copyright_safe": True}


def resolve_style_traits(ctx: StyleContext, provider: StyleResearchProvider | None = None) -> dict:
    base = {}
    base.update(derive_genre_traits(ctx.genre, ctx.bpm))
    base.update(derive_vibe_traits(ctx.mood, ctx.energy))
    prompt_traits = interpret_style_prompt(ctx)
    if prompt_traits:
        base.update(prompt_traits)

    if provider:
        try:
            logger.info("STYLE_RESEARCH_REQUESTED")
            research = provider.research_genre_traits(ctx.style_prompt or ctx.genre)
            base.update(research)
            base["research_used"] = True
            logger.info("STYLE_RESEARCH_TRAITS_APPLIED")
        except Exception:
            base["research_used"] = False
            base["research_fallback"] = provider.summarize_style_traits()
            logger.info("STYLE_RESEARCH_FALLBACK_USED")
    return base
logger = logging.getLogger(__name__)
