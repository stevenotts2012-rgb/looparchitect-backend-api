"""
Core data types for the Groove Engine.

The Groove Engine operates AFTER the Timeline Engine and Pattern Variation
Engine, and BEFORE final audio rendering.  It transforms mechanically correct
arrangements into musically believable, producer-like feels.

All types are pure Python dataclasses with no audio or I/O dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Safe microtiming bounds (milliseconds)
# ---------------------------------------------------------------------------

# Maximum safe offset for each instrument role to prevent flamming / broken rhythm.
_MAX_HAT_OFFSET_MS: float = 15.0
_MAX_SNARE_LAYBACK_MS: float = 12.0
_MAX_BASS_LAG_MS: float = 10.0
_MAX_KICK_OFFSET_MS: float = 6.0
_MAX_PERC_OFFSET_MS: float = 12.0


# ---------------------------------------------------------------------------
# GrooveEvent
# ---------------------------------------------------------------------------

@dataclass
class GrooveEvent:
    """A single groove instruction applied over a bar range within a section.

    Attributes:
        bar_start: 1-indexed bar where this groove event begins.
        bar_end: 1-indexed bar where this groove event ends (inclusive).
        role: Instrument role targeted (e.g. ``"drums"``, ``"bass"``).
        groove_type: Named groove action (e.g. ``"hat_push"``, ``"snare_layback"``).
        intensity: Strength in [0.0, 1.0].
        timing_offset_ms: Microtiming offset in milliseconds (negative = push ahead,
            positive = lag behind).  ``None`` means no explicit timing nudge.
        velocity_profile: Per-beat relative velocity adjustments.
        density_profile: Per-beat density modifiers.
        parameters: Arbitrary key/value pairs for downstream processors.
    """

    bar_start: int
    bar_end: int
    role: str
    groove_type: str
    intensity: float = 0.7
    timing_offset_ms: Optional[float] = None
    velocity_profile: Optional[Dict[str, float]] = None
    density_profile: Optional[Dict[str, float]] = None
    parameters: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.bar_start < 1:
            raise ValueError(f"bar_start must be >= 1, got {self.bar_start}")
        if self.bar_end < self.bar_start:
            raise ValueError(
                f"bar_end ({self.bar_end}) must be >= bar_start ({self.bar_start})"
            )
        if not self.role:
            raise ValueError("role must be a non-empty string")
        if not self.groove_type:
            raise ValueError("groove_type must be a non-empty string")
        self.intensity = max(0.0, min(1.0, float(self.intensity)))
        if self.timing_offset_ms is not None:
            self._validate_timing_offset()

    def _validate_timing_offset(self) -> None:
        """Raise ValueError if timing_offset_ms exceeds safe musical bounds."""
        offset = abs(self.timing_offset_ms)
        role_lower = self.role.lower()
        if "hat" in role_lower or "hi-hat" in role_lower or "hihat" in role_lower:
            limit = _MAX_HAT_OFFSET_MS
        elif "snare" in role_lower:
            limit = _MAX_SNARE_LAYBACK_MS
        elif "bass" in role_lower:
            limit = _MAX_BASS_LAG_MS
        elif "kick" in role_lower:
            limit = _MAX_KICK_OFFSET_MS
        elif "perc" in role_lower:
            limit = _MAX_PERC_OFFSET_MS
        else:
            limit = _MAX_HAT_OFFSET_MS
        if offset > limit:
            raise ValueError(
                f"timing_offset_ms={self.timing_offset_ms:.1f}ms exceeds safe limit "
                f"of ±{limit:.1f}ms for role '{self.role}'"
            )

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        d: dict = {
            "bar_start": self.bar_start,
            "bar_end": self.bar_end,
            "role": self.role,
            "groove_type": self.groove_type,
            "intensity": round(self.intensity, 4),
        }
        if self.timing_offset_ms is not None:
            d["timing_offset_ms"] = round(self.timing_offset_ms, 2)
        if self.velocity_profile is not None:
            d["velocity_profile"] = {k: round(v, 4) for k, v in self.velocity_profile.items()}
        if self.density_profile is not None:
            d["density_profile"] = {k: round(v, 4) for k, v in self.density_profile.items()}
        if self.parameters:
            d["parameters"] = dict(self.parameters)
        return d


# ---------------------------------------------------------------------------
# GrooveProfile
# ---------------------------------------------------------------------------

@dataclass
class GrooveProfile:
    """Defines the section-level groove feel for a named profile.

    Attributes:
        name: Unique profile name (e.g. ``"explosive_hook"``).
        swing_amount: Swing percentage [0.0, 1.0] (0.0 = straight, 1.0 = full swing).
        hat_push_ms: Hi-hat push in ms (negative = push ahead, positive = lag behind).
        snare_layback_ms: Snare layback in ms (>= 0, positive = behind the beat).
        kick_tightness: Kick tightness [0.0, 1.0] (1.0 = perfectly quantised).
        accent_density: Accent event density [0.0, 1.0].
        bass_lag_ms: Bass lag in ms (>= 0).
        section_bias: Primary section type this profile suits best.
        notes: Human-readable description of the groove character.
    """

    name: str
    swing_amount: float
    hat_push_ms: float
    snare_layback_ms: float
    kick_tightness: float
    accent_density: float
    bass_lag_ms: float
    section_bias: str
    notes: str = ""

    def __post_init__(self) -> None:
        self.swing_amount = max(0.0, min(1.0, float(self.swing_amount)))
        self.kick_tightness = max(0.0, min(1.0, float(self.kick_tightness)))
        self.accent_density = max(0.0, min(1.0, float(self.accent_density)))
        self.hat_push_ms = max(-_MAX_HAT_OFFSET_MS, min(_MAX_HAT_OFFSET_MS, float(self.hat_push_ms)))
        self.snare_layback_ms = max(0.0, min(_MAX_SNARE_LAYBACK_MS, float(self.snare_layback_ms)))
        self.bass_lag_ms = max(0.0, min(_MAX_BASS_LAG_MS, float(self.bass_lag_ms)))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "swing_amount": round(self.swing_amount, 4),
            "hat_push_ms": round(self.hat_push_ms, 2),
            "snare_layback_ms": round(self.snare_layback_ms, 2),
            "kick_tightness": round(self.kick_tightness, 4),
            "accent_density": round(self.accent_density, 4),
            "bass_lag_ms": round(self.bass_lag_ms, 2),
            "section_bias": self.section_bias,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# GrooveContext
# ---------------------------------------------------------------------------

@dataclass
class GrooveContext:
    """Input context consumed by the Groove Engine for one section.

    Attributes:
        section_name: Human-readable section label (e.g. ``"Hook 2"``).
        section_index: 0-based position in the full arrangement.
        section_occurrence_index: 0-based repetition counter within section type.
        total_occurrences: Total number of times this section type appears.
        bars: Bar count of this section.
        energy: Target energy level [0.0, 1.0].
        density: Target density level [0.0, 1.0].
        active_roles: Instrument roles active in this section.
        timeline_events: Raw event list from the Timeline Engine (may be empty).
        pattern_variations: Serialised pattern variation plans (may be empty).
        source_quality: Source quality mode string (default ``"true_stems"``).
        available_roles: All roles available in the source material.
    """

    section_name: str
    section_index: int
    section_occurrence_index: int
    total_occurrences: int
    bars: int
    energy: float
    density: float
    active_roles: List[str] = field(default_factory=list)
    timeline_events: List[Dict] = field(default_factory=list)
    pattern_variations: List[Dict] = field(default_factory=list)
    source_quality: str = "true_stems"
    available_roles: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.energy = max(0.0, min(1.0, float(self.energy)))
        self.density = max(0.0, min(1.0, float(self.density)))
        if self.bars < 1:
            raise ValueError(f"bars must be >= 1, got {self.bars}")
        if self.section_occurrence_index < 0:
            raise ValueError(
                f"section_occurrence_index must be >= 0, got {self.section_occurrence_index}"
            )
        if self.total_occurrences < 1:
            raise ValueError(
                f"total_occurrences must be >= 1, got {self.total_occurrences}"
            )

    @property
    def section_type(self) -> str:
        """Derive canonical section type from section_name."""
        name = self.section_name.lower().strip()
        for token in ("pre_hook", "pre-hook", "prehook", "buildup", "build"):
            if token in name:
                return "pre_hook"
        for token in ("hook", "chorus", "drop"):
            if token in name:
                return "hook"
        for token in ("verse",):
            if token in name:
                return "verse"
        for token in ("bridge",):
            if token in name:
                return "bridge"
        for token in ("breakdown", "break"):
            if token in name:
                return "breakdown"
        for token in ("intro",):
            if token in name:
                return "intro"
        for token in ("outro",):
            if token in name:
                return "outro"
        return "verse"

    @property
    def occurrence(self) -> int:
        """Return 1-based occurrence index."""
        return self.section_occurrence_index + 1


# ---------------------------------------------------------------------------
# GroovePlan
# ---------------------------------------------------------------------------

@dataclass
class GroovePlan:
    """Groove plan generated by the Groove Engine for one section.

    Attributes:
        section_name: Human-readable section label.
        groove_profile_name: Name of the selected :class:`GrooveProfile`.
        groove_events: Ordered list of :class:`GrooveEvent` objects.
        groove_intensity: Overall groove intensity for this section [0.0, 1.0].
        bounce_score: Computed bounce / feel quality score [0.0, 1.0].
        applied_heuristics: Human-readable list of heuristics applied.
    """

    section_name: str
    groove_profile_name: str
    groove_events: List[GrooveEvent] = field(default_factory=list)
    groove_intensity: float = 0.5
    bounce_score: float = 0.0
    applied_heuristics: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.groove_intensity = max(0.0, min(1.0, float(self.groove_intensity)))
        self.bounce_score = max(0.0, min(1.0, float(self.bounce_score)))

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "section_name": self.section_name,
            "groove_profile_name": self.groove_profile_name,
            "groove_intensity": round(self.groove_intensity, 4),
            "bounce_score": round(self.bounce_score, 4),
            "applied_heuristics": list(self.applied_heuristics),
            "groove_events": [e.to_dict() for e in self.groove_events],
        }
