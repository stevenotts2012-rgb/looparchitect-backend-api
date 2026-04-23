"""Template selector for arrangement structure.

Selects an arrangement template based on genre, vibe, energy, and other
loop characteristics. Supports multiple templates per genre.

Trap templates:
  trap_A: intro → verse → hook → verse → hook → outro
  trap_B: intro → hook → verse → hook → outro
  trap_C: intro → verse → pre_hook → hook → verse → hook → outro
  trap_D: hook → verse → hook → outro  (no intro)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TemplateDefinition:
    """An arrangement template that defines the ordered section structure.

    Attributes:
        template_id: Unique identifier (e.g. ``"trap_C"``).
        genre:       Top-level genre this template serves.
        sections:    Ordered list of canonical section type names.
        description: Human-readable summary of the template's intent.
    """

    template_id: str
    genre: str
    sections: list[str]
    description: str = ""


# ---------------------------------------------------------------------------
# Built-in template registry
# ---------------------------------------------------------------------------

_TEMPLATES: list[TemplateDefinition] = [
    # --- Trap ---
    TemplateDefinition(
        template_id="trap_A",
        genre="trap",
        sections=["intro", "verse", "hook", "verse", "hook", "outro"],
        description="Standard trap layout — intro, two verse/hook cycles, outro.",
    ),
    TemplateDefinition(
        template_id="trap_B",
        genre="trap",
        sections=["intro", "hook", "verse", "hook", "outro"],
        description="Hook-forward trap — leads with hook for immediate payoff.",
    ),
    TemplateDefinition(
        template_id="trap_C",
        genre="trap",
        sections=["intro", "verse", "pre_hook", "hook", "verse", "hook", "outro"],
        description="Melodic trap with pre-hook tension build — best for rich melodies.",
    ),
    TemplateDefinition(
        template_id="trap_D",
        genre="trap",
        sections=["hook", "verse", "hook", "outro"],
        description="Minimal trap — no intro, sparse arrangement, hook-first.",
    ),
    # --- Drill ---
    TemplateDefinition(
        template_id="drill_A",
        genre="drill",
        sections=["intro", "verse", "hook", "verse", "hook", "outro"],
        description="Standard drill layout — mirrors trap_A base structure.",
    ),
    # --- Rage ---
    TemplateDefinition(
        template_id="rage_A",
        genre="rage",
        sections=["intro", "hook", "verse", "hook", "outro"],
        description="Rage layout — intense hook-forward with limited verse space.",
    ),
    # --- R&B ---
    TemplateDefinition(
        template_id="rnb_A",
        genre="rnb",
        sections=["intro", "verse", "pre_hook", "hook", "verse", "outro"],
        description="R&B layout — melodic build through pre-hook, resolves in verse.",
    ),
    # --- Generic ---
    TemplateDefinition(
        template_id="generic_A",
        genre="generic",
        sections=["intro", "verse", "hook", "verse", "hook", "outro"],
        description="Generic arrangement — safe default for unknown genres.",
    ),
    # --- West Coast ---
    TemplateDefinition(
        template_id="west_coast_A",
        genre="west_coast",
        sections=["intro", "verse", "hook", "verse", "hook", "outro"],
        description="West Coast layout — standard structure with smooth feel.",
    ),
]

_TEMPLATE_MAP: dict[str, TemplateDefinition] = {t.template_id: t for t in _TEMPLATES}


class TemplateSelector:
    """Selects an arrangement template deterministically from genre + loop traits.

    All selection logic is deterministic.  When multiple templates are
    candidates, ``variation_seed`` is used to pick among them reproducibly.
    """

    def select(
        self,
        genre: str,
        vibe: str,
        energy: float,
        melodic_richness: float,
        loop_density: float,
        variation_seed: int | None = None,
        user_override: str | None = None,
    ) -> TemplateDefinition:
        """Select the best template for the given musical parameters.

        Parameters
        ----------
        genre:            Classified genre string (e.g. ``"trap"``).
        vibe:             Classified vibe string (e.g. ``"dark"``).
        energy:           Energy level [0.0, 1.0].
        melodic_richness: Melodic complexity [0.0, 1.0].
        loop_density:     Loop density [0.0, 1.0].
        variation_seed:   Integer seed for deterministic candidate selection.
        user_override:    If set and matches a known template_id, use it directly.

        Returns
        -------
        TemplateDefinition
        """
        # Honour explicit user override if valid
        if user_override and user_override in _TEMPLATE_MAP:
            return _TEMPLATE_MAP[user_override]

        genre_lower = str(genre or "generic").strip().lower()

        if genre_lower == "trap":
            return self._select_trap(energy, melodic_richness, loop_density, variation_seed)
        if genre_lower == "drill":
            return _TEMPLATE_MAP["drill_A"]
        if genre_lower == "rage":
            return _TEMPLATE_MAP["rage_A"]
        if genre_lower == "rnb":
            return _TEMPLATE_MAP["rnb_A"]
        if genre_lower == "west_coast":
            return _TEMPLATE_MAP["west_coast_A"]
        return _TEMPLATE_MAP["generic_A"]

    def all_templates(self) -> list[TemplateDefinition]:
        """Return all registered template definitions."""
        return list(_TEMPLATES)

    # ------------------------------------------------------------------
    # Trap selection logic
    # ------------------------------------------------------------------

    def _select_trap(
        self,
        energy: float,
        melodic_richness: float,
        loop_density: float,
        variation_seed: int | None,
    ) -> TemplateDefinition:
        """Pick among the four trap templates using trait thresholds."""
        candidates: list[str] = []

        # Priority rules — gather all matching candidates
        if melodic_richness > 0.6:
            candidates.append("trap_C")
        if energy > 0.7 and melodic_richness <= 0.6:
            candidates.append("trap_B")
        if loop_density < 0.35:
            candidates.append("trap_D")

        # Default fallback
        if not candidates:
            candidates = ["trap_A"]

        seed = int(variation_seed or 0)
        chosen_id = candidates[seed % len(candidates)]
        return _TEMPLATE_MAP[chosen_id]
