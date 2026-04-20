"""
Critic Agent — scores an AIProducerPlan like an A&R / producer reviewer.

Scoring dimensions:
1. repeated_section_contrast_score  — repeated sections must differ meaningfully
2. hook_payoff_score                — hook must feel like payoff
3. timeline_movement_score          — changes every 4–8 bars when material allows
4. groove_fit_score                 — section groove aligns with energy and type
5. transition_quality_score         — boundaries are non-generic and varied
6. novelty_score                    — later hooks/verses evolve
7. vagueness_score                  — penalise vague/generic language

Rejection thresholds:
- overall_score < 0.55
- any critical subscore < 0.30
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from app.services.ai_producer_system.schemas import (
    AICriticScore,
    AIProducerPlan,
    AISectionPlan,
)
from app.services.ai_producer_system.scoring import (
    CRITICAL_SUBSCORE_THRESHOLD,
    OVERALL_ACCEPTANCE_THRESHOLD,
    energy_curve_score,
    hook_novelty_vs_prior_sections,
    hook_payoff_score as _hook_payoff_score,
    plan_completeness_score,
    repeated_section_contrast_score as _rsc_score,
    timeline_event_density,
    transition_diversity,
    vague_phrase_penalty,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Groove fit rules
# ---------------------------------------------------------------------------

_EXPECTED_ENERGY_FOR_TYPE: dict[str, tuple[float, float]] = {
    # section_name → (min_energy, max_energy)
    "hook": (0.70, 1.0),
    "chorus": (0.70, 1.0),
    "drop": (0.80, 1.0),
    "verse": (0.30, 0.75),
    "pre_hook": (0.55, 0.85),
    "bridge": (0.10, 0.55),
    "breakdown": (0.10, 0.50),
    "intro": (0.10, 0.60),
    "outro": (0.10, 0.50),
}

_EXPECTED_DENSITY_FOR_TYPE: dict[str, tuple[float, float]] = {
    "hook": (0.60, 1.0),
    "chorus": (0.60, 1.0),
    "drop": (0.70, 1.0),
    "verse": (0.30, 0.75),
    "pre_hook": (0.50, 0.80),
    "bridge": (0.10, 0.50),
    "breakdown": (0.10, 0.45),
    "intro": (0.10, 0.55),
    "outro": (0.10, 0.45),
}


def _groove_fit_for_section(sp: AISectionPlan) -> float:
    """Return groove fit score [0.0, 1.0] for a single section."""
    name = sp.section_name
    energy_range = _EXPECTED_ENERGY_FOR_TYPE.get(name)
    density_range = _EXPECTED_DENSITY_FOR_TYPE.get(name)

    score = 1.0
    if energy_range:
        lo, hi = energy_range
        if not (lo <= sp.target_energy <= hi):
            score -= 0.35
    if density_range:
        lo, hi = density_range
        if not (lo <= sp.target_density <= hi):
            score -= 0.35
    return max(0.0, score)


# ---------------------------------------------------------------------------
# CriticAgent
# ---------------------------------------------------------------------------

class CriticAgent:
    """Scores an :class:`AIProducerPlan` and returns an :class:`AICriticScore`."""

    def score(self, plan: AIProducerPlan) -> AICriticScore:
        """Evaluate *plan* across all scoring dimensions.

        Parameters
        ----------
        plan:
            The plan to evaluate.

        Returns
        -------
        AICriticScore
            Fully populated score object including warnings.
        """
        logger.info("CRITIC: scoring plan with %d sections", len(plan.section_plans))

        warnings: list[str] = []

        # 1. Repeated section contrast
        rsc = _rsc_score(plan.section_plans)
        if rsc < CRITICAL_SUBSCORE_THRESHOLD:
            warnings.append(
                f"REPEATED_SECTION_CONTRAST too low ({rsc:.2f}): "
                "repeated sections are too similar — inject concrete differences."
            )

        # 2. Hook payoff
        hooks = [sp for sp in plan.section_plans if sp.section_name in ("hook", "chorus")]
        verses = [sp for sp in plan.section_plans if sp.section_name == "verse"]
        if hooks:
            hp = _hook_payoff_score(hooks[-1], verses)
        else:
            hp = 0.5
            warnings.append(
                "HOOK_PAYOFF: no hook or chorus sections found — "
                "arrangement lacks a payoff moment."
            )
        if hp < CRITICAL_SUBSCORE_THRESHOLD:
            warnings.append(
                f"HOOK_PAYOFF too low ({hp:.2f}): "
                "hook does not exceed verse energy/density by enough margin."
            )

        # 3. Timeline movement
        total_bars = sum(sp.bars for sp in plan.section_plans)
        tl = timeline_event_density(plan.micro_plan_events, total_bars)
        if total_bars >= 16 and tl < 0.25:
            warnings.append(
                f"TIMELINE_MOVEMENT too low ({tl:.2f}): "
                "too few micro-plan events — increase internal motion per section."
            )

        # 4. Groove fit
        if plan.section_plans:
            gf_scores = [_groove_fit_for_section(sp) for sp in plan.section_plans]
            gf = sum(gf_scores) / len(gf_scores)
        else:
            gf = 0.5
        if gf < CRITICAL_SUBSCORE_THRESHOLD:
            warnings.append(
                f"GROOVE_FIT too low ({gf:.2f}): "
                "section energy/density values violate expected ranges for their types."
            )

        # 5. Transition quality
        tq = transition_diversity(plan.section_plans)
        if tq < CRITICAL_SUBSCORE_THRESHOLD:
            warnings.append(
                f"TRANSITION_QUALITY too low ({tq:.2f}): "
                "transitions are too uniform — substitute varied boundary behaviours."
            )

        # 6. Novelty
        nv = self._novelty_score(plan)
        if nv < CRITICAL_SUBSCORE_THRESHOLD:
            warnings.append(
                f"NOVELTY too low ({nv:.2f}): "
                "later hooks/verses do not evolve sufficiently from earlier occurrences."
            )

        # 7. Vagueness
        vg = vague_phrase_penalty(plan)
        if vg < CRITICAL_SUBSCORE_THRESHOLD:
            warnings.append(
                f"VAGUENESS too high (score={vg:.2f}): "
                "plan contains generic/vague production notes — replace with concrete instructions."
            )

        # Overall (weighted composite)
        overall = (
            rsc  * 0.20
            + hp  * 0.20
            + tl  * 0.15
            + gf  * 0.15
            + tq  * 0.10
            + nv  * 0.10
            + vg  * 0.10
        )
        # Completeness bonus / penalty (up to ±0.10)
        completeness = plan_completeness_score(plan)
        overall = min(1.0, overall + (completeness - 0.5) * 0.10)
        overall = max(0.0, overall)

        if overall < OVERALL_ACCEPTANCE_THRESHOLD:
            warnings.append(
                f"OVERALL_SCORE {overall:.2f} < {OVERALL_ACCEPTANCE_THRESHOLD}: "
                "plan requires repair or fallback."
            )

        score = AICriticScore(
            repeated_section_contrast_score=round(rsc, 4),
            hook_payoff_score=round(hp, 4),
            timeline_movement_score=round(tl, 4),
            groove_fit_score=round(gf, 4),
            transition_quality_score=round(tq, 4),
            novelty_score=round(nv, 4),
            vagueness_score=round(vg, 4),
            overall_score=round(overall, 4),
            warnings=warnings,
        )

        logger.info(
            "CRITIC: overall=%.3f  rsc=%.3f  hp=%.3f  tl=%.3f  gf=%.3f  "
            "tq=%.3f  nv=%.3f  vg=%.3f  warnings=%d",
            score.overall_score,
            score.repeated_section_contrast_score,
            score.hook_payoff_score,
            score.timeline_movement_score,
            score.groove_fit_score,
            score.transition_quality_score,
            score.novelty_score,
            score.vagueness_score,
            len(score.warnings),
        )
        return score

    def is_acceptable(self, score: AICriticScore) -> bool:
        """Return ``True`` if the score meets acceptance thresholds."""
        if score.overall_score < OVERALL_ACCEPTANCE_THRESHOLD:
            return False
        critical = (
            score.repeated_section_contrast_score,
            score.hook_payoff_score,
            score.groove_fit_score,
        )
        return all(s >= CRITICAL_SUBSCORE_THRESHOLD for s in critical)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _novelty_score(self, plan: AIProducerPlan) -> float:
        """Score novelty of later hook/verse occurrences."""
        if not plan.section_plans:
            return 1.0

        novelty_scores: list[float] = []
        first_occurrence: dict[str, AISectionPlan] = {}

        for sp in plan.section_plans:
            key = sp.section_name
            if key not in first_occurrence:
                first_occurrence[key] = sp
            elif sp.occurrence > 1:
                from app.services.ai_producer_system.scoring import section_element_contrast
                contrast = section_element_contrast(first_occurrence[key], sp)
                novelty_scores.append(contrast)

        if not novelty_scores:
            return 1.0

        return sum(novelty_scores) / len(novelty_scores)
