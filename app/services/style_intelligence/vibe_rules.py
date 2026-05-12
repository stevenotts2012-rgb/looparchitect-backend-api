from __future__ import annotations


def derive_vibe_traits(mood: str, energy: str) -> dict:
    m = (mood or "").lower()
    e = (energy or "medium").lower()
    return {
        "melody_density": "high" if any(t in m for t in ("emotional", "soulful", "melodic")) else "medium",
        "section_pacing": "wide" if e in {"low", "smooth", "chill"} else "tight",
        "transition_density": "high" if e in {"high", "hype", "energetic"} else "medium",
    }
