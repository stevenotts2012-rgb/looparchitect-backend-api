"""
Motif Extractor — identifies the best motif source from available roles.

The extractor inspects available melodic/harmonic roles and returns the
strongest candidate :class:`~app.services.motif_engine.types.Motif`, or
``None`` when no viable source exists.

This pass is structural.  No deep audio transcription is performed — the
extractor uses role availability, metadata, and source quality to choose
a motif source conservatively.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.motif_engine.types import Motif

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role-to-motif-type preference tables
# ---------------------------------------------------------------------------

# Ordered preference: (role_token, motif_type, confidence_weight)
# The first matching role in available_roles wins.
_ROLE_PREFERENCE: List[tuple] = [
    # Melody / lead roles — strongest source for a lead_phrase motif.
    ("melody", "lead_phrase", 1.00),
    ("lead", "lead_phrase", 0.95),
    ("vocal", "lead_phrase", 0.90),
    ("synth_lead", "lead_phrase", 0.85),
    ("pluck", "lead_phrase", 0.80),
    # Synth / instrument — can serve as counter_phrase.
    ("synth", "counter_phrase", 0.70),
    ("keys", "counter_phrase", 0.70),
    ("piano", "counter_phrase", 0.70),
    ("guitar", "counter_phrase", 0.65),
    # Chord / harmony roles.
    ("chords", "chord_shape", 0.65),
    ("harmony", "chord_shape", 0.60),
    ("pads", "chord_shape", 0.55),
    ("strings", "chord_shape", 0.55),
    # Arp / melodic pattern roles.
    ("arp", "arp_fragment", 0.60),
    ("sequence", "arp_fragment", 0.55),
    ("mallet", "arp_fragment", 0.55),
    # Texture / atmosphere — weakest, last resort.
    ("texture", "texture_motif", 0.35),
    ("atmosphere", "texture_motif", 0.35),
    ("fx", "texture_motif", 0.25),
    ("noise", "texture_motif", 0.20),
    ("ambient", "texture_motif", 0.25),
]

# Source-quality confidence multipliers.
_SOURCE_QUALITY_MULTIPLIERS: Dict[str, float] = {
    "true_stems": 1.00,
    "zip_stems": 0.90,
    "ai_separated": 0.65,
    "stereo_fallback": 0.30,
}

# Minimum confidence to consider a motif viable (not a fallback).
_MIN_VIABLE_CONFIDENCE: float = 0.25


def _match_role(role: str, token: str) -> bool:
    """Return True when *token* appears anywhere in *role* (case-insensitive)."""
    return token in role.lower()


class MotifExtractor:
    """Identify the best motif source from available instrument roles.

    Parameters
    ----------
    source_quality:
        Source quality mode string (e.g. ``"true_stems"``,
        ``"ai_separated"``, ``"stereo_fallback"``).
    available_roles:
        Instrument roles present in the source material.

    Usage::

        extractor = MotifExtractor(source_quality="true_stems", available_roles=["melody", "bass"])
        motif = extractor.extract()  # returns Motif or None
    """

    def __init__(
        self,
        source_quality: str = "stereo_fallback",
        available_roles: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.source_quality = source_quality
        self.available_roles: List[str] = list(available_roles or [])
        self.context: Dict[str, Any] = context or {}

    def extract(self) -> Optional[Motif]:
        """Attempt to extract a core motif from available roles.

        Returns
        -------
        Motif or None
            A :class:`~app.services.motif_engine.types.Motif` when a viable
            source is found; ``None`` when no suitable role exists.
        """
        quality_multiplier = _SOURCE_QUALITY_MULTIPLIERS.get(
            self.source_quality, 0.30
        )

        # stereo_fallback with no roles: no motif possible.
        if self.source_quality == "stereo_fallback" and not self.available_roles:
            logger.debug(
                "MotifExtractor: stereo_fallback with no roles — returning None"
            )
            return None

        best_role: Optional[str] = None
        best_motif_type: Optional[str] = None
        best_confidence: float = 0.0

        for pref_token, motif_type, base_confidence in _ROLE_PREFERENCE:
            for role in self.available_roles:
                if _match_role(role, pref_token):
                    adjusted = base_confidence * quality_multiplier
                    if adjusted > best_confidence:
                        best_confidence = adjusted
                        best_role = role
                        best_motif_type = motif_type

        if best_role is None or best_confidence < _MIN_VIABLE_CONFIDENCE:
            logger.debug(
                "MotifExtractor: no viable motif source found "
                "(best_confidence=%.3f, threshold=%.3f)",
                best_confidence,
                _MIN_VIABLE_CONFIDENCE,
            )
            return None

        # Conservative bar count: prefer 2 bars (structurally safe).
        bars = self.context.get("motif_bars") or 2

        motif = Motif(
            motif_id=f"motif_{best_role}_{best_motif_type}",
            source_role=best_role,
            motif_type=best_motif_type,
            confidence=best_confidence,
            bars=int(bars),
            notes=(
                f"Extracted from '{best_role}' "
                f"(quality={self.source_quality}, "
                f"confidence={best_confidence:.2f})"
            ),
        )

        logger.debug(
            "MotifExtractor: extracted motif — role=%s type=%s confidence=%.3f",
            best_role,
            best_motif_type,
            best_confidence,
        )
        return motif
