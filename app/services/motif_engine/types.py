"""
Core data types for the Motif Engine.

The Motif Engine operates AFTER the Timeline Engine, Pattern Variation Engine,
Groove Engine, AI Producer System, and Drop Engine, and BEFORE live rendering.
It gives arrangements identity and cohesion by extracting or defining a core
motif and reusing it across sections in controlled variations so the track
feels like one song, not disconnected parts.

All types are pure Python dataclasses with no audio or I/O dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Supported motif type identifiers
# ---------------------------------------------------------------------------

SUPPORTED_MOTIF_TYPES: frozenset[str] = frozenset(
    {
        "lead_phrase",
        "counter_phrase",
        "chord_shape",
        "arp_fragment",
        "texture_motif",
    }
)

# Supported transformation type identifiers.
SUPPORTED_TRANSFORMATION_TYPES: frozenset[str] = frozenset(
    {
        "simplify",
        "delay_entry",
        "octave_lift",
        "sparse_phrase",
        "full_phrase",
        "call_response",
        "texture_only",
        "counter_variant",
        "rhythm_trim",
        "sustain_expand",
    }
)

# Transformation types considered "strong" — full motif statement.
STRONG_TRANSFORMATION_TYPES: frozenset[str] = frozenset(
    {
        "full_phrase",
        "octave_lift",
        "call_response",
        "sustain_expand",
    }
)

# Transformation types considered "weak" — reduced / tease motif.
WEAK_TRANSFORMATION_TYPES: frozenset[str] = frozenset(
    {
        "texture_only",
        "sparse_phrase",
        "delay_entry",
        "rhythm_trim",
        "simplify",
    }
)


# ---------------------------------------------------------------------------
# Motif
# ---------------------------------------------------------------------------


@dataclass
class Motif:
    """A core melodic or harmonic identity extracted from source material.

    Attributes:
        motif_id: Unique identifier for this motif.
        source_role: The instrument role the motif is sourced from
            (e.g. ``"melody"``, ``"chords"``).
        motif_type: Type classification.  Must be in
            :data:`SUPPORTED_MOTIF_TYPES`.
        confidence: Extraction confidence in [0.0, 1.0].  Higher means the
            source role clearly provides usable motif material.
        bars: Length of the motif in bars (1–8 typical).
        notes: Optional human-readable annotation.
    """

    motif_id: str
    source_role: str
    motif_type: str
    confidence: float
    bars: int
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.motif_id:
            raise ValueError("motif_id must be a non-empty string")
        if not self.source_role:
            raise ValueError("source_role must be a non-empty string")
        if self.motif_type not in SUPPORTED_MOTIF_TYPES:
            raise ValueError(
                f"motif_type must be one of {sorted(SUPPORTED_MOTIF_TYPES)}, "
                f"got {self.motif_type!r}"
            )
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if self.bars < 1:
            raise ValueError(f"bars must be >= 1, got {self.bars}")

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        d: dict = {
            "motif_id": self.motif_id,
            "source_role": self.source_role,
            "motif_type": self.motif_type,
            "confidence": round(self.confidence, 4),
            "bars": self.bars,
        }
        if self.notes is not None:
            d["notes"] = self.notes
        return d


# ---------------------------------------------------------------------------
# MotifTransformation
# ---------------------------------------------------------------------------


@dataclass
class MotifTransformation:
    """A single deterministic transformation applied to a motif occurrence.

    Attributes:
        transformation_type: Named transformation.  Must be in
            :data:`SUPPORTED_TRANSFORMATION_TYPES`.
        intensity: Strength of the transformation in [0.0, 1.0].
        parameters: Arbitrary key/value hints for downstream processors.
        notes: Optional human-readable annotation.
    """

    transformation_type: str
    intensity: float = 0.7
    parameters: Dict[str, Any] = field(default_factory=dict)
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if self.transformation_type not in SUPPORTED_TRANSFORMATION_TYPES:
            raise ValueError(
                f"transformation_type must be one of "
                f"{sorted(SUPPORTED_TRANSFORMATION_TYPES)}, "
                f"got {self.transformation_type!r}"
            )
        self.intensity = max(0.0, min(1.0, float(self.intensity)))

    @property
    def is_strong(self) -> bool:
        """Return True when this transformation counts as a strong statement."""
        return self.transformation_type in STRONG_TRANSFORMATION_TYPES

    @property
    def is_weak(self) -> bool:
        """Return True when this transformation counts as a reduced/tease."""
        return self.transformation_type in WEAK_TRANSFORMATION_TYPES

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        d: dict = {
            "transformation_type": self.transformation_type,
            "intensity": round(self.intensity, 4),
            "parameters": dict(self.parameters),
        }
        if self.notes is not None:
            d["notes"] = self.notes
        return d


# ---------------------------------------------------------------------------
# MotifOccurrence
# ---------------------------------------------------------------------------


@dataclass
class MotifOccurrence:
    """A single occurrence of the motif in a specific section.

    Attributes:
        section_name: Name of the section where this occurrence appears
            (e.g. ``"hook_1"``).
        occurrence_index: 0-based index of how many times this section type
            has received a motif occurrence before.
        source_role: Instrument role the motif is drawn from.
        transformations: Ordered list of transformations applied for this
            occurrence.
        target_intensity: Overall intensity level for this occurrence [0.0, 1.0].
        notes: Optional human-readable annotation.
    """

    section_name: str
    occurrence_index: int
    source_role: str
    transformations: List[MotifTransformation] = field(default_factory=list)
    target_intensity: float = 0.7
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.section_name:
            raise ValueError("section_name must be a non-empty string")
        if self.occurrence_index < 0:
            raise ValueError(
                f"occurrence_index must be >= 0, got {self.occurrence_index}"
            )
        self.target_intensity = max(0.0, min(1.0, float(self.target_intensity)))

    @property
    def transformation_types(self) -> List[str]:
        """Return the transformation type strings for this occurrence."""
        return [t.transformation_type for t in self.transformations]

    @property
    def is_strong(self) -> bool:
        """Return True when at least one transformation is strong."""
        return any(t.is_strong for t in self.transformations)

    @property
    def is_weak(self) -> bool:
        """Return True when all transformations are weak (or list is empty)."""
        if not self.transformations:
            return True
        return all(t.is_weak for t in self.transformations)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        d: dict = {
            "section_name": self.section_name,
            "occurrence_index": self.occurrence_index,
            "source_role": self.source_role,
            "transformations": [t.to_dict() for t in self.transformations],
            "target_intensity": round(self.target_intensity, 4),
        }
        if self.notes is not None:
            d["notes"] = self.notes
        return d


# ---------------------------------------------------------------------------
# MotifPlan
# ---------------------------------------------------------------------------


@dataclass
class MotifPlan:
    """Full motif reuse plan for a complete arrangement.

    Attributes:
        motif: The core :class:`Motif` extracted from source material, or
            ``None`` when no viable motif could be identified.
        occurrences: Ordered list of :class:`MotifOccurrence` objects — one
            per section that receives a motif treatment.
        motif_reuse_score: How well the motif is reused across sections [0.0, 1.0].
        motif_variation_score: How well the motif is varied across sections
            [0.0, 1.0].
        fallback_used: ``True`` when the engine fell back to conservative
            behaviour due to weak or missing source material.
    """

    motif: Optional[Motif] = None
    occurrences: List[MotifOccurrence] = field(default_factory=list)
    motif_reuse_score: float = 0.0
    motif_variation_score: float = 0.0
    fallback_used: bool = False

    def __post_init__(self) -> None:
        self.motif_reuse_score = max(0.0, min(1.0, float(self.motif_reuse_score)))
        self.motif_variation_score = max(
            0.0, min(1.0, float(self.motif_variation_score))
        )

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "motif": self.motif.to_dict() if self.motif is not None else None,
            "occurrences": [o.to_dict() for o in self.occurrences],
            "motif_reuse_score": round(self.motif_reuse_score, 4),
            "motif_variation_score": round(self.motif_variation_score, 4),
            "fallback_used": self.fallback_used,
        }
