"""
Arranger V2 — role engine.

Responsibilities:
1. Validate incoming stem roles against CANONICAL_ROLES.
2. Reject (raise) stems that have no valid role.
3. Normalise role strings to lowercase canonical form.
4. Return a deduplicated, ordered list of valid ``StemRoleModel`` objects.

This layer runs before planning starts.  If it raises, the arrangement
must not proceed (fail-fast — see validator.py for runtime checks).
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.services.arranger_v2.types import (
    CANONICAL_ROLES,
    ROLE_ENERGY_WEIGHTS,
    StemRoleModel,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role normalisation map
# ---------------------------------------------------------------------------

_ROLE_ALIASES: dict[str, str] = {
    # Common names → canonical
    "kick":       "drums",
    "snare":      "drums",
    "hi_hat":     "drums",
    "hihat":      "drums",
    "hats":       "drums",
    "hat":        "drums",
    "drum":       "drums",
    "808":        "bass",
    "sub":        "bass",
    "lead":       "melody",
    "synth_lead": "melody",
    "piano":      "chords",
    "guitar":     "chords",
    "keys":       "chords",
    "pad":        "pads",
    "string":     "texture",
    "strings":    "texture",
    "atmo":       "texture",
    "atmosphere": "texture",
    "ambience":   "texture",
    "ambient":    "texture",
    "sfx":        "fx",
    "effect":     "fx",
    "effects":    "fx",
    "vox":        "vocal",
    "vocals":     "vocal",
    "harmony":    "vocal",
    "sample":     "texture",
    "perc":       "percussion",
    "full":       "full_mix",
    "loop":       "full_mix",
    "stereo":     "full_mix",
    "mix":        "full_mix",
    "other":      "full_mix",
}


def normalise_role(raw: str) -> str:
    """Return the canonical role string for *raw*, or *raw* itself if unknown."""
    cleaned = str(raw or "").strip().lower()
    return _ROLE_ALIASES.get(cleaned, cleaned)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class RoleValidationError(ValueError):
    """Raised when a stem cannot be assigned a valid role."""


def validate_stem_roles(
    raw_roles: Sequence[str],
    *,
    strict: bool = False,
) -> list[StemRoleModel]:
    """Convert a list of raw role strings into validated ``StemRoleModel`` objects.

    Args:
        raw_roles:  Role strings as they arrive from stem metadata or the request.
        strict:     When True, raise ``RoleValidationError`` for unknown roles
                    instead of logging a warning and skipping them.

    Returns:
        Deduplicated list of ``StemRoleModel`` objects in stable order.

    Raises:
        RoleValidationError: If *strict* is True and any role is unrecognised.
        RoleValidationError: If no valid roles remain after validation.
    """
    seen_ids: set[str] = set()
    models: list[StemRoleModel] = []

    for raw in raw_roles:
        canonical = normalise_role(raw)

        if canonical not in CANONICAL_ROLES:
            msg = (
                f"Role {raw!r} normalises to {canonical!r} which is not in "
                f"CANONICAL_ROLES.  Valid roles: {sorted(CANONICAL_ROLES)}"
            )
            if strict:
                raise RoleValidationError(msg)
            logger.warning("role_engine: skipping unknown role — %s", msg)
            continue

        if canonical in seen_ids:
            continue  # Deduplicate

        seen_ids.add(canonical)
        weight = ROLE_ENERGY_WEIGHTS.get(canonical, 0.5)
        models.append(StemRoleModel(
            stem_id=canonical,
            role=canonical,
            energy_weight=weight,
        ))

    if not models:
        raise RoleValidationError(
            f"No valid roles found in input {list(raw_roles)!r}. "
            f"Every stem must carry a role from {sorted(CANONICAL_ROLES)}."
        )

    return models


def get_valid_role_strings(
    raw_roles: Sequence[str],
    *,
    strict: bool = False,
) -> list[str]:
    """Convenience wrapper returning just the canonical role strings."""
    return [m.role for m in validate_stem_roles(raw_roles, strict=strict)]


def compute_section_energy_weight(roles: list[str]) -> float:
    """Return a 0.0–1.0 composite energy score for *roles*.

    Computed as the mean energy weight of all roles, with a small bonus for
    high-impact roles (drums + bass together add 0.05 bonus).
    """
    if not roles:
        return 0.0
    weights = [ROLE_ENERGY_WEIGHTS.get(r, 0.5) for r in roles]
    base = sum(weights) / len(weights)
    # Bonus: drums and bass together boost perceived energy
    role_set = set(roles)
    if "drums" in role_set and "bass" in role_set:
        base = min(1.0, base + 0.05)
    return round(base, 4)
