"""
Arrangement Memory V2 — stateful planning memory for the arrangement engine.

Tracks state across section planning to prevent:
- identical section maps when avoidable
- flat energy progression
- repetitive hook construction
- accidental fallback to the same full-stack output on every section

The memory guides planning decisions without overriding musical judgment.
It is lightweight, deterministic, and scoped to a single arrangement build.

Gated by ARRANGEMENT_MEMORY_V2 feature flag in config.py.  When the flag is
disabled, the :class:`ArrangementMemory` class can still be instantiated but
all mutation methods are no-ops and all queries return empty/default values so
callers do not need a separate flag check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Variation strategy names
# ---------------------------------------------------------------------------

VARIATION_STRATEGIES = frozenset({
    "drop_kick",         # Remove kick drum from a repeat for felt-absence tension
    "add_percussion",    # Layer in a new percussion role on a second occurrence
    "change_pattern",    # Swap the primary melodic role for a different one
    "half_time",         # Hint to the renderer to halve rhythmic density
    "filter_sweep",      # Mark section for an incoming filter sweep transition
    "role_rotation",     # Rotate support roles between repeats
    "support_swap",      # Replace a support role with an unused one
    "none",              # No variation strategy applied
})


# ---------------------------------------------------------------------------
# ArrangementMemory
# ---------------------------------------------------------------------------

@dataclass
class ArrangementMemory:
    """Stateful memory accumulated while building one arrangement plan.

    All methods are safe to call regardless of whether the ARRANGEMENT_MEMORY_V2
    flag is set — the ``enabled`` attribute controls whether mutations actually
    take effect.  Callers that always pass through the memory object do not need
    their own flag checks.
    """

    enabled: bool = True

    # Stems that have already been used in any section.
    used_stems: set[str] = field(default_factory=set)

    # Frozen-set role combinations used so far, keyed by section type.
    # e.g. {"verse": [frozenset({"drums", "bass"}), frozenset({"drums", "bass", "melody"})]}
    used_role_combinations: dict[str, list[frozenset[str]]] = field(
        default_factory=dict
    )

    # Chronological list of (section_type, energy_int) tuples as sections are planned.
    energy_history: list[tuple[str, int]] = field(default_factory=list)

    # How many times each section type has been planned so far.
    section_occurrence_count: dict[str, int] = field(default_factory=dict)

    # Variation strategies applied per section type across occurrences.
    # e.g. {"verse": ["none", "role_rotation"]}
    repeat_variation_history: dict[str, list[str]] = field(default_factory=dict)

    # ---------------------------------------------------------------------------
    # Mutation helpers
    # ---------------------------------------------------------------------------

    def record_section(
        self,
        *,
        section_type: str,
        roles: list[str],
        energy: int,
        variation_strategy: str = "none",
    ) -> None:
        """Record a completed section into memory.

        Should be called after each section plan is finalized.
        """
        if not self.enabled:
            return

        # Track occurrence count.
        self.section_occurrence_count[section_type] = (
            self.section_occurrence_count.get(section_type, 0) + 1
        )

        # Track role combo for this section type.
        combo = frozenset(roles)
        if section_type not in self.used_role_combinations:
            self.used_role_combinations[section_type] = []
        self.used_role_combinations[section_type].append(combo)

        # Track all stems used globally.
        self.used_stems.update(roles)

        # Record energy.
        self.energy_history.append((section_type, energy))

        # Record variation strategy.
        if section_type not in self.repeat_variation_history:
            self.repeat_variation_history[section_type] = []
        self.repeat_variation_history[section_type].append(
            variation_strategy if variation_strategy in VARIATION_STRATEGIES else "none"
        )

    # ---------------------------------------------------------------------------
    # Query helpers
    # ---------------------------------------------------------------------------

    def occurrence_of(self, section_type: str) -> int:
        """Return how many times *section_type* has been planned so far."""
        return self.section_occurrence_count.get(section_type, 0)

    def previous_roles_for(self, section_type: str) -> list[str]:
        """Return the role list from the *most recent* occurrence of *section_type*.

        Returns an empty list if this is the first occurrence.
        """
        combos = self.used_role_combinations.get(section_type, [])
        if not combos:
            return []
        return sorted(combos[-1])  # deterministic order

    def all_role_combos_for(self, section_type: str) -> list[frozenset[str]]:
        """Return all role combinations recorded for *section_type* in order."""
        return list(self.used_role_combinations.get(section_type, []))

    def is_role_combo_used(self, section_type: str, roles: list[str]) -> bool:
        """Return True if this exact role combo has already been used for *section_type*."""
        if not self.enabled:
            return False
        combo = frozenset(roles)
        return combo in self.used_role_combinations.get(section_type, [])

    def energy_is_flat(self) -> bool:
        """Return True if the last 3 sections all have the same energy level.

        Used as a signal to inject contrast into the next section.
        """
        if not self.enabled or len(self.energy_history) < 3:
            return False
        recent = [e for _, e in self.energy_history[-3:]]
        return len(set(recent)) == 1

    def last_energy(self) -> Optional[int]:
        """Return the energy level of the most recently planned section."""
        if not self.energy_history:
            return None
        return self.energy_history[-1][1]

    def variation_strategies_used_for(self, section_type: str) -> list[str]:
        """Return the ordered list of variation strategies applied to *section_type*."""
        return list(self.repeat_variation_history.get(section_type, []))

    def suggest_variation_strategy(
        self,
        section_type: str,
        occurrence: int,
        available_roles: list[str],
        prev_roles: list[str],
    ) -> str:
        """Suggest a deterministic variation strategy for a repeated section.

        Priority:
        1. If no variation has been attempted yet: ``role_rotation`` when enough
           roles exist, else ``add_percussion`` when percussion is available.
        2. If ``role_rotation`` was used last time: try ``support_swap``.
        3. If already used ``support_swap``: try ``add_percussion``.
        4. Fallback: ``change_pattern`` when a melody role is available.
        5. Default: ``none``.

        Only called when ``occurrence > 1``.
        """
        if not self.enabled or occurrence <= 1:
            return "none"

        used = self.variation_strategies_used_for(section_type)
        last_used = used[-1] if used else "none"

        available_set = set(available_roles)
        prev_set = set(prev_roles)

        # Can we add a role not in prev?
        new_roles = [r for r in available_roles if r not in prev_set]

        if last_used == "none":
            if len(available_set - prev_set) >= 1:
                return "role_rotation"
            if "percussion" in available_set and "percussion" not in prev_set:
                return "add_percussion"
            return "none"

        if last_used == "role_rotation":
            if new_roles:
                return "support_swap"
            return "add_percussion" if "percussion" in available_set else "none"

        if last_used == "support_swap":
            return "add_percussion" if "percussion" in available_set else "change_pattern"

        if last_used == "add_percussion":
            if "melody" in available_set and "melody" not in prev_set:
                return "change_pattern"
            return "none"

        return "none"

    # ---------------------------------------------------------------------------
    # Serialisation (for observability / logs)
    # ---------------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-safe snapshot of the memory state."""
        return {
            "enabled": self.enabled,
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
