from __future__ import annotations

from typing import Dict


class StyleReferenceProvider:
    """Future hook for broad style research traits without copying works."""

    def get_traits(self, genre: str, mood: str | None = None) -> Dict[str, str]:
        return {
            "common_tempo_range": "90-140 bpm",
            "common_drum_pocket": "genre-appropriate groove with pocket over complexity",
            "melody_density": "moderate, motif-led",
            "bass_movement": "supports rhythm and hook",
            "transition_style": "tasteful fills and risers, avoid overuse",
            "section_pacing": "clear contrast between sections",
        }
