"""
State tracking for the Drop Engine.

Maintains per-run memory so that the planner can avoid repeating identical
drop behaviour on every boundary, escalate payoff for later hook occurrences,
and prevent overuse of silence-based drops.

The state is fresh for every :class:`~app.services.drop_engine.planner.DropEnginePlanner`
run and is never persisted between arrangement jobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set


@dataclass
class DropEngineState:
    """Mutable planning state for one arrangement run.

    Attributes:
        used_drop_event_types: Set of event type strings that have already
            been used as a *primary* event on any boundary in this run.
            Used to avoid stacking the same event repeatedly.
        repeated_hook_boundary_count: How many hook-entry boundaries have
            been planned so far (0-based starting count).
        previous_boundary_types: Ordered list of ``"from_section -> to_section"``
            strings recorded as each boundary is processed.
        previous_payoff_scores: Ordered list of payoff scores from already-planned
            boundaries, in the order they were planned.
        previous_tension_scores: Ordered list of tension scores from already-planned
            boundaries, in the order they were planned.
        hook_entry_event_types: Ordered list of primary event type strings used
            at hook-entry boundaries (pre_hook -> hook), newest last.
            Used to detect identical repeated hook treatment.
        silence_event_count: Running count of silence-based events used
            (``pre_drop_silence`` + ``silence_tease``) to prevent overuse.
    """

    used_drop_event_types: Set[str] = field(default_factory=set)
    repeated_hook_boundary_count: int = 0
    previous_boundary_types: List[str] = field(default_factory=list)
    previous_payoff_scores: List[float] = field(default_factory=list)
    previous_tension_scores: List[float] = field(default_factory=list)
    hook_entry_event_types: List[str] = field(default_factory=list)
    silence_event_count: int = 0

    # Internal: per-boundary-key occurrence counters used by the planner to
    # assign occurrence_index when the same boundary type repeats.
    _boundary_occurrence_counters: Dict[str, int] = field(
        default_factory=dict, repr=False
    )

    def record_boundary(
        self,
        boundary_key: str,
        primary_event_type: str | None,
        tension_score: float,
        payoff_score: float,
    ) -> None:
        """Record an already-planned boundary in the state.

        Parameters
        ----------
        boundary_key:
            Canonical ``"from_section -> to_section"`` string.
        primary_event_type:
            The primary event type used (``None`` if no primary event was placed).
        tension_score:
            Computed tension score for the boundary.
        payoff_score:
            Computed payoff score for the boundary.
        """
        self.previous_boundary_types.append(boundary_key)
        self.previous_tension_scores.append(max(0.0, min(1.0, float(tension_score))))
        self.previous_payoff_scores.append(max(0.0, min(1.0, float(payoff_score))))

        if primary_event_type is not None:
            self.used_drop_event_types.add(primary_event_type)
            if primary_event_type in ("pre_drop_silence", "silence_tease"):
                self.silence_event_count += 1
            if boundary_key == "pre_hook -> hook":
                self.hook_entry_event_types.append(primary_event_type)
                self.repeated_hook_boundary_count += 1

    def get_occurrence_index(self, boundary_key: str) -> int:
        """Return the 0-based occurrence index for *boundary_key* and increment it.

        The first time a boundary key is seen this returns 0, the second time 1, etc.
        """
        idx = self._boundary_occurrence_counters.get(boundary_key, 0)
        self._boundary_occurrence_counters[boundary_key] = idx + 1
        return idx

    def hook_entries_are_identical(self) -> bool:
        """Return True when all hook-entry events recorded so far are the same type."""
        if len(self.hook_entry_event_types) < 2:
            return False
        return len(set(self.hook_entry_event_types)) == 1

    def silence_overused(self, max_silence_events: int = 2) -> bool:
        """Return True when silence-based events exceed *max_silence_events*."""
        return self.silence_event_count > max_silence_events

    def event_type_used(self, event_type: str) -> bool:
        """Return True when *event_type* has already been used as a primary event."""
        return event_type in self.used_drop_event_types
