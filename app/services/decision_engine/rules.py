"""
Deterministic decision helpers for the Decision Engine.

All functions are pure and stateless — they take explicit inputs and return
explicit outputs with no side effects.  The :class:`DecisionPlanner` calls
these helpers to build its section decisions.
"""

from __future__ import annotations

from typing import List, Optional

# ---------------------------------------------------------------------------
# Source-quality constants
# ---------------------------------------------------------------------------

# Source quality values that are considered "limited" (fallback behaviour).
LIMITED_SOURCE_QUALITIES: frozenset[str] = frozenset(
    {"stereo_fallback", "mono_fallback"}
)

# Minimum number of available roles required to apply non-trivial subtractions.
MIN_ROLES_FOR_SUBTRACTION: int = 2

# Roles considered "core" — these are protected by default in most sections.
CORE_ROLES: frozenset[str] = frozenset({"kick", "bass", "drums", "melody", "lead"})

# Roles considered "non-core" — candidates for hold-back / removal.
NON_CORE_ROLES: frozenset[str] = frozenset(
    {
        "chords",
        "pad",
        "fx",
        "hi_hat",
        "perc",
        "synth",
        "texture",
        "arp",
        "counter_melody",
        "atmos",
    }
)


# ---------------------------------------------------------------------------
# Role selection helpers
# ---------------------------------------------------------------------------


def choose_roles_to_hold_back(
    available_roles: List[str],
    source_quality: str,
    section_type: str,
    occurrence_index: int,
    already_held_back: Optional[List[str]] = None,
) -> List[str]:
    """Choose which roles to hold back for a given section.

    Hold-back candidates are non-core roles not already withheld.  For limited
    source material we are more conservative and hold back at most one role.

    Parameters
    ----------
    available_roles:
        All instrument roles present in the source material.
    source_quality:
        Source quality mode (e.g. ``"true_stems"``).
    section_type:
        Canonical section type (e.g. ``"intro"``, ``"verse"``).
    occurrence_index:
        0-based index of this section type's occurrence.
    already_held_back:
        Roles already being held back from a prior section.

    Returns
    -------
    list[str]
        Ordered list of roles to hold back.
    """
    if already_held_back is None:
        already_held_back = []

    if len(available_roles) < MIN_ROLES_FOR_SUBTRACTION:
        return []

    held_set = set(already_held_back)
    candidates = [
        r for r in available_roles
        if r in NON_CORE_ROLES and r not in held_set
    ]

    # In limited quality mode, hold back at most one role.
    is_limited = source_quality in LIMITED_SOURCE_QUALITIES
    max_hold = 1 if is_limited else _max_hold_back_for_section(section_type, occurrence_index)

    return candidates[:max_hold]


def _max_hold_back_for_section(section_type: str, occurrence_index: int) -> int:
    """Return the maximum number of roles to hold back for a section type."""
    limits: dict[str, int] = {
        "intro": 3,
        "verse": 2,
        "pre_hook": 1,
        "hook": 0,        # hooks reintroduce; they don't add new hold-backs
        "bridge": 2,
        "breakdown": 3,
        "outro": 2,
    }
    base = limits.get(section_type, 1)
    # First occurrence of verse is more restrained.
    if section_type == "verse" and occurrence_index == 0:
        base = max(base, 2)
    return base


def choose_roles_to_remove_for_tension(
    available_roles: List[str],
    source_quality: str,
    currently_held_back: Optional[List[str]] = None,
) -> List[str]:
    """Choose a role to temporarily remove for tension (e.g. pre-hook).

    Targets at most one anchor role that is not in the hold-back list.
    An "anchor role" here is something the listener expects — kicking out a
    drum or bass briefly creates maximum tension before the hook.

    Parameters
    ----------
    available_roles:
        Roles currently active.
    source_quality:
        Source quality mode.
    currently_held_back:
        Roles already held back (exclude these from removal candidates).

    Returns
    -------
    list[str]
        Zero or one role to remove for tension.
    """
    if currently_held_back is None:
        currently_held_back = []

    if len(available_roles) < MIN_ROLES_FOR_SUBTRACTION:
        return []

    held_set = set(currently_held_back)
    # Prefer to remove a non-core anchor (chords, pad) then hi_hat/perc.
    # Avoid removing the core rhythm section if there are safer options.
    tension_candidates = [
        r for r in ["chords", "pad", "hi_hat", "perc", "synth", "arp"]
        if r in available_roles and r not in held_set
    ]
    if tension_candidates:
        return [tension_candidates[0]]

    # As a fallback try any non-core role not already held.
    for role in available_roles:
        if role not in CORE_ROLES and role not in held_set:
            return [role]

    return []


