"""
Core data types for the Generative Producer System.

All fields are plain Python types so they serialise cleanly to JSON.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Supported genres
# ---------------------------------------------------------------------------

SUPPORTED_GENRES: frozenset[str] = frozenset(
    {"trap", "drill", "rnb", "rage", "west_coast", "generic"}
)

# ---------------------------------------------------------------------------
# Supported render actions (must stay in sync with renderer_mapping.py)
# ---------------------------------------------------------------------------

SUPPORTED_RENDER_ACTIONS: frozenset[str] = frozenset(
    {
        "mute_role",
        "unmute_role",
        "filter_role",
        "chop_role",
        "reverse_slice",
        "add_hat_roll",
        "add_drum_fill",
        "bass_pattern_variation",
        "add_fx_riser",
        "add_impact",
        "fade_role",
        "widen_role",
        "delay_role",
        "reverb_tail",
    }
)

# ---------------------------------------------------------------------------
# ProducerEvent
# ---------------------------------------------------------------------------


@dataclass
class ProducerEvent:
    """A single audio-actionable producer decision for a section window."""

    event_id: str
    section_name: str
    occurrence_index: int
    bar_start: int
    bar_end: int
    target_role: str
    event_type: str
    intensity: float  # 0.0 – 1.0
    parameters: dict[str, Any]
    render_action: str
    reason: str

    @classmethod
    def make(
        cls,
        *,
        section_name: str,
        occurrence_index: int,
        bar_start: int,
        bar_end: int,
        target_role: str,
        event_type: str,
        intensity: float,
        parameters: dict[str, Any] | None = None,
        render_action: str,
        reason: str,
    ) -> "ProducerEvent":
        return cls(
            event_id=str(uuid.uuid4()),
            section_name=section_name,
            occurrence_index=occurrence_index,
            bar_start=bar_start,
            bar_end=bar_end,
            target_role=target_role,
            event_type=event_type,
            intensity=float(intensity),
            parameters=parameters or {},
            render_action=render_action,
            reason=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "section_name": self.section_name,
            "occurrence_index": self.occurrence_index,
            "bar_start": self.bar_start,
            "bar_end": self.bar_end,
            "target_role": self.target_role,
            "event_type": self.event_type,
            "intensity": self.intensity,
            "parameters": self.parameters,
            "render_action": self.render_action,
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# SkippedEvent
# ---------------------------------------------------------------------------


@dataclass
class SkippedEvent:
    """An event that could not be mapped to a supported render action."""

    event_id: str
    section_name: str
    event_type: str
    skipped_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "section_name": self.section_name,
            "event_type": self.event_type,
            "skipped_reason": self.skipped_reason,
        }


# ---------------------------------------------------------------------------
# GenreProducerProfile
# ---------------------------------------------------------------------------


@dataclass
class GenreProducerProfile:
    """Behaviour contract for a specific genre."""

    genre: str
    section_behaviors: dict[str, dict[str, Any]]
    energy_curve_policy: str
    drum_policy: str
    bass_policy: str
    melody_policy: str
    fx_policy: str
    variation_policy: str

    def behavior_for(self, section_name: str) -> dict[str, Any]:
        """Return section behavior, falling back to verse if not found."""
        name = section_name.lower()
        return self.section_behaviors.get(name, self.section_behaviors.get("verse", {}))


# ---------------------------------------------------------------------------
# ProducerPlan
# ---------------------------------------------------------------------------


@dataclass
class ProducerPlan:
    """The complete output of the Generative Producer System for one arrangement."""

    genre: str
    vibe: str
    seed: int
    events: list[ProducerEvent] = field(default_factory=list)
    section_variation_score: float = 0.0
    event_count_per_section: dict[str, int] = field(default_factory=dict)
    skipped_events: list[SkippedEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "genre": self.genre,
            "vibe": self.vibe,
            "seed": self.seed,
            "events": [e.to_dict() for e in self.events],
            "section_variation_score": self.section_variation_score,
            "event_count_per_section": self.event_count_per_section,
            "skipped_events": [s.to_dict() for s in self.skipped_events],
            "warnings": self.warnings,
        }
