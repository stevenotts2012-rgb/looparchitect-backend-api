"""
Deterministic motif transformation selection for the Motif Engine.

Each public function builds a :class:`~app.services.motif_engine.types.MotifTransformation`
for a specific named transformation.  Selection of *which* transformation to
apply is performed by :func:`select_transformations`, which is deterministic —
same inputs always produce the same result.

No uncontrolled randomness is used anywhere in this module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.motif_engine.types import MotifTransformation


# ---------------------------------------------------------------------------
# Individual transformation builders
# ---------------------------------------------------------------------------


def simplify(
    intensity: float = 0.4,
    parameters: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> MotifTransformation:
    """Reduced / stripped-back motif statement."""
    return MotifTransformation(
        transformation_type="simplify",
        intensity=intensity,
        parameters=parameters or {"reduction": "strip_ornaments"},
        notes=notes,
    )


def delay_entry(
    intensity: float = 0.5,
    parameters: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> MotifTransformation:
    """Motif enters later in the bar — creates anticipation."""
    return MotifTransformation(
        transformation_type="delay_entry",
        intensity=intensity,
        parameters=parameters or {"entry_offset_beats": 2},
        notes=notes,
    )


def octave_lift(
    intensity: float = 0.8,
    parameters: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> MotifTransformation:
    """Motif raised one octave for a high-energy statement."""
    return MotifTransformation(
        transformation_type="octave_lift",
        intensity=intensity,
        parameters=parameters or {"octave_shift": 1},
        notes=notes,
    )


def sparse_phrase(
    intensity: float = 0.35,
    parameters: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> MotifTransformation:
    """Only key notes of the motif retained — most notes removed."""
    return MotifTransformation(
        transformation_type="sparse_phrase",
        intensity=intensity,
        parameters=parameters or {"density": "low"},
        notes=notes,
    )


def full_phrase(
    intensity: float = 0.9,
    parameters: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> MotifTransformation:
    """Complete motif statement — fullest form."""
    return MotifTransformation(
        transformation_type="full_phrase",
        intensity=intensity,
        parameters=parameters or {"density": "full"},
        notes=notes,
    )


def call_response(
    intensity: float = 0.75,
    parameters: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> MotifTransformation:
    """Motif split into call and answer phrases."""
    return MotifTransformation(
        transformation_type="call_response",
        intensity=intensity,
        parameters=parameters or {"response_offset_bars": 2},
        notes=notes,
    )


def texture_only(
    intensity: float = 0.25,
    parameters: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> MotifTransformation:
    """Motif present only as textural background — no clear melodic statement."""
    return MotifTransformation(
        transformation_type="texture_only",
        intensity=intensity,
        parameters=parameters or {"presence": "background"},
        notes=notes,
    )


def counter_variant(
    intensity: float = 0.65,
    parameters: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> MotifTransformation:
    """Countermelodic variation of the main motif."""
    return MotifTransformation(
        transformation_type="counter_variant",
        intensity=intensity,
        parameters=parameters or {"inversion": True},
        notes=notes,
    )


def rhythm_trim(
    intensity: float = 0.45,
    parameters: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> MotifTransformation:
    """Motif rhythmically shortened — only first beats retained."""
    return MotifTransformation(
        transformation_type="rhythm_trim",
        intensity=intensity,
        parameters=parameters or {"trim_bars": 1},
        notes=notes,
    )


def sustain_expand(
    intensity: float = 0.85,
    parameters: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> MotifTransformation:
    """Motif notes held longer — swells and resolves smoothly."""
    return MotifTransformation(
        transformation_type="sustain_expand",
        intensity=intensity,
        parameters=parameters or {"sustain_multiplier": 1.5},
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Deterministic transformation selector
# ---------------------------------------------------------------------------

# Transformation sequences indexed by (section_type, occurrence_index).
# Each entry is a list of builder-call tuples: (fn, kwargs).
# When occurrence_index >= len(sequence), the last entry is used.
_TRANSFORMATION_TABLE: Dict[str, List[List[MotifTransformation]]] = {}


def _build_table() -> None:
    """Populate the static transformation table.  Called once at import time."""
    global _TRANSFORMATION_TABLE

    _TRANSFORMATION_TABLE = {
        # ------------------------------------------------------------------
        # intro — tease or sparse motif; never full statement
        # ------------------------------------------------------------------
        "intro": [
            # occurrence 0
            [sparse_phrase(intensity=0.30, notes="intro_tease")],
            # occurrence 1+
            [delay_entry(intensity=0.35, notes="intro_delayed_tease"), texture_only(intensity=0.20)],
        ],
        # ------------------------------------------------------------------
        # verse — partial or restrained motif
        # ------------------------------------------------------------------
        "verse": [
            # occurrence 0
            [simplify(intensity=0.45, notes="verse_restrained")],
            # occurrence 1
            [rhythm_trim(intensity=0.40, notes="verse_trimmed")],
            # occurrence 2+
            [sparse_phrase(intensity=0.35, notes="verse_sparse"), simplify(intensity=0.40)],
        ],
        # ------------------------------------------------------------------
        # pre_hook — building anticipation; slightly stronger than verse
        # ------------------------------------------------------------------
        "pre_hook": [
            # occurrence 0
            [delay_entry(intensity=0.55, notes="pre_hook_delayed")],
            # occurrence 1
            [rhythm_trim(intensity=0.50), call_response(intensity=0.60, notes="pre_hook_call_response")],
            # occurrence 2+
            [simplify(intensity=0.50), delay_entry(intensity=0.55)],
        ],
        # ------------------------------------------------------------------
        # hook — fullest motif statement; escalates with repetitions
        # ------------------------------------------------------------------
        "hook": [
            # occurrence 0 — first hook: full statement
            [full_phrase(intensity=0.90, notes="hook_full")],
            # occurrence 1 — second hook: lifted for payoff escalation
            [full_phrase(intensity=0.92), octave_lift(intensity=0.80, notes="hook_lifted")],
            # occurrence 2 — third hook: transformed payoff
            [call_response(intensity=0.85, notes="hook_call_response"), full_phrase(intensity=0.95)],
            # occurrence 3+ — maximum payoff
            [octave_lift(intensity=0.90), sustain_expand(intensity=0.85, notes="hook_sustained")],
        ],
        # ------------------------------------------------------------------
        # bridge — motif variation; stripped or counter-version
        # ------------------------------------------------------------------
        "bridge": [
            # occurrence 0
            [counter_variant(intensity=0.60, notes="bridge_counter")],
            # occurrence 1+
            [sparse_phrase(intensity=0.40, notes="bridge_stripped"), texture_only(intensity=0.25)],
        ],
        # ------------------------------------------------------------------
        # breakdown — minimal; texture only or sparse
        # ------------------------------------------------------------------
        "breakdown": [
            # occurrence 0
            [texture_only(intensity=0.30, notes="breakdown_texture")],
            # occurrence 1+
            [sparse_phrase(intensity=0.25), texture_only(intensity=0.20)],
        ],
        # ------------------------------------------------------------------
        # outro — resolve and reduce; never re-use full hook motif
        # ------------------------------------------------------------------
        "outro": [
            # occurrence 0
            [rhythm_trim(intensity=0.35, notes="outro_resolve"), simplify(intensity=0.30)],
            # occurrence 1+
            [sustain_expand(intensity=0.40, notes="outro_sustain_resolve"), rhythm_trim(intensity=0.30)],
        ],
    }


_build_table()


def select_transformations(
    section_type: str,
    occurrence_index: int,
    source_quality: str = "true_stems",
    available_roles: Optional[List[str]] = None,
    energy: float = 0.7,
    previous_hook_treatment: Optional[frozenset] = None,
) -> List[MotifTransformation]:
    """Select the appropriate transformations for a section.

    Parameters
    ----------
    section_type:
        Canonical section type (e.g. ``"hook"``, ``"verse"``).
    occurrence_index:
        0-based count of how many times this section type has received a
        motif treatment before.
    source_quality:
        Source quality mode string.  Weaker quality restricts to simpler
        transformations.
    available_roles:
        Instrument roles available in the source material.
    energy:
        Target energy for this section in [0.0, 1.0].
    previous_hook_treatment:
        Frozenset of transformation types used on the immediately preceding
        hook occurrence.  Used to differentiate repeated hooks.

    Returns
    -------
    List[MotifTransformation]
        Deterministically selected transformations for this section occurrence.
    """
    table = _TRANSFORMATION_TABLE.get(section_type)
    if table is None:
        # Unknown section type — conservative fallback.
        return [simplify(intensity=0.40, notes=f"fallback_{section_type}")]

    idx = min(occurrence_index, len(table) - 1)
    selected = list(table[idx])

    # For stereo_fallback: always downgrade to texture_only regardless of section.
    is_stereo = source_quality == "stereo_fallback"
    if is_stereo and section_type not in ("hook",):
        return [texture_only(intensity=0.20, notes="stereo_fallback_texture")]

    if is_stereo and section_type == "hook":
        return [sparse_phrase(intensity=0.40, notes="stereo_fallback_hook")]

    # Differentiate repeated hooks: if the proposed treatment matches the
    # previous hook, use the next entry from the table.
    if (
        section_type == "hook"
        and previous_hook_treatment is not None
        and len(selected) > 0
    ):
        proposed = frozenset(t.transformation_type for t in selected)
        if proposed == previous_hook_treatment and occurrence_index + 1 < len(table):
            selected = list(table[occurrence_index + 1])

    # For ai_separated: cap hook intensity and avoid octave_lift.
    # Applied after hook-differentiation to filter any newly selected entries too.
    if source_quality == "ai_separated":
        selected = [
            t for t in selected if t.transformation_type != "octave_lift"
        ]
        if not selected:
            selected = [full_phrase(intensity=0.75, notes="ai_separated_hook")]

    return selected
