from __future__ import annotations

from .style_context import StyleContext


def interpret_style_prompt(ctx: StyleContext) -> dict:
    text = (ctx.style_prompt or "").strip().lower()
    if not text:
        return {}
    # broad-trait only, never direct song/recording copying
    traits = {
        "melody_density": "medium",
        "transition_density": "medium",
        "mood_vocab": [ctx.mood or "balanced"],
        "copyright_safe": True,
    }
    if "dark" in text:
        traits["mood_vocab"].append("dark")
    if "smooth" in text or "late-night" in text:
        traits["melody_density"] = "high"
    if "club" in text or "bounce" in text:
        traits["transition_density"] = "high"
    return traits
