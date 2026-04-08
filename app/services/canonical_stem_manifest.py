"""Canonical stem manifest — shared internal representation for all ingestion modes.

All three input modes (single audio file, multi-stem upload, ZIP stem pack) normalise
into this shared structure before downstream processing.

Canonical roles
---------------
Rich producer-friendly roles (Phase 2 taxonomy):
  Drums/Rhythm : kick, snare, clap, hi_hat, percussion, cymbals
  Low-end      : bass, 808
  Melodic      : piano, keys, guitar, pads, strings, synth, arp, melody
  Misc         : fx, vocal
  Broad fallback (backward-compatible): drums, harmony, vocals, accent, full_mix

Source types
------------
  uploaded_stem  — individual stem files uploaded by the user
  zip_stem       — stems extracted from a user-uploaded ZIP
  ai_separated   — stems produced by the AI separation pipeline
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Canonical role taxonomy
# ---------------------------------------------------------------------------

CANONICAL_ROLES: tuple[str, ...] = (
    # Drums / Rhythm
    "kick",
    "snare",
    "clap",
    "hi_hat",
    "percussion",
    "cymbals",
    # Low-end
    "bass",
    "808",
    # Melodic / Harmonic
    "piano",
    "keys",
    "guitar",
    "pads",
    "strings",
    "synth",
    "arp",
    "melody",
    # FX / Vocal
    "fx",
    "vocal",
    # Broad fallback (backward-compatible with existing pipeline)
    "drums",
    "harmony",
    "vocals",
    "accent",
    "full_mix",
)

# Mapping from canonical role → broad legacy role used by the existing pipeline
CANONICAL_TO_BROAD: dict[str, str] = {
    # Drums sub-roles → "drums"
    "kick":       "drums",
    "snare":      "drums",
    "clap":       "drums",
    "hi_hat":     "drums",
    "cymbals":    "drums",
    # Percussion keeps its own group
    "percussion": "percussion",
    # Low-end sub-roles → "bass"
    "bass":       "bass",
    "808":        "bass",
    # Melodic sub-roles
    "piano":      "melody",
    "keys":       "harmony",
    "guitar":     "melody",
    "pads":       "pads",
    "strings":    "harmony",
    "synth":      "melody",
    "arp":        "melody",
    "melody":     "melody",
    # FX / Vocal
    "fx":         "fx",
    "vocal":      "vocals",
    # Broad roles pass through unchanged
    "drums":      "drums",
    "harmony":    "harmony",
    "vocals":     "vocals",
    "accent":     "accent",
    "full_mix":   "full_mix",
}

# Arrangement groups for canonical roles (extends existing ARRANGEMENT_GROUPS)
CANONICAL_ARRANGEMENT_GROUPS: dict[str, str] = {
    "kick":       "rhythm",
    "snare":      "rhythm",
    "clap":       "rhythm",
    "hi_hat":     "rhythm",
    "cymbals":    "rhythm",
    "percussion": "rhythm",
    "drums":      "rhythm",
    "bass":       "low_end",
    "808":        "low_end",
    "piano":      "lead",
    "guitar":     "lead",
    "melody":     "lead",
    "vocals":     "lead",
    "vocal":      "lead",
    "keys":       "harmonic",
    "strings":    "harmonic",
    "harmony":    "harmonic",
    "pads":       "harmonic",
    "synth":      "lead",
    "arp":        "lead",
    "fx":         "texture",
    "accent":     "transition",
    "full_mix":   "fallback_mix",
}

# Source type constants
SOURCE_UPLOADED_STEM = "uploaded_stem"
SOURCE_ZIP_STEM = "zip_stem"
SOURCE_AI_SEPARATED = "ai_separated"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CanonicalStemEntry:
    """A single stem entry in the canonical manifest."""

    role: str
    """Rich canonical role (kick, snare, piano, 808, …)."""

    broad_role: str
    """Backward-compatible broad role used by the existing pipeline (drums, bass, melody, …)."""

    file_key: str
    """Storage key (S3 key or local path)."""

    confidence: float
    """Classification confidence in [0.0, 1.0]."""

    source_type: str
    """One of SOURCE_UPLOADED_STEM, SOURCE_ZIP_STEM, SOURCE_AI_SEPARATED."""

    fallback: bool = False
    """True when the role was assigned by graceful degradation rather than high-confidence match."""

    parent_broad_stem: str | None = None
    """The broad parent stem when a sub-role was isolated (e.g. 'drums' when role is 'kick')."""

    original_filename: str | None = None
    """Original uploaded filename, preserved for traceability."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalStemManifest:
    """Normalised output for all three ingestion modes.

    Consumers (arranger, render path) should use this object rather than
    mode-specific data structures.  All three paths produce this manifest
    as their final output.
    """

    stems: list[CanonicalStemEntry] = field(default_factory=list)
    source_mode: str = ""
    """'single_file' | 'multi_stem' | 'zip_stem'"""

    loop_id: int = 0

    @property
    def roles(self) -> list[str]:
        """Sorted list of unique canonical roles present in this manifest."""
        return sorted({e.role for e in self.stems})

    @property
    def broad_roles(self) -> list[str]:
        """Sorted list of unique broad (legacy) roles present in this manifest."""
        return sorted({e.broad_role for e in self.stems})

    def by_role(self, role: str) -> CanonicalStemEntry | None:
        """Return the first entry matching *role*, or None."""
        for entry in self.stems:
            if entry.role == role:
                return entry
        return None

    def by_broad_role(self, broad_role: str) -> list[CanonicalStemEntry]:
        """Return all entries whose broad_role matches *broad_role*."""
        return [e for e in self.stems if e.broad_role == broad_role]

    def stem_keys(self) -> dict[str, str]:
        """Return a mapping of broad_role → file_key (first entry per broad role)."""
        result: dict[str, str] = {}
        for entry in self.stems:
            if entry.broad_role not in result:
                result[entry.broad_role] = entry.file_key
        return result

    def stem_keys_by_canonical(self) -> dict[str, str]:
        """Return a mapping of canonical_role → file_key."""
        return {e.role: e.file_key for e in self.stems}

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_mode": self.source_mode,
            "loop_id": self.loop_id,
            "roles": self.roles,
            "broad_roles": self.broad_roles,
            "stems": [e.to_dict() for e in self.stems],
        }
