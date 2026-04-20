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


# ---------------------------------------------------------------------------
# Higher-level variation types (used by PatternVariationEngine)
# ---------------------------------------------------------------------------

@dataclass
class PatternVariationEvent:
    """A single variation event emitted by :class:`PatternVariationEngine`.

    Maps to the JSON output format described in the LoopArchitect spec:

    .. code-block:: json

        {"bars": [5, 8], "role": "drums", "type": "drum_fill", "intensity": 0.8}

    Attributes:
        bar_start: 1-indexed bar where the variation begins (relative to section).
        bar_end: 1-indexed bar where the variation ends (inclusive).
        role: Instrument role targeted (e.g. ``"drums"``, ``"bass"``).
        variation_type: Human-readable variation name (e.g. ``"drum_fill"``).
        intensity: Strength in [0.0, 1.0].
        parameters: Arbitrary key/value pairs for downstream processors.
    """

    bar_start: int
    bar_end: int
    role: str
    variation_type: str
    intensity: float = 0.7
    parameters: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.bar_start < 1:
            raise ValueError(f"bar_start must be >= 1, got {self.bar_start}")
        if self.bar_end < self.bar_start:
            raise ValueError(
                f"bar_end ({self.bar_end}) must be >= bar_start ({self.bar_start})"
            )
        if not self.role:
            raise ValueError("role must be a non-empty string")
        if not self.variation_type:
            raise ValueError("variation_type must be a non-empty string")
        self.intensity = max(0.0, min(1.0, float(self.intensity)))

    def to_dict(self) -> dict:
        return {
            "bars": [self.bar_start, self.bar_end],
            "role": self.role,
            "type": self.variation_type,
            "intensity": self.intensity,
            "parameters": dict(self.parameters),
        }


@dataclass
class VariationPlan:
    """Variation plan generated by :class:`PatternVariationEngine` for one section.

    Attributes:
        section_name: Human-readable section label (e.g. ``"Hook 2"``).
        variations: Ordered list of :class:`PatternVariationEvent` objects.
        variation_density: Proportion of available variation budget used (0.0–1.0).
        repetition_score: How well-varied this plan is (0.0 = fully repetitive,
            1.0 = maximally varied).  Plans scoring below 0.3 are rejected.
        applied_strategies: Human-readable list of variation strategies applied.
    """

    section_name: str
    variations: List[PatternVariationEvent] = field(default_factory=list)
    variation_density: float = 0.0
    repetition_score: float = 0.0
    applied_strategies: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.variation_density = max(0.0, min(1.0, float(self.variation_density)))
        self.repetition_score = max(0.0, min(1.0, float(self.repetition_score)))

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation matching the spec output format."""
        return {
            "section": self.section_name,
            "variations": [v.to_dict() for v in self.variations],
            "variation_density": round(self.variation_density, 4),
            "repetition_score": round(self.repetition_score, 4),
            "applied_strategies": list(self.applied_strategies),
        }


@dataclass
class VariationContext:
    """Input context consumed by :class:`PatternVariationEngine`.

    Produced from the output of the Timeline Engine and arrangement metadata.

    Attributes:
        section_name: Human-readable section label.
        section_index: 0-based position in the arrangement.
        section_occurrence_index: 0-based repetition counter (0 = first time
            this section type appears, 1 = second time, etc.).
        total_occurrences: Total number of times this section type appears
            across the full arrangement.
        bars: Bar count of this section.
        energy: Target energy level (0.0–1.0).
        density: Target density level (0.0–1.0).
        active_roles: Instrument roles active in this section.
        timeline_events: Raw event list from the Timeline Engine (may be empty).
        source_quality: Source quality mode string (default ``"true_stems"``).
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
    source_quality: str = "true_stems"

    def __post_init__(self) -> None:
        self.energy = max(0.0, min(1.0, float(self.energy)))
        self.density = max(0.0, min(1.0, float(self.density)))
        if self.bars < 1:
            raise ValueError(f"bars must be >= 1, got {self.bars}")
        if self.section_occurrence_index < 0:
            raise ValueError(
                f"section_occurrence_index must be >= 0, got {self.section_occurrence_index}"
            )

    @property
    def section_type(self) -> str:
        """Derive a canonical section type from the section name."""
        name = self.section_name.lower().strip()
        # pre_hook must be checked before hook since "pre-hook" contains "hook"
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
        """Return 1-based occurrence index for sub-planner compatibility."""
        return self.section_occurrence_index + 1
