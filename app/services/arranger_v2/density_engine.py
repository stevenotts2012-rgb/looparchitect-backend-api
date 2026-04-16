"""
Arranger V2 — density engine.

Core stem selection logic.  Given a pool of validated roles, a target density,
and the current arrangement state, this module selects the specific roles that
should be active in a section.

Design rules:
- Must respect section roles (preference order per section type).
- Must not exceed target density threshold.
- Must avoid previously used combinations when alternatives exist.
- Deterministic: same inputs always produce the same outputs.
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.services.arranger_v2.state import ArrangerState
from app.services.arranger_v2.types import CANONICAL_ROLES, ROLE_ENERGY_WEIGHTS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-section type role preference tables
# ---------------------------------------------------------------------------

# Priority-ordered groups per section type.  The density engine picks the top
# roles according to the target density, always honouring this order.
_SECTION_ROLE_PRIORITY: dict[str, list[list[str]]] = {
    "intro": [
        ["pads", "texture"],
        ["melody", "arp", "synth"],
        ["fx"],
        ["vocal"],
        ["full_mix"],
    ],
    "verse": [
        ["drums", "percussion"],
        ["bass"],
        ["melody", "synth", "arp"],
        ["chords", "pads"],
        ["vocal"],
        ["fx"],
    ],
    "pre_hook": [
        ["drums", "percussion"],
        ["bass"],
        ["melody", "arp"],
        ["fx"],
        ["vocal"],
        ["chords", "pads"],
    ],
    "hook": [
        ["drums", "percussion"],
        ["bass"],
        ["melody", "synth"],
        ["vocal"],
        ["chords", "pads"],
        ["arp"],
        ["fx"],
        ["texture"],
    ],
    "bridge": [
        ["pads", "texture"],
        ["melody", "arp"],
        ["vocal"],
        ["fx"],
        ["chords"],
        ["bass"],
    ],
    "breakdown": [
        ["pads", "texture"],
        ["fx"],
        ["melody"],
        ["vocal"],
    ],
    "outro": [
        ["melody", "arp"],
        ["pads", "texture"],
        ["fx"],
        ["vocal"],
        ["bass"],
    ],
}

# Roles that are forbidden in certain section types.
_SECTION_ROLE_EXCLUSIONS: dict[str, frozenset[str]] = {
    "intro":     frozenset({"drums", "percussion", "bass"}),
    "verse":     frozenset(),
    "pre_hook":  frozenset(),   # drums stay in pre_hook — it's a tension ramp, not a rest
    "hook":      frozenset(),
    "bridge":    frozenset({"drums", "percussion", "bass"}),
    "breakdown": frozenset({"drums", "percussion", "bass"}),
    "outro":     frozenset(),
}

# Min / max active layers per section type.
_SECTION_LAYER_BOUNDS: dict[str, tuple[int, int]] = {
    "intro":     (1, 3),
    "verse":     (2, 4),
    "pre_hook":  (2, 4),
    "hook":      (3, 6),
    "bridge":    (1, 3),
    "breakdown": (1, 2),
    "outro":     (1, 3),
}


# ---------------------------------------------------------------------------
# Density thresholds
# ---------------------------------------------------------------------------

def density_label_to_float(label: str) -> float:
    """Convert a density label to a 0.0–1.0 float."""
    return {"sparse": 0.30, "medium": 0.60, "full": 1.00}.get(label, 0.60)


def density_float_to_label(value: float) -> str:
    """Convert a 0.0–1.0 density float to a label."""
    if value <= 0.35:
        return "sparse"
    if value <= 0.70:
        return "medium"
    return "full"


# ---------------------------------------------------------------------------
# Core selection function
# ---------------------------------------------------------------------------

def select_stems_for_section(
    available_roles: Sequence[str],
    section_type: str,
    target_density: float,
    state: ArrangerState,
    *,
    occurrence: int = 1,
    force_distinct: bool = True,
) -> list[str]:
    """Select active roles for *section_type* respecting density and state.

    Args:
        available_roles:  Full set of validated role strings available.
        section_type:     Canonical section type from SECTION_TYPES.
        target_density:   0.0–1.0 target density for this section.
        state:            Current arrangement state (used to avoid repeats).
        occurrence:       1-based occurrence count within this section type.
        force_distinct:   When True, attempt to return a role set different
                          from any prior occurrence of the same section type.

    Returns:
        Ordered list of role strings for this section.
    """
    # Resolve type alias edge cases
    section_type = _normalise_section_type(section_type)

    available = [r for r in available_roles if r in CANONICAL_ROLES]
    if not available:
        logger.warning("density_engine: no valid roles in available_roles=%s", list(available_roles))
        return []

    excluded = _SECTION_ROLE_EXCLUSIONS.get(section_type, frozenset())
    eligible = [r for r in available if r not in excluded]

    # Fall back to full available set if exclusions removed everything.
    if not eligible:
        eligible = list(available)

    min_layers, max_layers = _SECTION_LAYER_BOUNDS.get(section_type, (1, 4))

    # Scale max_layers with target_density.
    density_cap = max(min_layers, round(target_density * max_layers))
    effective_max = min(max_layers, density_cap)

    selected = _apply_priority_selection(eligible, section_type, effective_max)
    selected = _enforce_min_layers(selected, eligible, min_layers)

    # Attempt to make this selection distinct from prior occurrences.
    if force_distinct and occurrence > 1:
        selected = _differentiate_from_prior(
            selected, eligible, section_type, state, effective_max
        )

    return selected


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_section_type(section_type: str) -> str:
    value = str(section_type or "verse").strip().lower()
    if value in {"chorus", "drop"}:
        return "hook"
    if value in {"buildup", "build_up", "build", "prehook", "pre-hook"}:
        return "pre_hook"
    if value == "break":
        return "breakdown"
    return value


def _apply_priority_selection(
    eligible: list[str],
    section_type: str,
    effective_max: int,
) -> list[str]:
    """Select roles from eligible using the priority table for section_type."""
    priority_groups = _SECTION_ROLE_PRIORITY.get(
        section_type,
        _SECTION_ROLE_PRIORITY["verse"],
    )
    selected: list[str] = []
    eligible_set = set(eligible)

    for group in priority_groups:
        if len(selected) >= effective_max:
            break
        for role in group:
            if role in eligible_set and role not in selected:
                selected.append(role)
                break  # Take at most one from each priority group

    # If still short of effective_max, pull from remaining eligible roles.
    if len(selected) < effective_max:
        remaining = [r for r in eligible if r not in selected]
        selected.extend(remaining[: effective_max - len(selected)])

    return selected[:effective_max]


def _enforce_min_layers(
    selected: list[str],
    eligible: list[str],
    min_layers: int,
) -> list[str]:
    """Ensure at least *min_layers* roles are present."""
    if len(selected) >= min_layers:
        return selected
    extra = [r for r in eligible if r not in selected]
    needed = min_layers - len(selected)
    return selected + extra[:needed]


def _differentiate_from_prior(
    selected: list[str],
    eligible: list[str],
    section_type: str,
    state: ArrangerState,
    effective_max: int,
) -> list[str]:
    """Attempt to produce a role set distinct from all prior occurrences.

    If the selected set is already unique, return it unchanged.  Otherwise
    try swapping one or two roles to break the match.  Fall back to the
    original selection only if no distinct alternative exists.
    """
    if not state.is_combo_used(section_type, selected):
        return selected

    # Try rotating one role at a time.
    unused = [r for r in eligible if r not in selected]
    for swap_out in reversed(selected):
        for swap_in in unused:
            candidate = [r for r in selected if r != swap_out] + [swap_in]
            candidate = candidate[:effective_max]
            if not state.is_combo_used(section_type, candidate):
                logger.debug(
                    "density_engine: differentiated %s combo: swapped %s → %s",
                    section_type,
                    swap_out,
                    swap_in,
                )
                return candidate

    # No distinct swap found — log and return original.
    logger.debug(
        "density_engine: cannot differentiate %s combo (limited stems)", section_type
    )
    return selected
