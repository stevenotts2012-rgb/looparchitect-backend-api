"""
Motif Planner — builds a :class:`~app.services.motif_engine.types.MotifPlan`
across all arrangement sections.

The planner:
1. Extracts a core motif via :class:`~app.services.motif_engine.extractor.MotifExtractor`.
2. Iterates through sections and assigns motif occurrences with appropriate
   transformations from :mod:`~app.services.motif_engine.transformations`.
3. Tracks state via :class:`~app.services.motif_engine.state.MotifEngineState`
   to prevent repeated identical hook treatment and ensure outro resolution.
4. Computes :attr:`~app.services.motif_engine.types.MotifPlan.motif_reuse_score`
   and :attr:`~app.services.motif_engine.types.MotifPlan.motif_variation_score`.

The planner is deterministic — no uncontrolled randomness.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.motif_engine.extractor import MotifExtractor
from app.services.motif_engine.state import MotifEngineState
from app.services.motif_engine.transformations import select_transformations
from app.services.motif_engine.types import Motif, MotifOccurrence, MotifPlan

logger = logging.getLogger(__name__)

# Canonical section types that can receive a motif treatment.
_MOTIF_ELIGIBLE_SECTIONS: frozenset[str] = frozenset(
    {
        "intro",
        "verse",
        "pre_hook",
        "hook",
        "bridge",
        "breakdown",
        "outro",
    }
)

# Section types where the motif is ALWAYS included when a motif exists.
_ALWAYS_MOTIF_SECTIONS: frozenset[str] = frozenset(
    {
        "hook",
        "outro",
    }
)

# Base target intensity per section type.
_BASE_TARGET_INTENSITY: Dict[str, float] = {
    "intro": 0.30,
    "verse": 0.45,
    "pre_hook": 0.55,
    "hook": 0.90,
    "bridge": 0.55,
    "breakdown": 0.30,
    "outro": 0.35,
}


def _derive_section_type(name: str) -> str:
    """Derive a canonical section type from a raw section name string."""
    n = name.lower().strip()
    for token in ("pre_hook", "pre-hook", "prehook", "buildup", "build"):
        if token in n:
            return "pre_hook"
    for token in ("hook", "chorus", "drop"):
        if token in n:
            return "hook"
    for token in ("verse",):
        if token in n:
            return "verse"
    for token in ("bridge",):
        if token in n:
            return "bridge"
    for token in ("breakdown", "break"):
        if token in n:
            return "breakdown"
    for token in ("intro",):
        if token in n:
            return "intro"
    for token in ("outro",):
        if token in n:
            return "outro"
    return "verse"


def _compute_reuse_score(
    occurrences: List[MotifOccurrence],
    section_count: int,
) -> float:
    """Compute how well the motif is reused across sections.

    Heuristics:
    - If no occurrences: 0.0
    - 1 occurrence in many sections: small penalty
    - Well-spread reuse: approaches 1.0
    """
    if section_count == 0 or not occurrences:
        return 0.0
    reuse_ratio = len(occurrences) / max(section_count, 1)
    # Hook occurrences are more important — weight them.
    hook_count = sum(1 for o in occurrences if "hook" in o.section_name.lower())
    hook_bonus = min(0.20, hook_count * 0.10)
    raw = min(1.0, reuse_ratio * 0.8 + hook_bonus)
    # Penalise if only 1 occurrence (weak reuse).
    if len(occurrences) == 1:
        raw *= 0.5
    return round(raw, 4)


def _compute_variation_score(occurrences: List[MotifOccurrence]) -> float:
    """Compute how well the motif is varied across sections.

    Heuristics:
    - All identical transformations: ~0.1
    - Good variety across sections: approaches 1.0
    - Repeated hook identical treatment: penalty
    """
    if not occurrences:
        return 0.0

    # Collect unique transformation sets.
    transform_sets = [frozenset(o.transformation_types) for o in occurrences]
    total = len(transform_sets)
    unique = len(set(transform_sets))

    variety_ratio = unique / total if total > 0 else 0.0

    # Check repeated hook treatment.
    hook_occurrences = [
        o for o in occurrences if _derive_section_type(o.section_name) == "hook"
    ]
    hook_sets = [frozenset(o.transformation_types) for o in hook_occurrences]
    hook_identical_penalty = 0.0
    if len(hook_sets) >= 2 and len(set(hook_sets)) == 1:
        hook_identical_penalty = 0.25

    raw = max(0.0, variety_ratio - hook_identical_penalty)
    return round(min(1.0, raw), 4)


class MotifPlanner:
    """Build a :class:`~app.services.motif_engine.types.MotifPlan` from an
    arrangement's section sequence.

    Parameters
    ----------
    source_quality:
        Source quality mode string.
    available_roles:
        Instrument roles present in the source material.
    context:
        Optional dict with additional context for the extractor
        (e.g. ``{"motif_bars": 2}``).

    Usage::

        planner = MotifPlanner(source_quality="true_stems", available_roles=["melody"])
        plan = planner.build(sections=[...])
    """

    def __init__(
        self,
        source_quality: str = "stereo_fallback",
        available_roles: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.source_quality = source_quality
        self.available_roles: List[str] = list(available_roles or [])
        self.context: Dict[str, Any] = context or {}

    def build(
        self,
        sections: List[Dict[str, Any]],
    ) -> MotifPlan:
        """Build a :class:`MotifPlan` from an arrangement section sequence.

        Parameters
        ----------
        sections:
            Ordered list of section dicts.  Each dict must contain at least a
            ``type`` or ``name`` key identifying the section type, and
            optionally a ``bars`` key.

        Returns
        -------
        MotifPlan
            The complete motif reuse plan.
        """
        if not sections:
            return MotifPlan(
                motif=None,
                occurrences=[],
                motif_reuse_score=0.0,
                motif_variation_score=0.0,
                fallback_used=True,
            )

        # Step 1: extract the core motif.
        extractor = MotifExtractor(
            source_quality=self.source_quality,
            available_roles=self.available_roles,
            context=self.context,
        )
        motif: Optional[Motif] = extractor.extract()
        fallback_used = motif is None

        if motif is None:
            logger.info(
                "MotifPlanner: no viable motif extracted — fallback_used=True"
            )
            return MotifPlan(
                motif=None,
                occurrences=[],
                motif_reuse_score=0.0,
                motif_variation_score=0.0,
                fallback_used=True,
            )

        state = MotifEngineState()
        occurrences: List[MotifOccurrence] = []

        # Step 2: assign motif occurrences per section.
        for section in sections:
            raw_name = str(section.get("type") or section.get("name") or "verse")
            section_type = _derive_section_type(raw_name)

            if section_type not in _MOTIF_ELIGIBLE_SECTIONS:
                continue

            occurrence_index = state.get_occurrence_index(section_type)

            # Retrieve previous hook treatment for differentiation.
            prev_hook = state.last_hook_treatment() if section_type == "hook" else None

            transformations = select_transformations(
                section_type=section_type,
                occurrence_index=occurrence_index,
                source_quality=self.source_quality,
                available_roles=self.available_roles,
                energy=_BASE_TARGET_INTENSITY.get(section_type, 0.5),
                previous_hook_treatment=prev_hook,
            )

            target_intensity = _BASE_TARGET_INTENSITY.get(section_type, 0.5)

            occurrence = MotifOccurrence(
                section_name=raw_name,
                occurrence_index=occurrence_index,
                source_role=motif.source_role,
                transformations=transformations,
                target_intensity=target_intensity,
                notes=f"motif_type={motif.motif_type}",
            )

            state.record_occurrence(
                section_name=raw_name,
                section_type=section_type,
                transformation_types=[t.transformation_type for t in transformations],
            )
            occurrences.append(occurrence)

        # Step 3: compute scores.
        reuse_score = _compute_reuse_score(occurrences, len(sections))
        variation_score = _compute_variation_score(occurrences)

        logger.debug(
            "MotifPlanner: built plan — occurrences=%d reuse=%.3f variation=%.3f "
            "fallback=%s",
            len(occurrences),
            reuse_score,
            variation_score,
            fallback_used,
        )

        return MotifPlan(
            motif=motif,
            occurrences=occurrences,
            motif_reuse_score=reuse_score,
            motif_variation_score=variation_score,
            fallback_used=fallback_used,
        )
