"""
Core data types for the timeline-based arrangement engine.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TimelineEvent:
    """A discrete musical event that occurs within a timeline section.

    Attributes:
        bar_start: Bar number (1-indexed) where the event begins.
        bar_end: Bar number (1-indexed, inclusive) where the event ends.
        action: The event type (e.g. ``"add_layer"``, ``"drum_fill"``).
        target_role: Instrument role this event targets, or ``None`` for global events.
        parameters: Arbitrary key/value pairs controlling event behaviour.
    """

    bar_start: int
    bar_end: int
    action: str
    target_role: Optional[str] = None
    parameters: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.bar_start < 1:
            raise ValueError(f"bar_start must be >= 1, got {self.bar_start}")
        if self.bar_end < self.bar_start:
            raise ValueError(
                f"bar_end ({self.bar_end}) must be >= bar_start ({self.bar_start})"
            )
        if not self.action:
            raise ValueError("action must be a non-empty string")


@dataclass
class TimelineSection:
    """A named musical section with its own energy targets and event list.

    Attributes:
        name: Human-readable section identifier (e.g. ``"intro"``, ``"hook"``).
        bars: Total number of bars in this section.
        target_energy: Desired energy level in [0.0, 1.0].
        target_density: Desired layer density in [0.0, 1.0].
        active_roles: Instrument roles that should be playing in this section.
        events: Ordered list of :class:`TimelineEvent` objects within this section.
    """

    name: str
    bars: int
    target_energy: float
    target_density: float
    active_roles: list = field(default_factory=list)
    events: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.bars < 1:
            raise ValueError(f"bars must be >= 1, got {self.bars}")
        if not (0.0 <= self.target_energy <= 1.0):
            raise ValueError(
                f"target_energy must be in [0, 1], got {self.target_energy}"
            )
        if not (0.0 <= self.target_density <= 1.0):
            raise ValueError(
                f"target_density must be in [0, 1], got {self.target_density}"
            )


@dataclass
class TimelinePlan:
    """The complete arrangement plan produced by the timeline engine.

    Attributes:
        sections: Ordered list of :class:`TimelineSection` objects.
        total_bars: Total bar count across all sections.
        energy_curve: Per-section energy values (same length as ``sections``).
        variation_log: Records of variation attempts for auditing/debugging.
        state_snapshot: Serialisable snapshot of the :class:`TimelineState` at
            the time this plan was produced.
    """

    sections: list = field(default_factory=list)
    total_bars: int = 0
    energy_curve: list = field(default_factory=list)
    variation_log: list = field(default_factory=list)
    state_snapshot: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.total_bars < 0:
            raise ValueError(f"total_bars must be >= 0, got {self.total_bars}")
