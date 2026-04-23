"""Genre and vibe classifier for LoopArchitect.

Classifies a loop analysis object into a top-level genre + vibe profile
using deterministic rule-based logic. No ML training required.

Supported genres: trap, drill, rage, rnb, west_coast, generic
Supported vibes: dark, emotional, hype, ambient, rage, cinematic, smooth
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_KNOWN_GENRES = frozenset({"trap", "drill", "rage", "rnb", "west_coast", "generic"})
_KNOWN_VIBES = frozenset({"dark", "emotional", "hype", "ambient", "rage", "cinematic", "smooth"})

_CONFIDENCE_CAP = 0.95


class GenreVibeClassifier:
    """Deterministic rule-based genre and vibe classifier.

    No ML training or external dependencies required.  All classification
    is performed from the input ``analysis`` dict using explicit threshold
    rules applied in priority order.
    """

    def classify(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """Classify a loop analysis dict into genre, vibe, and style profile.

        Parameters
        ----------
        analysis:
            Loop analysis dict that may contain keys: ``bpm``, ``key``,
            ``genre_hint``, ``vibe_hint``, ``energy``, ``melodic_richness``,
            ``loop_density``, ``instrument_tags``, ``inferred_genre_probs``,
            ``inferred_vibe_probs``.

        Returns
        -------
        dict
            Keys: ``selected_genre``, ``selected_vibe``, ``genre_confidence``,
            ``vibe_confidence``, ``style_profile``.
        """
        bpm: float = float(analysis.get("bpm") or 120.0)
        energy: float = float(analysis.get("energy") or 0.5)
        melodic_richness: float = float(analysis.get("melodic_richness") or 0.5)
        loop_density: float = float(analysis.get("loop_density") or 0.5)
        genre_hint: str = str(analysis.get("genre_hint") or "").strip().lower()
        vibe_hint: str = str(analysis.get("vibe_hint") or "").strip().lower()
        tags: list[str] = [str(t).lower() for t in (analysis.get("instrument_tags") or [])]
        inferred_genre_probs: dict[str, float] = dict(analysis.get("inferred_genre_probs") or {})
        inferred_vibe_probs: dict[str, float] = dict(analysis.get("inferred_vibe_probs") or {})

        genre, genre_confidence = self._classify_genre(
            bpm, tags, genre_hint, inferred_genre_probs
        )
        vibe, vibe_confidence = self._classify_vibe(
            bpm, energy, loop_density, melodic_richness, tags, vibe_hint,
            genre, inferred_vibe_probs
        )

        density_label = (
            "sparse" if loop_density < 0.4
            else "dense" if loop_density > 0.7
            else "balanced"
        )
        style_profile = f"{genre}_{vibe}_{density_label}"

        return {
            "selected_genre": genre,
            "selected_vibe": vibe,
            "genre_confidence": round(min(genre_confidence, _CONFIDENCE_CAP), 4),
            "vibe_confidence": round(min(vibe_confidence, _CONFIDENCE_CAP), 4),
            "style_profile": style_profile,
        }

    # ------------------------------------------------------------------
    # Genre classification
    # ------------------------------------------------------------------

    def _classify_genre(
        self,
        bpm: float,
        tags: list[str],
        genre_hint: str,
        inferred_probs: dict[str, float],
    ) -> tuple[str, float]:
        """Return (genre, confidence) using explicit priority rules."""
        # Highest priority: exact genre hint
        if genre_hint and genre_hint in _KNOWN_GENRES:
            return genre_hint, 0.9

        # BPM + tag rules
        if "drill" in tags and 135 <= bpm <= 150:
            return "drill", 0.85

        if "rage" in tags and 140 <= bpm <= 170:
            return "rage", 0.85

        if ("808" in tags or "trap" in tags) and 130 <= bpm <= 160:
            return "trap", 0.82

        if "rnb" in tags or "r&b" in tags or 65 <= bpm <= 100:
            return "rnb", 0.78

        # Fall back to inferred probabilities from metadata analyzer
        if inferred_probs:
            best_genre = max(inferred_probs, key=lambda k: inferred_probs[k])
            if best_genre in _KNOWN_GENRES:
                return best_genre, min(inferred_probs[best_genre], _CONFIDENCE_CAP)

        # Default: trap (most supported genre)
        return "trap", 0.55

    # ------------------------------------------------------------------
    # Vibe classification
    # ------------------------------------------------------------------

    def _classify_vibe(
        self,
        bpm: float,
        energy: float,
        loop_density: float,
        melodic_richness: float,
        tags: list[str],
        vibe_hint: str,
        genre: str,
        inferred_probs: dict[str, float],
    ) -> tuple[str, float]:
        """Return (vibe, confidence) using explicit priority rules."""
        # Highest priority: vibe hint
        if vibe_hint and vibe_hint in _KNOWN_VIBES:
            return vibe_hint, 0.9

        # Rule-based vibe detection (checked in priority order)
        if "dark" in tags or energy < 0.5:
            return "dark", 0.80

        if "piano" in tags or "sad" in tags or "emotional" in tags:
            return "emotional", 0.80

        if energy > 0.8:
            return "hype", 0.82

        if loop_density < 0.3:
            return "ambient", 0.78

        if bpm > 155:
            return "rage", 0.78

        if "cinematic" in tags:
            return "cinematic", 0.75

        if genre == "rnb":
            return "smooth", 0.75

        # Fall back to inferred probabilities
        if inferred_probs:
            best_vibe = max(inferred_probs, key=lambda k: inferred_probs[k])
            if best_vibe in _KNOWN_VIBES:
                return best_vibe, min(inferred_probs[best_vibe], _CONFIDENCE_CAP)

        # Default: dark
        return "dark", 0.55
