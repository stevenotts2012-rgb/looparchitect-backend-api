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

    @classmethod
    def score_plan(cls, plan: ProducerArrangementPlanV2) -> RenderQAResult:
        """Score an arrangement plan. Returns RenderQAResult."""
        score = QualityScore()
        checks_run: list[str] = []

        cls._check_structure(plan, score, checks_run)
        cls._check_transitions(plan, score, checks_run)
        cls._check_audio_hygiene(plan, score, checks_run)

        score.recompute_overall()

        result = RenderQAResult(
            score=score,
            checks_run=checks_run,
            passed=score.passed,
        )

        logger.info(
            "RenderQAService: overall=%.1f structure=%.1f transition=%.1f audio=%.1f passed=%s",
            score.overall_score,
            score.structure_score,
            score.transition_score,
            score.audio_quality_score,
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
