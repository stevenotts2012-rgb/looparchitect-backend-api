"""Genre-aware arrangement Template Selector.

Selects a deterministic arrangement template from the genre template pack
based on the following inputs:

- ``genre``            : required genre key ("trap" | "drill" | "rnb" | "rage")
- ``vibe``             : optional vibe hint that narrows the candidate pool
- ``loop_energy``      : 0.0–1.0 energy of the source loop material
- ``melodic_richness`` : 0.0–1.0 melodic content measure
- ``complexity_class`` : preferred complexity ("simple" | "medium" | "complex")
- ``variation_seed``   : int/str seed for deterministic selection

Given the **same** inputs and the **same** seed the selector always returns the
**same** template.  Different seeds can produce different valid templates when
more than one candidate qualifies.

Public API
----------
select_template        : main entry point, returns TemplateSelectionResult
TemplateSelectionResult: dataclass with selection details and metadata
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from app.style_engine.genre_templates import (
    ALL_TEMPLATES,
    ArrangementTemplate,
    get_templates_for_genre,
    validate_template,
)
from app.style_engine.seed import create_rng, choice_weighted

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

VALID_COMPLEXITY_CLASSES = frozenset({"simple", "medium", "complex"})


@dataclass
class TemplateSelectionResult:
    """Outcome of a :func:`select_template` call."""

    # Metadata
    available_template_count: int
    candidate_template_ids: list[str]
    selected_template_id: str
    selected_template_reason: str
    template_total_bars: int

    # The chosen template itself
    template: ArrangementTemplate

    # Seed that was actually used (useful when caller passed None)
    seed_used: int


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _energy_score(template: ArrangementTemplate, loop_energy: float) -> float:
    """Score based on proximity of template energy to loop energy (0–1)."""
    return 1.0 - abs(template.energy - loop_energy)


def _melodic_score(template: ArrangementTemplate, melodic_richness: float) -> float:
    """Score based on proximity of melodic richness (0–1)."""
    return 1.0 - abs(template.melodic_richness - melodic_richness)


def _complexity_score(template: ArrangementTemplate, complexity_class: str) -> float:
    """Score = 1.0 for exact match, 0.5 for adjacent, 0.0 for opposite."""
    order = {"simple": 0, "medium": 1, "complex": 2}
    t_ord = order.get(template.complexity_class, 1)
    c_ord = order.get(complexity_class, 1)
    distance = abs(t_ord - c_ord)
    return max(0.0, 1.0 - distance * 0.5)


def _vibe_score(template: ArrangementTemplate, vibe: Optional[str]) -> float:
    """Score = 1.0 when vibe matches any template vibe tag, else 0.5."""
    if not vibe:
        return 0.5
    return 1.0 if vibe.strip().lower() in template.vibe else 0.5


# ---------------------------------------------------------------------------
# Main selector
# ---------------------------------------------------------------------------

def select_template(
    genre: str,
    vibe: Optional[str] = None,
    loop_energy: float = 0.5,
    melodic_richness: float = 0.5,
    complexity_class: str = "medium",
    variation_seed: Optional[int | str] = None,
) -> TemplateSelectionResult:
    """Select the best-matching arrangement template.

    Parameters
    ----------
    genre:
        Target genre ("trap" | "drill" | "rnb" | "rage").
    vibe:
        Optional vibe hint string (e.g. "dark", "melodic").  When provided,
        templates whose vibe tags include this string receive a higher score.
    loop_energy:
        0.0–1.0 energy level of the source loop material.
    melodic_richness:
        0.0–1.0 measure of melodic content in the source.
    complexity_class:
        Preferred arrangement complexity ("simple" | "medium" | "complex").
    variation_seed:
        Integer or string seed for deterministic selection.  Passing the same
        seed with the same other inputs always yields the same template.
        Pass ``None`` to pick a random seed.

    Returns
    -------
    TemplateSelectionResult
        Full selection metadata plus the chosen template.

    Raises
    ------
    ValueError
        When *genre* is not a recognised genre key.
    RuntimeError
        When no valid templates are found for the genre (should never occur
        if the genre template pack is correctly defined).
    """
    # Validate / clamp inputs
    loop_energy = max(0.0, min(1.0, float(loop_energy)))
    melodic_richness = max(0.0, min(1.0, float(melodic_richness)))
    if complexity_class not in VALID_COMPLEXITY_CLASSES:
        complexity_class = "medium"

    seed_used, rng = create_rng(variation_seed)

    # 1. Retrieve all templates for the requested genre (raises ValueError if unknown)
    candidates = get_templates_for_genre(genre)

    # 2. Filter out templates with validation errors
    valid_candidates = [t for t in candidates if not validate_template(t)]

    if not valid_candidates:
        raise RuntimeError(
            f"No valid templates found for genre '{genre}'.  "
            "Check genre_templates.py for validation errors."
        )

    available_count = len(valid_candidates)

    # 3. Score each candidate
    def _score(t: ArrangementTemplate) -> float:
        e = _energy_score(t, loop_energy)
        m = _melodic_score(t, melodic_richness)
        c = _complexity_score(t, complexity_class)
        v = _vibe_score(t, vibe)
        # Weighted combination
        return 0.35 * e + 0.25 * m + 0.20 * c + 0.20 * v

    scores = [_score(t) for t in valid_candidates]

    # 4. Deterministic weighted selection using the seed
    chosen = choice_weighted(rng, valid_candidates, scores)

    # Build a human-readable reason
    chosen_score = scores[valid_candidates.index(chosen)]
    reason_parts = [
        f"genre={genre}",
        f"energy_proximity={1.0 - abs(chosen.energy - loop_energy):.2f}",
        f"melodic_proximity={1.0 - abs(chosen.melodic_richness - melodic_richness):.2f}",
        f"complexity_match={chosen.complexity_class}=={complexity_class}",
    ]
    if vibe:
        vibe_hit = vibe.strip().lower() in chosen.vibe
        reason_parts.append(f"vibe_match={vibe_hit}")
    reason_parts.append(f"score={chosen_score:.3f}")
    reason_parts.append(f"seed={seed_used}")

    reason = "; ".join(reason_parts)

    return TemplateSelectionResult(
        available_template_count=available_count,
        candidate_template_ids=[t.id for t in valid_candidates],
        selected_template_id=chosen.id,
        selected_template_reason=reason,
        template_total_bars=chosen.total_bars,
        template=chosen,
        seed_used=seed_used,
    )
