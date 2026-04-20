"""
Core data types for the Pattern Variation Engine.

Pattern variation operates *inside* a section — adding rhythmic and melodic
movement so arrangements feel produced rather than just section-swapped.

All types are pure Python dataclasses with no audio or I/O dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Pattern actions
# ---------------------------------------------------------------------------

class PatternAction(str, Enum):
    """All named pattern-level actions the engine can emit."""

    # Drum actions
    DROP_KICK = "drop_kick"
    ADD_SYNCOPATED_KICK = "add_syncopated_kick"
    SNARE_FILL = "snare_fill"
    HAT_DENSITY_UP = "hat_density_up"
    HAT_DENSITY_DOWN = "hat_density_down"
    PERC_FILL = "perc_fill"
    HALF_TIME_SWITCH = "half_time_switch"
    PRE_DROP_SILENCE = "pre_drop_silence"

    # Melodic actions
    DELAYED_MELODY_ENTRY = "delayed_melody_entry"
    MELODY_DROPOUT = "melody_dropout"
    CALL_RESPONSE = "call_response"
    COUNTER_MELODY_ADD = "counter_melody_add"

    # Bass actions
    BASS_DROPOUT = "bass_dropout"
    REENTRY_808 = "808_reentry"
    OCTAVE_LIFT = "octave_lift"
    SYNCOPATED_BASS_PUSH = "syncopated_bass_push"


# ---------------------------------------------------------------------------
# PatternEvent
# ---------------------------------------------------------------------------

@dataclass
class PatternEvent:
    """A single pattern-level event targeting one role inside a section.

    Attributes:
        bar_start: 1-indexed bar where the event begins (relative to section).
        bar_end: 1-indexed bar where the event ends (inclusive).
        role: Instrument role this event targets (e.g. ``"drums"``, ``"bass"``).
        pattern_action: The :class:`PatternAction` to apply.
        intensity: Strength of the event in [0.0, 1.0].
        parameters: Arbitrary key/value pairs controlling event behaviour.
        notes: Human-readable annotation for debugging / logging.
    """

    bar_start: int
    bar_end: int
    role: str
    pattern_action: PatternAction
    intensity: float = 0.7
    parameters: Dict[str, object] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        if self.bar_start < 1:
            raise ValueError(f"bar_start must be >= 1, got {self.bar_start}")
        if self.bar_end < self.bar_start:
            raise ValueError(
                f"bar_end ({self.bar_end}) must be >= bar_start ({self.bar_start})"
            )
        if not self.role:
            raise ValueError("role must be a non-empty string")
        if not isinstance(self.pattern_action, PatternAction):
            raise TypeError(
                f"pattern_action must be a PatternAction instance, "
                f"got {type(self.pattern_action)}"
            )
        self.intensity = max(0.0, min(1.0, float(self.intensity)))


# ---------------------------------------------------------------------------
# PatternSectionPlan
# ---------------------------------------------------------------------------

@dataclass
class PatternSectionPlan:
    """Pattern-variation plan for one section of an arrangement.

    Attributes:
        section_name: Human-readable section label (e.g. ``"Hook 2"``).
        section_type: Canonical type (e.g. ``"hook"``, ``"verse"``).
        occurrence: 1-based counter within the section type.
        bars: Total number of bars in this section.
        source_quality: Source quality mode string (e.g. ``"true_stems"``).
        events: Ordered list of :class:`PatternEvent` objects.
        variation_budget: Maximum number of simultaneous pattern changes
            allowed (depends on source quality).
        notes: Human-readable rationale for the pattern choices.
    """

    section_name: str
    section_type: str
    occurrence: int
    bars: int
    source_quality: str = "true_stems"
    events: List[PatternEvent] = field(default_factory=list)
    variation_budget: int = 3
    notes: str = ""

    def __post_init__(self) -> None:
        if self.bars < 1:
            raise ValueError(f"bars must be >= 1, got {self.bars}")
        if self.occurrence < 1:
            raise ValueError(f"occurrence must be >= 1, got {self.occurrence}")

    @property
    def active_actions(self) -> List[PatternAction]:
        """Return the unique set of actions present in this section's events."""
        return list({e.pattern_action for e in self.events})

    def has_action(self, action: PatternAction) -> bool:
        return any(e.pattern_action == action for e in self.events)


# ---------------------------------------------------------------------------
# PatternVariationPlan
# ---------------------------------------------------------------------------

@dataclass
class PatternVariationPlan:
    """Top-level pattern variation plan for a full arrangement.

    Attributes:
        sections: Ordered list of :class:`PatternSectionPlan` objects.
        source_quality: Source quality mode for the whole arrangement.
        decision_log: Human-readable log of planning decisions.
        validation_issues: Issues raised by :class:`PatternVariationValidator`.
    """

    sections: List[PatternSectionPlan] = field(default_factory=list)
    source_quality: str = "true_stems"
    decision_log: List[str] = field(default_factory=list)
    validation_issues: List[str] = field(default_factory=list)

    @property
    def total_events(self) -> int:
        return sum(len(s.events) for s in self.sections)

    def section_by_type(self, section_type: str) -> List[PatternSectionPlan]:
        """Return all sections matching *section_type*."""
        return [s for s in self.sections if s.section_type == section_type]

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation of the plan."""
        return {
            "source_quality": self.source_quality,
            "total_events": self.total_events,
            "sections": [
                {
                    "section_name": s.section_name,
                    "section_type": s.section_type,
                    "occurrence": s.occurrence,
                    "bars": s.bars,
                    "variation_budget": s.variation_budget,
                    "events": [
                        {
                            "bar_start": e.bar_start,
                            "bar_end": e.bar_end,
                            "role": e.role,
                            "pattern_action": e.pattern_action.value,
                            "intensity": e.intensity,
                            "parameters": dict(e.parameters),
                            "notes": e.notes,
                        }
                        for e in s.events
                    ],
                    "notes": s.notes,
                }
                for s in self.sections
            ],
            "decision_log": list(self.decision_log),
            "validation_issues": list(self.validation_issues),
        }
