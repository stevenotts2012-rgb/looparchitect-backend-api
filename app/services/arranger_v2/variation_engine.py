"""
Arranger V2 — variation engine.

Determines how a repeated section should differ from its first occurrence.
This is a planning-only layer; it returns a strategy name and updated role
list.  DSP effects (fills, filter sweeps) are applied by the render executor.

Strategies:
- drop_kick       Remove the kick/drums role temporarily for tension.
- add_percussion  Layer in percussion to increase rhythmic complexity.
- layer_extra     Add one more role than the previous occurrence.
- filter          Mark for filter sweep DSP during render.
- role_rotation   Swap one support role for an unused one.
- support_swap    Explicitly rotate support roles between occurrences.
- change_pattern  Swap the primary melodic role for a different melodic role.
- half_time       Hint to the renderer to drop rhythmic density to half-time feel.
- none            No change applied.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.services.arranger_v2.state import ArrangerState
from app.services.arranger_v2.types import VARIATION_STRATEGIES

logger = logging.getLogger(__name__)


# Roles whose absence signals meaningful section contrast.
_RHYTHMIC_ROLES: frozenset[str] = frozenset({"drums", "percussion"})
_MELODIC_ROLES:  frozenset[str] = frozenset({"melody", "synth", "arp", "chords"})


def apply_variation(
    section_type: str,
    occurrence: int,
    current_roles: list[str],
    prev_roles: list[str],
    available_roles: list[str],
    state: ArrangerState,
) -> tuple[list[str], str]:
    """Compute a varied role set for a repeated section.

    Rules:
    - verse_2 must differ from verse_1 (at least one role change).
    - hook_2 must feel larger than hook_1 (more roles or stronger roles).
    - The strategy applied must not be the same as the last strategy used
      for this section type (avoid predictable pattern).

    Args:
        section_type:    Canonical section type.
        occurrence:      1-based occurrence count (this is the *new* occurrence).
        current_roles:   Roles currently selected for this section.
        prev_roles:      Roles used in the most recent prior occurrence.
        available_roles: All available roles for this arrangement.
        state:           Current arrangement state.

    Returns:
        Tuple of (updated_roles, strategy_name).
    """
    if occurrence <= 1:
        return current_roles, "none"

    # Determine which strategies have already been used for this section.
    last_strategy = state.last_variation_for(section_type)

    # -------------------------------------------------------------------------
    # hook-specific: hook_2+ must feel larger
    # -------------------------------------------------------------------------
    if section_type == "hook" and occurrence >= 2:
        return _hook_escalation(
            current_roles, prev_roles, available_roles, last_strategy
        )

    # -------------------------------------------------------------------------
    # verse_2: must differ — try role_rotation first
    # -------------------------------------------------------------------------
    if section_type in {"verse", "pre_hook"}:
        return _verse_variation(
            current_roles, prev_roles, available_roles, last_strategy
        )

    # -------------------------------------------------------------------------
    # Generic repeated section
    # -------------------------------------------------------------------------
    return _generic_variation(
        section_type, current_roles, prev_roles, available_roles, last_strategy
    )


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

def _hook_escalation(
    current_roles: list[str],
    prev_roles: list[str],
    available_roles: list[str],
    last_strategy: str,
) -> tuple[list[str], str]:
    """Hook 2+ must feel larger than Hook 1."""
    current_set = set(current_roles)
    prev_set = set(prev_roles)
    available_set = set(available_roles)
    unused = sorted(available_set - current_set)

    # Try layer_extra: add one more role.
    if unused and last_strategy != "layer_extra":
        new_role = _pick_high_energy(unused)
        if new_role:
            return list(current_roles) + [new_role], "layer_extra"

    # Try role_rotation: swap a support role for a new one.
    if last_strategy not in ("role_rotation", "support_swap"):
        result, strategy = _try_role_rotation(current_roles, prev_roles, available_roles)
        if strategy != "none":
            return result, strategy

    # If hook already has drums and bass, add a melodic layer.
    if not current_set & _MELODIC_ROLES:
        melodic = [r for r in available_roles if r in _MELODIC_ROLES and r not in current_set]
        if melodic:
            return list(current_roles) + melodic[:1], "layer_extra"

    return current_roles, "none"


def _verse_variation(
    current_roles: list[str],
    prev_roles: list[str],
    available_roles: list[str],
    last_strategy: str,
) -> tuple[list[str], str]:
    """Verse/pre_hook repeat must differ by at least one role."""
    current_set = set(current_roles)
    prev_set = set(prev_roles)

    # Already different — no change needed, but record it.
    if current_set != prev_set:
        strategy = _infer_strategy_from_diff(current_set, prev_set)
        return current_roles, strategy

    available_set = set(available_roles)
    unused = sorted(available_set - current_set)

    # Try add_percussion.
    if last_strategy != "add_percussion":
        for r in unused:
            if r == "percussion":
                return list(current_roles) + [r], "add_percussion"

    # Try role_rotation.
    if last_strategy not in ("role_rotation", "support_swap"):
        result, strategy = _try_role_rotation(current_roles, prev_roles, available_roles)
        if strategy != "none":
            return result, strategy

    # Try change_pattern: swap primary melodic role.
    if last_strategy != "change_pattern":
        result, strategy = _try_change_pattern(current_roles, available_roles)
        if strategy != "none":
            return result, strategy

    # Last resort: drop_kick for a felt-absence variation.
    if "drums" in current_set and last_strategy != "drop_kick":
        new_roles = [r for r in current_roles if r != "drums"]
        if new_roles:
            return new_roles, "drop_kick"

    return current_roles, "none"


def _generic_variation(
    section_type: str,
    current_roles: list[str],
    prev_roles: list[str],
    available_roles: list[str],
    last_strategy: str,
) -> tuple[list[str], str]:
    """Generic variation for any repeated section."""
    current_set = set(current_roles)
    prev_set = set(prev_roles)

    if current_set != prev_set:
        return current_roles, _infer_strategy_from_diff(current_set, prev_set)

    # Prefer role_rotation as general-purpose strategy.
    result, strategy = _try_role_rotation(current_roles, prev_roles, available_roles)
    if strategy != "none":
        return result, strategy

    return current_roles, "none"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_role_rotation(
    current_roles: list[str],
    prev_roles: list[str],
    available_roles: list[str],
) -> tuple[list[str], str]:
    """Attempt to swap one support role to differentiate from previous."""
    current_set = set(current_roles)
    available_set = set(available_roles)
    unused = sorted(available_set - current_set)
    if not unused:
        return current_roles, "none"

    # Find a non-rhythmic, non-critical role that can be swapped out.
    swap_candidates = [r for r in current_roles if r not in _RHYTHMIC_ROLES]
    if not swap_candidates:
        return current_roles, "none"

    swap_out = swap_candidates[-1]  # Remove the last non-critical role
    swap_in = unused[0]             # Add the first unused role
    new_roles = [r for r in current_roles if r != swap_out] + [swap_in]
    return new_roles, "role_rotation"


def _try_change_pattern(
    current_roles: list[str],
    available_roles: list[str],
) -> tuple[list[str], str]:
    """Try swapping a melodic role for a different one."""
    current_melodic = [r for r in current_roles if r in _MELODIC_ROLES]
    available_melodic = [r for r in available_roles if r in _MELODIC_ROLES]
    unused_melodic = [r for r in available_melodic if r not in current_roles]
    if not current_melodic or not unused_melodic:
        return current_roles, "none"

    swap_out = current_melodic[-1]
    swap_in = unused_melodic[0]
    new_roles = [r if r != swap_out else swap_in for r in current_roles]
    return new_roles, "change_pattern"


def _pick_high_energy(roles: list[str]) -> Optional[str]:
    """Return the role with the highest energy weight from *roles*."""
    if not roles:
        return None
    from app.services.arranger_v2.types import ROLE_ENERGY_WEIGHTS
    return max(roles, key=lambda r: ROLE_ENERGY_WEIGHTS.get(r, 0.5))


def _infer_strategy_from_diff(
    current_set: set[str],
    prev_set: set[str],
) -> str:
    """Infer the most likely strategy name from the difference between two role sets."""
    introduced = current_set - prev_set
    dropped = prev_set - current_set

    if "drums" in dropped:
        return "drop_kick"
    if "percussion" in introduced:
        return "add_percussion"
    if introduced and not dropped:
        return "layer_extra"
    if introduced and dropped:
        if introduced & _MELODIC_ROLES or dropped & _MELODIC_ROLES:
            return "change_pattern"
        return "role_rotation"
    return "none"
