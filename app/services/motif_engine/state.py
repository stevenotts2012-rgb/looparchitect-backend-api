"""
State tracking for the Motif Engine.

Maintains per-run memory so the planner can:
- avoid identical motif treatment on repeated hooks
- prevent the bridge from copying hook motif directly
- ensure the outro resolves rather than reusing full hook motif

The state is fresh for every :class:`~app.services.motif_engine.planner.MotifPlanner`
run and is never persisted between arrangement jobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class MotifEngineState:
    """Mutable planning state for one arrangement run.

    Attributes:
        motif_usage_history: Ordered list of ``(section_name, transformation_types)``
            tuples for every section that received a motif treatment so far.
        hook_motif_treatments: Ordered list of transformation-type-sets used at
            hook sections, newest last.  Used to detect repeated identical hook
            treatment.
        bridge_treatment_types: Transformation types used at the most recent
            bridge/breakdown section (or empty set if none yet).
        outro_resolved: True once an outro section has received a reducing
            or resolving motif treatment.
        previous_section_type: The canonical section type of the most recently
            processed section (or ``None`` at the start).
        section_occurrence_counters: Per-section-type count of how many motif
            occurrences have been assigned so far.
    """

    motif_usage_history: List[tuple] = field(default_factory=list)
    hook_motif_treatments: List[frozenset] = field(default_factory=list)
    bridge_treatment_types: Set[str] = field(default_factory=set)
    outro_resolved: bool = False
    previous_section_type: Optional[str] = None

    # Internal: per-section-type occurrence counters.
    _section_occurrence_counters: Dict[str, int] = field(
        default_factory=dict, repr=False
    )

    def record_occurrence(
        self,
        section_name: str,
        section_type: str,
        transformation_types: List[str],
    ) -> None:
        """Record an assigned motif occurrence.

        Parameters
        ----------
        section_name:
            Raw section name (e.g. ``"hook_1"``).
        section_type:
            Canonical section type (e.g. ``"hook"``).
        transformation_types:
            List of transformation type strings applied.
        """
        self.motif_usage_history.append((section_name, list(transformation_types)))
        self.previous_section_type = section_type

        if section_type == "hook":
            self.hook_motif_treatments.append(frozenset(transformation_types))

        if section_type in ("bridge", "breakdown"):
            self.bridge_treatment_types = set(transformation_types)

        if section_type == "outro":
            self.outro_resolved = True

    def get_occurrence_index(self, section_type: str) -> int:
        """Return the 0-based occurrence index for *section_type* and increment.

        The first time a section type is processed this returns 0, second 1, etc.
        """
        idx = self._section_occurrence_counters.get(section_type, 0)
        self._section_occurrence_counters[section_type] = idx + 1
        return idx

    def hook_treatments_are_identical(self) -> bool:
        """Return True when at least two hook treatments exist and all are equal."""
        if len(self.hook_motif_treatments) < 2:
            return False
        return len(set(self.hook_motif_treatments)) == 1

    def last_hook_treatment(self) -> Optional[frozenset]:
        """Return the most recent hook transformation set, or ``None``."""
        if not self.hook_motif_treatments:
            return None
        return self.hook_motif_treatments[-1]

    def total_occurrences(self) -> int:
        """Return the total number of motif occurrences recorded so far."""
        return len(self.motif_usage_history)
