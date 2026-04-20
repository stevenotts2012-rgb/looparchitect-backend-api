"""
State tracker for the Pattern Variation Engine.

Tracks per-arrangement mutable state so the planner can make deterministic,
source-aware decisions about pattern changes inside sections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from app.services.pattern_variation_engine.types import PatternAction


# ---------------------------------------------------------------------------
# PatternVariationState
# ---------------------------------------------------------------------------

@dataclass
class PatternVariationState:
    """Mutable state accumulated while building a :class:`PatternVariationPlan`.

    Attributes:
        section_occurrence_count: Maps ``section_type`` → number of times that
            section type has appeared in the plan so far.
        used_pattern_combinations: Set of (section_type, frozenset[PatternAction])
            tuples representing pattern combinations already used.
        previous_drum_behavior: The last drum :class:`PatternAction` applied,
            keyed by section type.
        previous_melody_behavior: The last melody :class:`PatternAction` applied,
            keyed by section type.
        previous_hook_pattern_style: The pattern style used in the most recent
            hook section (stored as a sorted tuple of action strings).
        energy_history: Per-section energy levels in arrangement order (0.0–1.0).
            Used to detect flat curves and validate escalation.
        variation_log: Audit log of variation decisions.  Each entry is a dict
            with at minimum ``{"section": str, "action": str, "applied": bool}``.
    """

    section_occurrence_count: Dict[str, int] = field(default_factory=dict)
    used_pattern_combinations: Set[Tuple[str, Tuple[str, ...]]] = field(
        default_factory=set
    )
    previous_drum_behavior: Dict[str, Optional[PatternAction]] = field(
        default_factory=dict
    )
    previous_melody_behavior: Dict[str, Optional[PatternAction]] = field(
        default_factory=dict
    )
    previous_hook_pattern_style: Tuple[str, ...] = field(default_factory=tuple)
    energy_history: List[float] = field(default_factory=list)
    variation_log: List[dict] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Occurrence tracking                                                  #
    # ------------------------------------------------------------------ #

    def next_occurrence(self, section_type: str) -> int:
        """Increment and return the occurrence counter for *section_type*.

        Returns the occurrence *after* incrementing (1-based).
        """
        key = section_type.lower()
        self.section_occurrence_count[key] = (
            self.section_occurrence_count.get(key, 0) + 1
        )
        return self.section_occurrence_count[key]

    def occurrence_count(self, section_type: str) -> int:
        """Return how many times *section_type* has been processed so far."""
        return self.section_occurrence_count.get(section_type.lower(), 0)

    # ------------------------------------------------------------------ #
    # Pattern-combination tracking                                         #
    # ------------------------------------------------------------------ #

    def record_pattern_combination(
        self,
        section_type: str,
        actions: List[PatternAction],
    ) -> None:
        """Record a (section_type, actions) combination as used."""
        key = (section_type.lower(), tuple(sorted(a.value for a in actions)))
        self.used_pattern_combinations.add(key)

    def is_combination_used(
        self,
        section_type: str,
        actions: List[PatternAction],
    ) -> bool:
        """Return ``True`` if this exact combination has already been used."""
        key = (section_type.lower(), tuple(sorted(a.value for a in actions)))
        return key in self.used_pattern_combinations

    # ------------------------------------------------------------------ #
    # Behaviour tracking helpers                                           #
    # ------------------------------------------------------------------ #

    def update_drum_behavior(
        self, section_type: str, action: Optional[PatternAction]
    ) -> None:
        self.previous_drum_behavior[section_type.lower()] = action

    def get_previous_drum_behavior(
        self, section_type: str
    ) -> Optional[PatternAction]:
        return self.previous_drum_behavior.get(section_type.lower())

    def update_melody_behavior(
        self, section_type: str, action: Optional[PatternAction]
    ) -> None:
        self.previous_melody_behavior[section_type.lower()] = action

    def get_previous_melody_behavior(
        self, section_type: str
    ) -> Optional[PatternAction]:
        return self.previous_melody_behavior.get(section_type.lower())

    def update_hook_pattern_style(self, actions: List[PatternAction]) -> None:
        self.previous_hook_pattern_style = tuple(sorted(a.value for a in actions))

    # ------------------------------------------------------------------ #
    # Energy tracking                                                      #
    # ------------------------------------------------------------------ #

    def record_energy(self, energy: float) -> None:
        """Append an energy reading for the most recently processed section."""
        self.energy_history.append(max(0.0, min(1.0, float(energy))))

    def is_energy_flat(self) -> bool:
        """Return ``True`` if the energy history shows no meaningful variation."""
        if len(self.energy_history) < 2:
            return False
        return (max(self.energy_history) - min(self.energy_history)) < 0.1

    def last_energy(self) -> float:
        """Return the most recent energy value, or 0.5 if history is empty."""
        return self.energy_history[-1] if self.energy_history else 0.5

    # ------------------------------------------------------------------ #
    # Variation log                                                        #
    # ------------------------------------------------------------------ #

    def log_variation(
        self,
        section: str,
        action: str,
        applied: bool,
        reason: str = "",
    ) -> None:
        """Append a variation decision to the audit log."""
        entry: dict = {
            "section": section,
            "action": action,
            "applied": applied,
        }
        if reason:
            entry["reason"] = reason
        self.variation_log.append(entry)

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """Return a JSON-serialisable snapshot of the current state."""
        return {
            "section_occurrence_count": dict(self.section_occurrence_count),
            "used_pattern_combinations": [
                list(combo) for combo in self.used_pattern_combinations
            ],
            "previous_drum_behavior": {
                k: (v.value if v else None)
                for k, v in self.previous_drum_behavior.items()
            },
            "previous_melody_behavior": {
                k: (v.value if v else None)
                for k, v in self.previous_melody_behavior.items()
            },
            "previous_hook_pattern_style": list(self.previous_hook_pattern_style),
            "energy_history": list(self.energy_history),
            "variation_log": list(self.variation_log),
        }