def choose_roles_to_reintroduce(
    held_back_roles: List[str],
    section_type: str,
    source_quality: str,
    occurrence_index: int = 0,
) -> List[str]:
    """Choose which held-back roles to reintroduce for a payoff section.

    For the first hook we release everything held back.  For subsequent hooks
    we selectively release to create variation.

    Parameters
    ----------
    held_back_roles:
        Roles currently being held back.
    section_type:
        Canonical section type.
    source_quality:
        Source quality mode.
    occurrence_index:
        0-based index of this section type's occurrence.

    Returns
    -------
    list[str]
        Ordered list of roles to reintroduce.
    """
    if not held_back_roles:
        return []

    is_limited = source_quality in LIMITED_SOURCE_QUALITIES

    if section_type == "hook":
        if occurrence_index == 0:
            # First hook: release all held-back material for maximum payoff.
            return list(held_back_roles)
        elif occurrence_index == 1:
            # Second hook: release all if material is available, else most.
            return list(held_back_roles)
        else:
            # Third+ hook: release everything for climax.
            return list(held_back_roles)

    if section_type == "verse" and occurrence_index > 0:
        # Verse 2+: allow one strategic reintroduction.
        if not is_limited and held_back_roles:
            return [held_back_roles[0]]

    return []


def section_can_allow_full_stack(
    section_type: str,
    source_quality: str,
    available_roles: List[str],
    occurrence_index: int = 0,
    prior_hook_fullness: Optional[str] = None,
) -> bool:
    """Determine whether a section may use the full role stack simultaneously.

    Parameters
    ----------
    section_type:
        Canonical section type.
    source_quality:
        Source quality mode.
    available_roles:
        All available instrument roles.
    occurrence_index:
        0-based index of this section type's occurrence.
    prior_hook_fullness:
        The fullness label of the prior hook, or ``None``.

    Returns
    -------
    bool
        True when full stack is permitted.
    """
    is_limited = source_quality in LIMITED_SOURCE_QUALITIES
    enough_roles = len(available_roles) >= MIN_ROLES_FOR_SUBTRACTION

    # Hard constraints: these sections must NEVER go full stack (unless limited).
    if section_type in ("intro", "verse") and not is_limited:
        if section_type == "verse" and occurrence_index == 0:
            return False
        if section_type == "intro":
            return False

    if section_type == "pre_hook":
        # Pre-hook explicitly suppresses full stack to create tension.
        return False

    if section_type == "bridge" and enough_roles:
        return False

    if section_type == "outro":
        # Outro resolves downward — no full stack.
        return False

    if section_type == "breakdown":
        return False

    if section_type == "hook":
        # Allow full stack at hook unless extremely limited.
        return True

    if section_type == "verse" and occurrence_index > 0:
        # Verse 2+: still not full, but slightly more generous than Verse 1.
        return False

    # Default: allow if enough material.
    return enough_roles


def compute_target_fullness(
    section_type: str,
    source_quality: str,
    available_roles: List[str],
    occurrence_index: int = 0,
    held_back_count: int = 0,
) -> str:
    """Compute the target fullness label for a section.

    Parameters
    ----------
    section_type:
        Canonical section type.
    source_quality:
        Source quality mode.
    available_roles:
        All available roles.
    occurrence_index:
        0-based occurrence index.
    held_back_count:
        Number of roles currently being held back.

    Returns
    -------
    str
        One of ``"sparse"``, ``"medium"``, or ``"full"``.
    """
    is_limited = source_quality in LIMITED_SOURCE_QUALITIES

    if is_limited:
        # With limited material we can't go below medium safely.
        if section_type in ("hook",):
            return "full"
        return "medium"

    if section_type == "intro":
        return "sparse"
    if section_type == "verse":
        if occurrence_index == 0:
            return "sparse" if held_back_count >= 1 else "medium"
        return "medium"
    if section_type == "pre_hook":
        return "sparse"
    if section_type == "hook":
        if occurrence_index == 0:
            return "full"
        return "full"
    if section_type == "bridge":
        return "sparse"
    if section_type == "breakdown":
        return "sparse"
    if section_type == "outro":
        return "sparse" if occurrence_index == 0 else "sparse"

    return "medium"


def should_force_bridge_reset(
    section_type: str,
    prior_hook_fullness: Optional[str],
    source_quality: str,
    available_roles: List[str],
) -> bool:
    """Return True when the bridge/breakdown must be explicitly reset.

    Parameters
    ----------
    section_type:
        Canonical section type.
    prior_hook_fullness:
        Fullness of the most recent hook, or ``None``.
    source_quality:
        Source quality mode.
    available_roles:
        All available roles.

    Returns
    -------
    bool
        True when the bridge needs an explicit density reset.
    """
    if section_type not in ("bridge", "breakdown"):
        return False
    # If a full hook preceded the bridge, a reset is always needed.
    if prior_hook_fullness == "full":
        return True
    # If there's enough material to create contrast, force it.
    if len(available_roles) >= MIN_ROLES_FOR_SUBTRACTION:
        return True
    return False


def should_force_outro_resolution(
    section_type: str,
    current_fullness: str,
    source_quality: str,
) -> bool:
    """Return True when the outro must progressively remove weight.

    Parameters
    ----------
    section_type:
        Canonical section type.
    current_fullness:
        Fullness label already assigned to the outro.
    source_quality:
        Source quality mode.

    Returns
    -------
    bool
        True when the outro needs an explicit resolution action.
    """
    if section_type != "outro":
        return False
    # Outro should never end on full or medium when material is available.
    if current_fullness in ("full", "medium"):
        return True
    return False
