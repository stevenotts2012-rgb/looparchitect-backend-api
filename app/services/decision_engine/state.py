"""
State tracking for the Decision Engine.

Maintains per-run memory so the planner can:
- avoid identical section decisions on repeated sections
- track which roles have been held back so they can be reintroduced later
- prevent full-stack from appearing too early
- ensure hooks escalate across repetitions
- ensure bridge and outro decisions are applied correctly

The state is fresh for every :class:`~app.services.decision_engine.planner.DecisionPlanner`
run and is never persisted between arrangement jobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple


@dataclass
class DecisionEngineState:
    """Mutable planning state for one arrangement run.

    Attributes:
        held_back_roles: Roles currently being withheld from the arrangement
            (i.e. introduced in the plan but not yet released).
        reintroduced_roles: Roles that have been released after being held back.
        section_occurrence_counters: Per-section-type count of how many decisions
            have been made so far.
        section_decision_fingerprints: Per-section-type ordered list of
            decision fingerprints (frozensets of action_type+target_role) to
            detect repeated identical patterns.
        hook_fullness_history: Ordered list of fullness labels used for each
            hook section, newest last.
        prior_hook_had_subtraction_before: True if the most recent pre-hook
            section applied a subtraction before the hook.
        bridge_decision_fullness: The fullness label used in the most recent
            bridge/breakdown section (or ``None`` if not yet seen).
        full_stack_section_names: Names of sections that were allowed full stack.
        previous_section_type: Canonical type of the most recently processed
            section.
        section_type_sequence: Ordered list of canonical section types processed
            so far.
    """

    held_back_roles: Set[str] = field(default_factory=set)
    reintroduced_roles: Set[str] = field(default_factory=set)
    section_occurrence_counters: Dict[str, int] = field(default_factory=dict)
    section_decision_fingerprints: Dict[str, List[FrozenSet[Tuple[str, Optional[str]]]]] = field(
        default_factory=dict
    )
    hook_fullness_history: List[str] = field(default_factory=list)
    prior_hook_had_subtraction_before: bool = False
    bridge_decision_fullness: Optional[str] = None
    full_stack_section_names: List[str] = field(default_factory=list)
    previous_section_type: Optional[str] = None
    section_type_sequence: List[str] = field(default_factory=list)

    def get_occurrence_index(self, section_type: str) -> int:
        """Return the 0-based occurrence index for *section_type* and increment.

        The first time a section type is processed this returns 0, the second
        time it returns 1, etc.
        """
        idx = self.section_occurrence_counters.get(section_type, 0)
        self.section_occurrence_counters[section_type] = idx + 1
        return idx

    def hold_back_role(self, role: str) -> None:
        """Mark *role* as held back (withheld from the arrangement)."""
        self.held_back_roles.add(role)

    def reintroduce_role(self, role: str) -> None:
        """Mark *role* as reintroduced (released from held-back status)."""
        self.held_back_roles.discard(role)
        self.reintroduced_roles.add(role)

    def has_held_back_roles(self) -> bool:
        """Return True when at least one role is currently held back."""
        return len(self.held_back_roles) > 0

    def record_section(
        self,
        section_name: str,
        section_type: str,
        fullness: str,
        action_fingerprint: FrozenSet[Tuple[str, Optional[str]]],
        allow_full_stack: bool,
    ) -> None:
        """Record a completed section decision.

        Parameters
        ----------
        section_name:
            Raw section name (e.g. ``"verse_1"``).
        section_type:
            Canonical section type (e.g. ``"verse"``).
        fullness:
            Fullness label chosen for this section.
        action_fingerprint:
            A frozenset of ``(action_type, target_role)`` tuples uniquely
            describing the actions taken in this section.
        allow_full_stack:
            Whether full stack was allowed for this section.
        """
        if section_type not in self.section_decision_fingerprints:
            self.section_decision_fingerprints[section_type] = []
        self.section_decision_fingerprints[section_type].append(action_fingerprint)

        if section_type == "hook":
            self.hook_fullness_history.append(fullness)

        if section_type in ("bridge", "breakdown"):
            self.bridge_decision_fullness = fullness

        if allow_full_stack:
            self.full_stack_section_names.append(section_name)

        self.previous_section_type = section_type
        self.section_type_sequence.append(section_type)

    def last_hook_fullness(self) -> Optional[str]:
        """Return the fullness label of the most recent hook, or ``None``."""
        if not self.hook_fullness_history:
            return None
        return self.hook_fullness_history[-1]

    def hook_count(self) -> int:
        """Return how many hook decisions have been recorded so far."""
        return len(self.hook_fullness_history)

    def section_fingerprints_are_identical(self, section_type: str) -> bool:
        """Return True when at least two decisions exist for *section_type*
        and they all have the same fingerprint."""
        fps = self.section_decision_fingerprints.get(section_type, [])
        if len(fps) < 2:
            return False
        return len(set(fps)) == 1

    def full_stack_used_before(self) -> bool:
        """Return True when full stack has been allowed in any prior section."""
        return len(self.full_stack_section_names) > 0

    def full_stack_count(self) -> int:
        """Return the number of sections that were allowed full stack."""
        return len(self.full_stack_section_names)
