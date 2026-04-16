"""
Arranger V2 — arrangement state tracker.

ArrangerState is the single source of truth during a planning pass.  It
records every decision made so later sections can be planned with awareness
of what came before.  It is scoped to a single arrangement build; never
shared across builds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ArrangerState:
    """Mutable state accumulated while building one arrangement plan.

    Usage::

        state = ArrangerState()
        state.record_section("verse", ["drums", "bass"], energy=3)
        assert not state.is_combo_used("verse", ["drums", "bass"])  # False — already used
    """

    # All role IDs that have appeared in any section.
    used_stems: set[str] = field(default_factory=set)

    # Frozen-set role combinations used per section type.
    # e.g. {"verse": [frozenset({"drums","bass"}), frozenset({"drums","bass","melody"})]}
    used_role_combinations: dict[str, list[frozenset[str]]] = field(default_factory=dict)

    # Chronological (section_type, energy_int) history.
    energy_history: list[tuple[str, int]] = field(default_factory=list)

    # How many times each section type has been planned so far (0-based counts).
    section_occurrence_count: dict[str, int] = field(default_factory=dict)

    # Ordered variation strategies applied per section type.
    repeat_variation_history: dict[str, list[str]] = field(default_factory=dict)

    # ---------------------------------------------------------------------------
    # Write API
    # ---------------------------------------------------------------------------

    def record_section(
        self,
        section_type: str,
        roles: list[str],
        energy: int,
        variation_strategy: str = "none",
    ) -> None:
        """Commit a completed section into state.

        Must be called after each section is finalized so subsequent
        sections have accurate prior-state information.
        """
        self.section_occurrence_count[section_type] = (
            self.section_occurrence_count.get(section_type, 0) + 1
        )
        combo = frozenset(roles)
        self.used_role_combinations.setdefault(section_type, []).append(combo)
        self.used_stems.update(roles)
        self.energy_history.append((section_type, int(energy)))
        self.repeat_variation_history.setdefault(section_type, []).append(variation_strategy)

    # ---------------------------------------------------------------------------
    # Read API
    # ---------------------------------------------------------------------------

    def occurrence_of(self, section_type: str) -> int:
        """Return how many times *section_type* has already been committed."""
        return self.section_occurrence_count.get(section_type, 0)

    def previous_roles_for(self, section_type: str) -> list[str]:
        """Return roles from the most-recent occurrence of *section_type*."""
        combos = self.used_role_combinations.get(section_type, [])
        if not combos:
            return []
        return sorted(combos[-1])

    def all_combos_for(self, section_type: str) -> list[frozenset[str]]:
        """Return all role combinations used for *section_type* in order."""
        return list(self.used_role_combinations.get(section_type, []))

    def is_combo_used(self, section_type: str, roles: list[str]) -> bool:
        """Return True if this exact role set has already been planned for *section_type*."""
        combo = frozenset(roles)
        return combo in self.used_role_combinations.get(section_type, [])

    def is_energy_flat(self) -> bool:
        """Return True if the last 3 sections all share the same energy level."""
        if len(self.energy_history) < 3:
            return False
        recent = [e for _, e in self.energy_history[-3:]]
        return len(set(recent)) == 1

    def last_energy(self) -> Optional[int]:
        """Return the energy integer of the most recently recorded section."""
        if not self.energy_history:
            return None
        return self.energy_history[-1][1]

    def last_roles(self) -> list[str]:
        """Return the roles from the most recently recorded section."""
        for section_type, combos in reversed(
            list(self.used_role_combinations.items())
        ):
            if combos:
                return sorted(combos[-1])
        return []

    def last_variation_for(self, section_type: str) -> str:
        """Return the most recent variation strategy for *section_type*."""
        history = self.repeat_variation_history.get(section_type, [])
        return history[-1] if history else "none"

    # ---------------------------------------------------------------------------
    # Serialisation
    # ---------------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-safe snapshot."""
        return {
            "used_stems": sorted(self.used_stems),
            "section_occurrence_count": dict(self.section_occurrence_count),
            "energy_history": [
                {"section_type": st, "energy": e} for st, e in self.energy_history
            ],
            "repeat_variation_history": {
                k: list(v) for k, v in self.repeat_variation_history.items()
            },
            "used_role_combinations": {
                k: [sorted(combo) for combo in v]
                for k, v in self.used_role_combinations.items()
            },
        }
