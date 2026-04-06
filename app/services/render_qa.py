"""
Render QA Service — Phase 3: Sound Quality / Render Polish Layer.

Provides heuristic quality scoring and QA checks for arrangement plans and
render outputs.  All scores are 0–100.

Quality dimensions:
    structure_score      — How well the section flow follows producer patterns
    transition_score     — Quality of transitions between sections
    audio_quality_score  — Heuristic render hygiene (missing files, clipping risk, etc.)
    overall_score        — Weighted composite

QA checks are additive — they never silently discard valid output.  A
failed check downgrades the relevant score and adds a flag to the result.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.producer_plan_builder import (
    ProducerArrangementPlanV2,
    ProducerSectionPlan,
    SectionKind,
    DensityLevel,
    EnergyLevel,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Score models
# ---------------------------------------------------------------------------


@dataclass
class QualityScore:
    """Heuristic quality score for an arrangement plan or render output."""

    structure_score: float = 100.0      # 0–100: section flow & producer patterns
    transition_score: float = 100.0     # 0–100: transition intent quality
    audio_quality_score: float = 100.0  # 0–100: render hygiene
    overall_score: float = 100.0        # weighted composite

    # Anti-mud / mix-clarity supplemental scores (informational; not factored into overall_score)
    clarity_score: float = 100.0        # 0–100: absence of muddy role stacking
    density_balance_score: float = 100.0  # 0–100: density varies meaningfully across sections
    hook_impact_score: float = 100.0    # 0–100: hooks are perceptibly louder/denser than verses

    # Human-readable pass/fail flags
    flags: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def recompute_overall(
        self,
        structure_weight: float = 0.40,
        transition_weight: float = 0.30,
        audio_weight: float = 0.30,
    ) -> None:
        """Recompute overall_score from weighted components."""
        self.overall_score = round(
            self.structure_score * structure_weight
            + self.transition_score * transition_weight
            + self.audio_quality_score * audio_weight,
            1,
        )

    def to_dict(self) -> dict:
        return {
            "structure_score": self.structure_score,
            "transition_score": self.transition_score,
            "audio_quality_score": self.audio_quality_score,
            "overall_score": self.overall_score,
            "clarity_score": self.clarity_score,
            "density_balance_score": self.density_balance_score,
            "hook_impact_score": self.hook_impact_score,
            "flags": self.flags,
            "warnings": self.warnings,
        }

    @property
    def passed(self) -> bool:
        """Overall QA pass/fail threshold (overall >= 50)."""
        return self.overall_score >= 50.0


# ---------------------------------------------------------------------------
# QA result
# ---------------------------------------------------------------------------


@dataclass
class RenderQAResult:
    """Result of running RenderQAService over a plan or render output."""

    score: QualityScore
    checks_run: List[str] = field(default_factory=list)
    passed: bool = True

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "score": self.score.to_dict(),
            "checks_run": self.checks_run,
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RenderQAService:
    """
    Scores an arrangement plan for production quality.

    All checks are purely heuristic and deterministic — no audio I/O.
    Use ``score_plan`` for arrangement plan evaluation.
    Use ``score_render_output`` for post-render file hygiene checks.

    Usage::

        result = RenderQAService.score_plan(plan)
        print(result.score.overall_score)   # e.g. 82.5
        for flag in result.score.flags:
            print(flag)
    """

    # Penalty values (points deducted from relevant dimension)
    _STRUCTURE_PENALTIES = {
        "no_hooks":                   30,
        "intro_too_dense":            15,
        "hook_not_elevated":          20,
        "outro_too_energetic":        10,
        "no_contrast_section":        15,
        "hook_not_loudest":           10,
        "excessive_full_mix_reliance": 10,
        "flat_energy_curve":          15,
    }

    _TRANSITION_PENALTIES = {
        "no_transition_before_hook":  15,
        "hard_cut_into_breakdown":    10,
        "missing_transition_out_intro": 5,
    }

    _AUDIO_PENALTIES = {
        "no_roles_available":         25,
        "empty_sections_detected":    20,
        "single_section_arrangement": 30,
        "all_sections_identical_roles": 15,
    }

    # Penalty values for the anti-mud / supplemental score dimensions
    _CLARITY_PENALTIES = {
        "melodic_overload":           20,   # 3+ melodic roles in non-payoff section
        "sustained_wash":             15,   # 3+ sustained roles in non-payoff section
    }

    _DENSITY_BALANCE_PENALTIES = {
        "no_density_variety":         25,   # all sections have the same density level
        "intro_denser_than_hook":     20,   # intro density >= hook density (inverted structure)
        "outro_denser_than_hook":     15,
    }

    _HOOK_IMPACT_PENALTIES = {
        "hook_not_denser_than_verse": 25,   # hook density <= verse density
        "hook_not_more_roles":        20,   # hook has same number of roles as adjacent verse
    }

    @classmethod
    def score_plan(cls, plan: ProducerArrangementPlanV2) -> RenderQAResult:
        """Score an arrangement plan. Returns RenderQAResult."""
        score = QualityScore()
        checks_run: list[str] = []

        cls._check_structure(plan, score, checks_run)
        cls._check_transitions(plan, score, checks_run)
        cls._check_audio_hygiene(plan, score, checks_run)
        cls._check_clarity(plan, score, checks_run)
        cls._check_density_balance(plan, score, checks_run)
        cls._check_hook_impact(plan, score, checks_run)

        score.recompute_overall()

        result = RenderQAResult(
            score=score,
            checks_run=checks_run,
            passed=score.passed,
        )

        logger.info(
            "RenderQAService: overall=%.1f structure=%.1f transition=%.1f audio=%.1f "
            "clarity=%.1f density_balance=%.1f hook_impact=%.1f passed=%s",
            score.overall_score,
            score.structure_score,
            score.transition_score,
            score.audio_quality_score,
            score.clarity_score,
            score.density_balance_score,
            score.hook_impact_score,
            result.passed,
        )

        return result

    @classmethod
    def score_render_output(
        cls,
        output_path: Optional[str],
        sections: Optional[list[dict]] = None,
    ) -> RenderQAResult:
        """
        Check a rendered file for obvious hygiene issues.

        Args:
            output_path: Path to the rendered audio file.
            sections:    Optional list of section dicts from render_plan for
                         section-level checks.
        """
        score = QualityScore()
        checks_run: list[str] = []

        # File existence
        checks_run.append("file_exists")
        if not output_path or not os.path.exists(output_path):
            score.audio_quality_score -= cls._AUDIO_PENALTIES.get("empty_sections_detected", 20)
            score.flags.append(f"render_output_missing: {output_path or 'None'}")
        else:
            # Zero-length file
            checks_run.append("non_zero_size")
            size = os.path.getsize(output_path)
            if size == 0:
                score.audio_quality_score -= 40
                score.flags.append(f"render_output_zero_bytes: {output_path}")
            elif size < 1024:
                score.warnings.append(
                    f"render_output_very_small ({size} bytes) — possible silence or corrupt output"
                )

        score.audio_quality_score = max(0.0, score.audio_quality_score)
        score.recompute_overall()

        return RenderQAResult(
            score=score,
            checks_run=checks_run,
            passed=score.passed,
        )

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    @classmethod
    def _check_structure(
        cls, plan: ProducerArrangementPlanV2, score: QualityScore, checks_run: list[str]
    ) -> None:
        sections = plan.sections
        hooks = [s for s in sections if s.section_type == SectionKind.HOOK]
        verses = [s for s in sections if s.section_type == SectionKind.VERSE]
        intros = [s for s in sections if s.section_type == SectionKind.INTRO]
        outros = [s for s in sections if s.section_type == SectionKind.OUTRO]
        contrast = [s for s in sections if s.section_type in (SectionKind.BRIDGE, SectionKind.BREAKDOWN)]

        # --- no_hooks ---
        checks_run.append("no_hooks")
        if not hooks:
            score.structure_score -= cls._STRUCTURE_PENALTIES["no_hooks"]
            score.flags.append("no_hooks: arrangement lacks a payoff hook section")

        # --- intro_too_dense ---
        checks_run.append("intro_too_dense")
        for intro in intros:
            if intro.density == DensityLevel.FULL:
                score.structure_score -= cls._STRUCTURE_PENALTIES["intro_too_dense"]
                score.flags.append(
                    f"intro_too_dense: {intro.label} is full-density — opening too crowded"
                )

        # --- hook_not_elevated ---
        checks_run.append("hook_not_elevated")
        if hooks and verses:
            max_verse_energy = max(s.target_energy.value for s in verses)
            for hook in hooks:
                if hook.target_energy.value <= max_verse_energy:
                    score.structure_score -= cls._STRUCTURE_PENALTIES["hook_not_elevated"]
                    score.flags.append(
                        f"hook_not_elevated: {hook.label} energy ({hook.target_energy.value}) "
                        f"not above verse energy ({max_verse_energy})"
                    )

        # --- outro_too_energetic ---
        checks_run.append("outro_too_energetic")
        for outro in outros:
            if outro.target_energy.value > EnergyLevel.LOW.value:
                score.structure_score -= cls._STRUCTURE_PENALTIES["outro_too_energetic"]
                score.flags.append(
                    f"outro_too_energetic: {outro.label} energy={outro.target_energy.value}"
                )

        # --- no_contrast_section ---
        checks_run.append("no_contrast_section")
        if hooks and not contrast and len(sections) > 4:
            score.structure_score -= cls._STRUCTURE_PENALTIES["no_contrast_section"]
            score.warnings.append(
                "no_contrast_section: no bridge or breakdown to contrast with hooks"
            )

        # --- excessive_full_mix_reliance ---
        checks_run.append("excessive_full_mix_reliance")
        if len(plan.available_roles) > 1:
            full_mix_count = sum(1 for s in sections if s.active_roles == ["full_mix"])
            if sections and full_mix_count > len(sections) // 2:
                score.structure_score -= cls._STRUCTURE_PENALTIES["excessive_full_mix_reliance"]
                score.warnings.append(
                    f"excessive_full_mix_reliance: {full_mix_count}/{len(sections)} sections "
                    "use full_mix despite isolated stems"
                )

        # --- flat_energy_curve ---
        checks_run.append("flat_energy_curve")
        if len(sections) > 3:
            energy_values = [s.target_energy.value for s in sections]
            energy_range = max(energy_values) - min(energy_values)
            if energy_range < 2:
                score.structure_score -= cls._STRUCTURE_PENALTIES["flat_energy_curve"]
                score.warnings.append(
                    f"flat_energy_curve: energy range is only {energy_range} — "
                    "arrangement lacks dynamic contrast"
                )

        score.structure_score = max(0.0, score.structure_score)

    @classmethod
    def _check_transitions(
        cls, plan: ProducerArrangementPlanV2, score: QualityScore, checks_run: list[str]
    ) -> None:
        sections = plan.sections

        # --- no_transition_before_hook ---
        checks_run.append("no_transition_before_hook")
        for i, s in enumerate(sections):
            if s.section_type == SectionKind.HOOK and i > 0:
                prev = sections[i - 1]
                if (
                    prev.transition_out.value == "none"
                    and s.transition_in.value == "none"
                ):
                    score.transition_score -= cls._TRANSITION_PENALTIES["no_transition_before_hook"]
                    score.warnings.append(
                        f"no_transition_before_hook: hard cut into {s.label} — "
                        "add a fill or riser for better payoff"
                    )

        # --- hard_cut_into_breakdown ---
        checks_run.append("hard_cut_into_breakdown")
        for i, s in enumerate(sections):
            if s.section_type in (SectionKind.BRIDGE, SectionKind.BREAKDOWN) and i > 0:
                if s.transition_in.value == "none":
                    score.transition_score -= cls._TRANSITION_PENALTIES["hard_cut_into_breakdown"]
                    score.warnings.append(
                        f"hard_cut_into_breakdown: {s.label} has no transition — "
                        "a mute drop or silence is expected"
                    )

        score.transition_score = max(0.0, score.transition_score)

    @classmethod
    def _check_audio_hygiene(
        cls, plan: ProducerArrangementPlanV2, score: QualityScore, checks_run: list[str]
    ) -> None:
        sections = plan.sections

        # --- no_roles_available ---
        checks_run.append("no_roles_available")
        if not plan.available_roles:
            score.audio_quality_score -= cls._AUDIO_PENALTIES["no_roles_available"]
            score.warnings.append(
                "no_roles_available: no stems/roles detected — "
                "output will rely on full-mix fallback"
            )

        # --- empty_sections_detected ---
        checks_run.append("empty_sections_detected")
        empty = [s for s in sections if not s.active_roles]
        if empty:
            penalty = cls._AUDIO_PENALTIES["empty_sections_detected"]
            score.audio_quality_score -= min(penalty, penalty * len(empty) // max(1, len(sections)))
            for s in empty:
                score.flags.append(
                    f"empty_section: {s.label} has no active roles — will render silence"
                )

        # --- single_section_arrangement ---
        checks_run.append("single_section_arrangement")
        if len(sections) <= 1:
            score.audio_quality_score -= cls._AUDIO_PENALTIES["single_section_arrangement"]
            score.flags.append(
                "single_section_arrangement: only one section in plan — no structure"
            )

        # --- all_sections_identical_roles ---
        checks_run.append("all_sections_identical_roles")
        if len(sections) > 1:
            role_sets = [frozenset(s.active_roles) for s in sections]
            if len(set(role_sets)) == 1:
                score.audio_quality_score -= cls._AUDIO_PENALTIES["all_sections_identical_roles"]
                score.warnings.append(
                    "all_sections_identical_roles: every section plays the same role set — "
                    "no sonic variation across the arrangement"
                )

        score.audio_quality_score = max(0.0, score.audio_quality_score)

    # ------------------------------------------------------------------
    # Anti-mud / clarity checks (supplemental scores — informational)
    # ------------------------------------------------------------------

    # Roles that carry tonal / melodic content and crowd the mix when stacked
    _MELODIC_ROLES: frozenset[str] = frozenset({"melody", "harmony", "pads", "vocals", "vocal"})
    # Roles that produce sustained (long-decay) audio
    _SUSTAINED_ROLES: frozenset[str] = frozenset({"pads", "harmony", "vocals", "vocal"})
    # Payoff section types that are allowed higher density
    _PAYOFF_KINDS: frozenset[SectionKind] = frozenset({SectionKind.HOOK, SectionKind.PRE_HOOK})

    @classmethod
    def _check_clarity(
        cls, plan: ProducerArrangementPlanV2, score: QualityScore, checks_run: list[str]
    ) -> None:
        """Score melodic / sustained stacking against anti-mud thresholds.

        These are informational penalties on ``clarity_score``.  They do **not**
        affect ``structure_score`` or ``overall_score``.
        """
        sections = plan.sections

        # --- melodic_overload ---
        checks_run.append("melodic_overload")
        for s in sections:
            cap = 3 if s.section_type in cls._PAYOFF_KINDS else 2
            melodic_count = sum(1 for r in s.active_roles if r in cls._MELODIC_ROLES)
            if melodic_count > cap:
                score.clarity_score -= cls._CLARITY_PENALTIES["melodic_overload"]
                score.warnings.append(
                    f"melodic_overload: {s.label} has {melodic_count} melodic roles active "
                    f"(cap={cap}) — risk of harmonic muddiness"
                )

        # --- sustained_wash ---
        checks_run.append("sustained_wash")
        for s in sections:
            cap = 3 if s.section_type in cls._PAYOFF_KINDS else 2
            sustained_count = sum(1 for r in s.active_roles if r in cls._SUSTAINED_ROLES)
            if sustained_count > cap:
                score.clarity_score -= cls._CLARITY_PENALTIES["sustained_wash"]
                score.warnings.append(
                    f"sustained_wash: {s.label} has {sustained_count} sustained sources active "
                    f"(cap={cap}) — risk of washy mix"
                )

        score.clarity_score = max(0.0, score.clarity_score)

    @classmethod
    def _check_density_balance(
        cls, plan: ProducerArrangementPlanV2, score: QualityScore, checks_run: list[str]
    ) -> None:
        """Score how well density varies across sections.

        These are informational penalties on ``density_balance_score``.
        """
        sections = plan.sections
        if not sections:
            return

        density_order = [DensityLevel.SPARSE, DensityLevel.MEDIUM, DensityLevel.FULL]

        def _density_val(s: "ProducerSectionPlan") -> int:
            try:
                return density_order.index(s.density)
            except ValueError:
                return 1  # default: medium

        density_values = [_density_val(s) for s in sections]

        # --- no_density_variety ---
        checks_run.append("no_density_variety")
        if len(set(density_values)) == 1:
            score.density_balance_score -= cls._DENSITY_BALANCE_PENALTIES["no_density_variety"]
            score.warnings.append(
                "no_density_variety: all sections have the same density — arrangement lacks dynamic contrast"
            )

        # --- intro_denser_than_hook ---
        checks_run.append("intro_denser_than_hook")
        intros = [s for s in sections if s.section_type == SectionKind.INTRO]
        hooks = [s for s in sections if s.section_type == SectionKind.HOOK]
        if intros and hooks:
            max_intro_density = max(_density_val(s) for s in intros)
            max_hook_density = max(_density_val(s) for s in hooks)
            if max_intro_density >= max_hook_density:
                score.density_balance_score -= cls._DENSITY_BALANCE_PENALTIES["intro_denser_than_hook"]
                score.warnings.append(
                    "intro_denser_than_hook: intro density >= hook density — structural inversion"
                )

        # --- outro_denser_than_hook ---
        checks_run.append("outro_denser_than_hook")
        outros = [s for s in sections if s.section_type == SectionKind.OUTRO]
        if outros and hooks:
            max_outro_density = max(_density_val(s) for s in outros)
            max_hook_density = max(_density_val(s) for s in hooks)
            if max_outro_density >= max_hook_density:
                score.density_balance_score -= cls._DENSITY_BALANCE_PENALTIES["outro_denser_than_hook"]
                score.warnings.append(
                    "outro_denser_than_hook: outro density >= hook density — outro should wind down"
                )

        score.density_balance_score = max(0.0, score.density_balance_score)

    @classmethod
    def _check_hook_impact(
        cls, plan: ProducerArrangementPlanV2, score: QualityScore, checks_run: list[str]
    ) -> None:
        """Score whether hooks are perceptibly bigger than verses.

        These are informational penalties on ``hook_impact_score``.
        """
        sections = plan.sections
        hooks = [s for s in sections if s.section_type == SectionKind.HOOK]
        verses = [s for s in sections if s.section_type == SectionKind.VERSE]

        if not hooks or not verses:
            return

        density_order = [DensityLevel.SPARSE, DensityLevel.MEDIUM, DensityLevel.FULL]

        def _density_val(s: "ProducerSectionPlan") -> int:
            try:
                return density_order.index(s.density)
            except ValueError:
                return 1

        # --- hook_not_denser_than_verse ---
        checks_run.append("hook_not_denser_than_verse")
        max_verse_density = max(_density_val(s) for s in verses)
        for hook in hooks:
            if _density_val(hook) <= max_verse_density:
                score.hook_impact_score -= cls._HOOK_IMPACT_PENALTIES["hook_not_denser_than_verse"]
                score.warnings.append(
                    f"hook_not_denser_than_verse: {hook.label} density ({hook.density.value}) "
                    f"not greater than verse density — hook will not feel bigger"
                )
                break  # one penalty per arrangement, not per hook

        # --- hook_not_more_roles ---
        checks_run.append("hook_not_more_roles")
        avg_verse_roles = sum(len(s.active_roles) for s in verses) / max(1, len(verses))
        for hook in hooks:
            if len(hook.active_roles) <= avg_verse_roles:
                score.hook_impact_score -= cls._HOOK_IMPACT_PENALTIES["hook_not_more_roles"]
                score.warnings.append(
                    f"hook_not_more_roles: {hook.label} has {len(hook.active_roles)} roles "
                    f"(verse avg={avg_verse_roles:.1f}) — hooks should carry more layers"
                )
                break  # one penalty per arrangement

        score.hook_impact_score = max(0.0, score.hook_impact_score)
