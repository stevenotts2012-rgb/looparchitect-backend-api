"""
Arranger V2 — transition engine.

Selects the appropriate transition type at every section boundary.

Rules:
- Every section boundary must have a transition (no hard cuts allowed).
- Hooks MUST be preceded by a riser or silence_gap.
- Energy-increasing boundaries get build-up transitions.
- Energy-decreasing boundaries get subtractive or stripping transitions.
- Transitions are planning-only (no DSP computed here).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transition maps
# ---------------------------------------------------------------------------

# Default transition-in per destination section type.
_DEFAULT_TRANSITION_IN: dict[str, str] = {
    "intro":      "none",
    "verse":      "drum_fill",
    "pre_hook":   "riser",
    "hook":       "riser",
    "bridge":     "subtractive_entry",
    "breakdown":  "silence_gap",
    "outro":      "subtractive_entry",
}

# Default transition-out per source section type.
_DEFAULT_TRANSITION_OUT: dict[str, str] = {
    "intro":      "drum_fill",
    "verse":      "riser",
    "pre_hook":   "reverse_fx",
    "hook":       "none",
    "bridge":     "riser",
    "breakdown":  "riser",
    "outro":      "none",
}

# Mandatory transitions when entering specific destinations, regardless of source.
_MANDATORY_TRANSITION_IN: dict[str, str] = {
    "hook": "riser",      # Hooks MUST have riser before them
    "breakdown": "silence_gap",  # Breakdowns MUST have a silence/breath
}


def select_transition_in(
    from_section_type: str | None,
    to_section_type: str,
    from_energy: int | None,
    to_energy: int,
) -> str:
    """Select the transition type entering *to_section_type*.

    Args:
        from_section_type:  Source section type, or None for the first section.
        to_section_type:    Destination section type.
        from_energy:        Energy of the source section (1–5), or None.
        to_energy:          Energy of the destination section (1–5).

    Returns:
        Transition type string (always a value from TRANSITION_TYPES).
    """
    if from_section_type is None:
        # First section in arrangement — no transition needed.
        return "none"

    # Mandatory overrides: certain destinations always require specific transitions.
    if to_section_type in _MANDATORY_TRANSITION_IN:
        return _MANDATORY_TRANSITION_IN[to_section_type]

    # Energy-aware selection.
    if from_energy is not None:
        energy_delta = to_energy - from_energy

        # Significant energy ramp → build-up transition.
        if energy_delta >= 2:
            return _energy_ramp_transition(from_section_type, to_section_type)

        # Significant energy drop → subtractive transition.
        if energy_delta <= -2:
            return _energy_drop_transition(from_section_type, to_section_type)

    # Default transition for the destination type.
    return _DEFAULT_TRANSITION_IN.get(to_section_type, "drum_fill")


def select_transition_out(
    from_section_type: str,
    to_section_type: str | None,
    from_energy: int,
    to_energy: int | None,
) -> str:
    """Select the transition type leaving *from_section_type*.

    Args:
        from_section_type:  Source section type.
        to_section_type:    Next section type, or None if this is the last section.
        from_energy:        Energy of the source section (1–5).
        to_energy:          Energy of the next section (1–5), or None.

    Returns:
        Transition type string.
    """
    if to_section_type is None:
        # Last section — fade out.
        return "none"

    # If next section is a hook, ramp up.
    if to_section_type == "hook":
        return "riser"

    # If next section is a breakdown/bridge, strip down.
    if to_section_type in {"breakdown", "bridge", "outro"}:
        return "subtractive_entry"

    # Default out-transition for this section type.
    return _DEFAULT_TRANSITION_OUT.get(from_section_type, "none")


def build_transition_plan(
    section_types: list[str],
    energy_curve: list[int],
) -> list[dict]:
    """Build the full transition plan for an arrangement.

    Args:
        section_types:  Ordered list of section type strings.
        energy_curve:   Corresponding ordered list of energy integers (1–5).

    Returns:
        List of transition dicts, one per section boundary.
        Each dict has keys: index, from_type, to_type, transition_in,
        transition_out, from_energy, to_energy, intensity.
    """
    if len(section_types) != len(energy_curve):
        raise ValueError(
            f"section_types and energy_curve must have the same length, "
            f"got {len(section_types)} and {len(energy_curve)}"
        )

    plan: list[dict] = []
    for i in range(len(section_types)):
        prev_type = section_types[i - 1] if i > 0 else None
        prev_energy = energy_curve[i - 1] if i > 0 else None
        next_type = section_types[i + 1] if i < len(section_types) - 1 else None
        next_energy = energy_curve[i + 1] if i < len(energy_curve) - 1 else None

        t_in = select_transition_in(
            from_section_type=prev_type,
            to_section_type=section_types[i],
            from_energy=prev_energy,
            to_energy=energy_curve[i],
        )
        t_out = select_transition_out(
            from_section_type=section_types[i],
            to_section_type=next_type,
            from_energy=energy_curve[i],
            to_energy=next_energy,
        )

        # Compute intensity from energy delta.
        energy_delta = 0
        if prev_energy is not None:
            energy_delta = energy_curve[i] - prev_energy
        intensity = min(1.0, max(0.3, 0.5 + abs(energy_delta) * 0.1))

        plan.append({
            "index": i,
            "from_type": prev_type or "",
            "to_type": section_types[i],
            "transition_in": t_in,
            "transition_out": t_out,
            "from_energy": prev_energy,
            "to_energy": energy_curve[i],
            "intensity": round(intensity, 2),
        })

    return plan


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _energy_ramp_transition(from_type: str, to_type: str) -> str:
    """Best transition when energy ramps up significantly."""
    if to_type == "hook":
        return "riser"
    if from_type == "pre_hook":
        return "reverse_fx"
    return "drum_fill"


def _energy_drop_transition(from_type: str, to_type: str) -> str:
    """Best transition when energy drops significantly."""
    if to_type in {"bridge", "breakdown"}:
        return "silence_gap"
    return "subtractive_entry"
