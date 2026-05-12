from __future__ import annotations


def derive_genre_traits(genre: str, bpm: float) -> dict:
    g = (genre or "generic").lower()
    return {
        "tempo_range": (max(60, int(bpm - 15)), min(180, int(bpm + 15))),
        "drum_feel": "driving" if any(t in g for t in ("club", "edm", "dance", "trap")) else "balanced",
        "bass_behavior": "sub-forward" if "trap" in g else "supportive",
        "common_energy_curve": "aggressive" if "club" in g else "smooth",
    }
