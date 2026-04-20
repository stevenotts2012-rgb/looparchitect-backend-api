"""
Core data types for the Drop Engine.

The Drop Engine operates AFTER the Timeline Engine, Pattern Variation Engine,
Groove Engine, and AI Producer System, and BEFORE live rendering.  It designs
intentional drops — pre-hook tension, fakeouts, delayed entries, re-entry
accents, and payoff moments — so that hook entries feel produced rather than
mechanical.

All types are pure Python dataclasses with no audio or I/O dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Supported drop event types
# ---------------------------------------------------------------------------

SUPPORTED_DROP_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "pre_drop_silence",
        "kick_fakeout",
        "bass_dropout",
        "riser_build",
        "reverse_fx_entry",
        "re_entry_accent",
        "staggered_reentry",
        "crash_hit",
        "delayed_drop",
        "filtered_pre_drop",
        "snare_pickup",
        "silence_tease",
    }
)

# Event types that count as "strong" — at most one strong primary per boundary.
STRONG_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "pre_drop_silence",
        "bass_dropout",
        "kick_fakeout",
        "delayed_drop",
        "silence_tease",
    }
)

# Valid placement values for a DropEvent.
VALID_PLACEMENTS: frozenset[str] = frozenset(
    {"pre_boundary", "boundary", "post_boundary"}
)


# ---------------------------------------------------------------------------
# DropEvent
# ---------------------------------------------------------------------------


@dataclass
class DropEvent:
    """A single drop design event at or near a section boundary.

    Attributes:
        boundary_name: Human-readable label for the boundary
            (e.g. ``"pre_hook_1 -> hook_1"``).
        from_section: Canonical section type the arrangement is leaving
            (e.g. ``"pre_hook"``).
        to_section: Canonical section type the arrangement is entering
            (e.g. ``"hook"``).
        placement: Where relative to the boundary this event occurs.
            Must be one of ``pre_boundary``, ``boundary``, ``post_boundary``.
        event_type: Named event behaviour.  Must be in
            :data:`SUPPORTED_DROP_EVENT_TYPES`.
        intensity: Strength of the event in [0.0, 1.0].
        parameters: Arbitrary key/value pairs for downstream processors.
        notes: Optional human-readable annotation.
    """

    boundary_name: str
    from_section: str
    to_section: str
    placement: str
    event_type: str
    intensity: float = 0.7
    parameters: Dict[str, Any] = field(default_factory=dict)
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.boundary_name:
            raise ValueError("boundary_name must be a non-empty string")
        if not self.from_section:
            raise ValueError("from_section must be a non-empty string")
        if not self.to_section:
            raise ValueError("to_section must be a non-empty string")
        if self.placement not in VALID_PLACEMENTS:
            raise ValueError(
                f"placement must be one of {sorted(VALID_PLACEMENTS)}, "
                f"got {self.placement!r}"
            )
        if self.event_type not in SUPPORTED_DROP_EVENT_TYPES:
            raise ValueError(
                f"event_type must be one of {sorted(SUPPORTED_DROP_EVENT_TYPES)}, "
                f"got {self.event_type!r}"
            )
        self.intensity = max(0.0, min(1.0, float(self.intensity)))

    @property
    def is_strong(self) -> bool:
        """Return True when this event type is classified as strong."""
        return self.event_type in STRONG_EVENT_TYPES

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        d: dict = {
            "boundary_name": self.boundary_name,
            "from_section": self.from_section,
            "to_section": self.to_section,
            "placement": self.placement,
            "event_type": self.event_type,
            "intensity": round(self.intensity, 4),
            "parameters": dict(self.parameters),
        }
        if self.notes is not None:
            d["notes"] = self.notes
        return d


# ---------------------------------------------------------------------------
# DropBoundaryPlan
# ---------------------------------------------------------------------------


@dataclass
class DropBoundaryPlan:
    """Drop design plan for a single section boundary.

    Attributes:
        from_section: Canonical section type being left.
        to_section: Canonical section type being entered.
        occurrence_index: 0-based counter for how many times this exact
            boundary type (from→to) has appeared before in the arrangement.
        tension_score: Computed tension quality score [0.0, 1.0].
        payoff_score: Computed payoff quality score [0.0, 1.0].
        primary_drop_event: The single primary :class:`DropEvent` for this
            boundary, or ``None`` when no strong event is warranted.
        support_events: Additional lighter :class:`DropEvent` objects that
            complement the primary event.
        notes: Human-readable planning notes for this boundary.
    """

    from_section: str
    to_section: str
    occurrence_index: int = 0
    tension_score: float = 0.0
    payoff_score: float = 0.0
    primary_drop_event: Optional[DropEvent] = None
    support_events: List[DropEvent] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tension_score = max(0.0, min(1.0, float(self.tension_score)))
        self.payoff_score = max(0.0, min(1.0, float(self.payoff_score)))
        if self.occurrence_index < 0:
            raise ValueError(
                f"occurrence_index must be >= 0, got {self.occurrence_index}"
            )

    @property
    def boundary_name(self) -> str:
        """Derive a canonical boundary label."""
        suffix = f"_{self.occurrence_index + 1}" if self.occurrence_index > 0 else ""
        return f"{self.from_section} -> {self.to_section}{suffix}"

    @property
    def all_events(self) -> List[DropEvent]:
        """Return all events (primary + support) in order."""
        events: List[DropEvent] = []
        if self.primary_drop_event is not None:
            events.append(self.primary_drop_event)
        events.extend(self.support_events)
        return events

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "boundary_name": self.boundary_name,
            "from_section": self.from_section,
            "to_section": self.to_section,
            "occurrence_index": self.occurrence_index,
            "tension_score": round(self.tension_score, 4),
            "payoff_score": round(self.payoff_score, 4),
            "primary_drop_event": (
                self.primary_drop_event.to_dict()
                if self.primary_drop_event is not None
                else None
            ),
            "support_events": [e.to_dict() for e in self.support_events],
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# DropPlan
# ---------------------------------------------------------------------------


@dataclass
class DropPlan:
    """Full drop design plan for a complete arrangement.

    Attributes:
        boundaries: Ordered list of :class:`DropBoundaryPlan` objects, one
            per meaningful section boundary.
        total_drop_count: Number of boundaries that received a primary event.
        repeated_hook_drop_variation_score: Aggregate score measuring how
            much hook entries vary across repetitions [0.0, 1.0].
        fallback_used: ``True`` when the planner fell back to simpler
            treatment due to weak source material.
    """

    boundaries: List[DropBoundaryPlan] = field(default_factory=list)
    total_drop_count: int = 0
    repeated_hook_drop_variation_score: float = 0.0
    fallback_used: bool = False

    def __post_init__(self) -> None:
        self.repeated_hook_drop_variation_score = max(
            0.0, min(1.0, float(self.repeated_hook_drop_variation_score))
        )

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "total_drop_count": self.total_drop_count,
            "repeated_hook_drop_variation_score": round(
                self.repeated_hook_drop_variation_score, 4
            ),
            "fallback_used": self.fallback_used,
            "boundaries": [b.to_dict() for b in self.boundaries],
        }
