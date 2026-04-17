"""
State tracker for the timeline engine.

Tracks per-plan mutable state so the planner and validator can reason about
what has already happened during arrangement construction.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional


@dataclass
class TimelineState:
    """Mutable arrangement state accumulated while building a :class:`TimelinePlan`.

    Attributes:
        used_roles: All instrument roles referenced at least once across all
            sections built so far.
        used_role_combinations: Each unique frozenset of active roles observed
            across sections (stored as sorted tuples for serializability).
        section_occurrence_count: Maps ``section_name`` → number of times that
            section has appeared in the plan.
        energy_history: Per-section energy values in plan order.
        variation_history: Records of variation attempts.  Each entry is a dict
            with at minimum ``{"section": str, "attempt": str, "success": bool}``.
    """

    used_roles: List[str] = field(default_factory=list)
    used_role_combinations: List[Tuple[str, ...]] = field(default_factory=list)
    section_occurrence_count: Dict[str, int] = field(default_factory=dict)
    energy_history: List[float] = field(default_factory=list)
    variation_history: List[dict] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Mutation helpers                                                     #
    # ------------------------------------------------------------------ #

    def record_section(self, section_name: str, active_roles: List[str], energy: float) -> None:
        """Update state after a section has been added to the plan."""
        # Track occurrence count
        name_key = section_name.lower()
        self.section_occurrence_count[name_key] = (
            self.section_occurrence_count.get(name_key, 0) + 1
        )

        # Track roles
        for role in active_roles:
            if role not in self.used_roles:
                self.used_roles.append(role)

        # Track role combinations (deduplicated)
        combo = tuple(sorted(active_roles))
        if combo not in self.used_role_combinations:
            self.used_role_combinations.append(combo)

        # Track energy
        self.energy_history.append(energy)

    def record_variation_attempt(
        self,
        section_name: str,
        attempt_description: str,
        success: bool,
        details: Optional[dict] = None,
    ) -> None:
        """Log a variation attempt."""
        entry: dict = {
            "section": section_name,
            "attempt": attempt_description,
            "success": success,
        }
        if details:
            entry.update(details)
        self.variation_history.append(entry)

    def occurrence_count(self, section_name: str) -> int:
        """Return how many times *section_name* has occurred so far."""
        return self.section_occurrence_count.get(section_name.lower(), 0)

    def is_flat(self) -> bool:
        """Return ``True`` if the energy history shows no meaningful variation."""
        if len(self.energy_history) < 2:
            return False
        return (max(self.energy_history) - min(self.energy_history)) < 0.1

    def to_dict(self) -> dict:
        """Return a JSON-serialisable snapshot of the current state."""
        return {
            "used_roles": list(self.used_roles),
            "used_role_combinations": [list(c) for c in self.used_role_combinations],
            "section_occurrence_count": dict(self.section_occurrence_count),
            "energy_history": list(self.energy_history),
            "variation_history": list(self.variation_history),
        }
