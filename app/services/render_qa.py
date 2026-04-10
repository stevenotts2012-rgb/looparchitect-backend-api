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
    hook_impact_score: float = 100.0    # 0–100: hooks are perceptibly denser than verses

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


# ---------------------------------------------------------------------------
# Extended quality gates (Phase 2): section contrast, repeat differentiation,
# melodic overcrowding, low-end mud, source confidence, arrangement audibility.
# ---------------------------------------------------------------------------

_SOURCE_QUALITY_CONFIDENCE_THRESHOLD: float = 0.60
_ARRANGEMENT_AUDIBILITY_MIN_ROLES: int = 2
_REPEAT_DIFFERENTIATION_MIN_JACCARD: float = 0.20


@dataclass
class ExtendedQAResult:
    """Result from the extended quality gate checks.

    Fields:
        passed          — True when all critical gates pass.
        gates_failed    — Names of gates that failed (empty = all clear).
        warnings        — Non-critical quality advisory messages.
        repair_applied  — True when the auto-repair pass mutated the plan.
        repair_actions  — Human-readable description of each repair step taken.
        source_confidence — 0–1 confidence in the source quality (from mode).
    """

    passed: bool = True
    gates_failed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    repair_applied: bool = False
    repair_actions: List[str] = field(default_factory=list)
    source_confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "gates_failed": self.gates_failed,
            "warnings": self.warnings,
            "repair_applied": self.repair_applied,
            "repair_actions": self.repair_actions,
            "source_confidence": self.source_confidence,
        }


class ArrangementQualityGates:
    """Deterministic quality gate checks and auto-repair for arrangement plans.

    Usage::

        from app.services.render_qa import ArrangementQualityGates
        from app.services.source_quality import SourceQualityMode

        result = ArrangementQualityGates.check_and_repair(
            plan,
            source_quality=SourceQualityMode.AI_SEPARATED,
        )
        if result.repair_applied:
            for action in result.repair_actions:
                print("Repaired:", action)
    """

    # Penalty map for gate-based scoring
    _GATE_THRESHOLDS = {
        "section_contrast":         0.35,   # min Jaccard distance verse→hook
        "melodic_overcrowding":     2,      # max melodic roles in non-hook/pre_hook
        "low_end_mud":              2,      # max simultaneous bass-group roles
        "source_confidence":        0.60,   # min confidence from source mode
        "arrangement_audibility":   2,      # min total active roles in any section
    }

    # Roles in the bass/low-end group
    _LOW_END_ROLES: frozenset[str] = frozenset({"bass"})
    _MELODIC_ROLES: frozenset[str] = frozenset({"melody", "harmony", "pads", "vocals", "vocal"})
    _PAYOFF_KINDS: frozenset = frozenset({SectionKind.HOOK, SectionKind.PRE_HOOK})

    @classmethod
    def check_and_repair(
        cls,
        plan: ProducerArrangementPlanV2,
        source_quality: "SourceQualityMode | str | None" = None,
    ) -> ExtendedQAResult:
        """Run all quality gates against *plan*.

        If any gate fails, apply an auto-repair pass to reduce clutter and
        improve audible contrast.  The plan is mutated in-place when repair
        is applied.

        Args:
            plan:           The arrangement plan to check.
            source_quality: Source quality mode — affects confidence gate and
                            repair aggressiveness.  Accepts a
                            ``SourceQualityMode`` enum value or a plain string.

        Returns:
            ``ExtendedQAResult`` describing gate status and any repairs made.
        """
        from app.services.source_quality import get_source_quality_profile, SourceQualityMode

        profile = get_source_quality_profile(source_quality)
        result = ExtendedQAResult(source_confidence=profile.confidence_weight)

        cls._gate_section_contrast(plan, result)
        cls._gate_repeat_differentiation(plan, result)
        cls._gate_hook_payoff(plan, result)
        cls._gate_melodic_overcrowding(plan, result, profile)
        cls._gate_low_end_mud(plan, result, profile)
        cls._gate_source_confidence(result, profile)
        cls._gate_arrangement_audibility(plan, result)

        result.passed = len(result.gates_failed) == 0

        if not result.passed:
            cls._auto_repair(plan, result, profile)

        logger.info(
            "ArrangementQualityGates: passed=%s gates_failed=%s repair=%s",
            result.passed,
            result.gates_failed,
            result.repair_applied,
        )

        return result

    # ------------------------------------------------------------------
    # Gate implementations
    # ------------------------------------------------------------------

    @classmethod
    def _gate_section_contrast(
        cls, plan: ProducerArrangementPlanV2, result: ExtendedQAResult
    ) -> None:
        """Verify hooks are acoustically distinct from verses."""
        hooks = [s for s in plan.sections if s.section_type == SectionKind.HOOK]
        verses = [s for s in plan.sections if s.section_type == SectionKind.VERSE]
        if not hooks or not verses:
            return

        verse_roles = set().union(*(set(s.active_roles) for s in verses))
        hook_roles = set().union(*(set(s.active_roles) for s in hooks))

        union = len(verse_roles | hook_roles)
        if union == 0:
            return

        jaccard = 1.0 - len(verse_roles & hook_roles) / union
        threshold = cls._GATE_THRESHOLDS["section_contrast"]
        if jaccard < threshold:
            result.gates_failed.append("section_contrast")
            result.warnings.append(
                f"section_contrast: verse/hook role overlap too high "
                f"(Jaccard distance={jaccard:.2f}, need>={threshold:.2f}) — "
                "hook will not feel different from verse"
            )

    @classmethod
    def _gate_repeat_differentiation(
        cls, plan: ProducerArrangementPlanV2, result: ExtendedQAResult
    ) -> None:
        """Verify repeated same-type sections differ from each other."""
        by_type: dict[str, list] = {}
        for s in plan.sections:
            by_type.setdefault(s.section_type.value, []).append(s)

        for stype, sections in by_type.items():
            if len(sections) < 2:
                continue
            for i in range(len(sections) - 1):
                a = set(sections[i].active_roles)
                b = set(sections[i + 1].active_roles)
                union = len(a | b)
                if union == 0:
                    continue
                jaccard = 1.0 - len(a & b) / union
                if jaccard < _REPEAT_DIFFERENTIATION_MIN_JACCARD:
                    gate = f"repeat_differentiation_{stype}"
                    if gate not in result.gates_failed:
                        result.gates_failed.append(gate)
                    result.warnings.append(
                        f"repeat_differentiation: {stype} repeat #{i+2} is identical to "
                        f"#{i+1} (Jaccard={jaccard:.2f}) — no evolution between repeats"
                    )

    @classmethod
    def _gate_hook_payoff(
        cls, plan: ProducerArrangementPlanV2, result: ExtendedQAResult
    ) -> None:
        """Verify hooks have more roles than verses (payoff gate)."""
        hooks = [s for s in plan.sections if s.section_type == SectionKind.HOOK]
        verses = [s for s in plan.sections if s.section_type == SectionKind.VERSE]
        if not hooks or not verses:
            return

        avg_verse_roles = sum(len(s.active_roles) for s in verses) / len(verses)
        for hook in hooks:
            if len(hook.active_roles) <= avg_verse_roles:
                if "hook_payoff" not in result.gates_failed:
                    result.gates_failed.append("hook_payoff")
                result.warnings.append(
                    f"hook_payoff: {hook.label} has {len(hook.active_roles)} role(s) "
                    f"but verse avg is {avg_verse_roles:.1f} — hook must have more layers"
                )

    @classmethod
    def _gate_melodic_overcrowding(
        cls,
        plan: ProducerArrangementPlanV2,
        result: ExtendedQAResult,
        profile: "SourceQualityProfile",  # type: ignore[name-defined]
    ) -> None:
        """Flag sections with more melodic roles than the source quality allows."""
        cap = profile.max_melodic_layers
        for s in plan.sections:
            if s.section_type in cls._PAYOFF_KINDS:
                continue  # payoff sections have looser cap
            melodic = sum(1 for r in s.active_roles if r in cls._MELODIC_ROLES)
            if melodic > cap:
                if "melodic_overcrowding" not in result.gates_failed:
                    result.gates_failed.append("melodic_overcrowding")
                result.warnings.append(
                    f"melodic_overcrowding: {s.label} has {melodic} melodic roles "
                    f"(cap={cap} for source mode) — mix will be muddy"
                )

    @classmethod
    def _gate_low_end_mud(
        cls,
        plan: ProducerArrangementPlanV2,
        result: ExtendedQAResult,
        profile: "SourceQualityProfile",  # type: ignore[name-defined]
    ) -> None:
        """Flag low-end crowding (multiple bass-family roles stacked)."""
        if not profile.safe_low_end:
            return  # only enforce in safe-low-end modes (ai_separated, stereo_fallback)

        for s in plan.sections:
            low_end_count = sum(1 for r in s.active_roles if r in cls._LOW_END_ROLES)
            # Also count "other" if it co-exists with bass (AI separation artefact)
            has_other_with_bass = (
                "bass" in s.active_roles
                and any(r in {"full_mix", "other"} for r in s.active_roles)
            )
            if low_end_count > 1 or has_other_with_bass:
                if "low_end_mud" not in result.gates_failed:
                    result.gates_failed.append("low_end_mud")
                result.warnings.append(
                    f"low_end_mud: {s.label} stacks bass-group roles "
                    f"({[r for r in s.active_roles if r in cls._LOW_END_ROLES | {'full_mix', 'other'}]}) "
                    "— low-end will be muddy with AI-separated source"
                )

    @classmethod
    def _gate_source_confidence(
        cls,
        result: ExtendedQAResult,
        profile: "SourceQualityProfile",  # type: ignore[name-defined]
    ) -> None:
        """Flag low source confidence so downstream can adjust expectations."""
        threshold = cls._GATE_THRESHOLDS["source_confidence"]
        if profile.confidence_weight < threshold:
            if "source_confidence" not in result.gates_failed:
                result.gates_failed.append("source_confidence")
            result.warnings.append(
                f"source_confidence: source confidence={profile.confidence_weight:.2f} "
                f"is below threshold={threshold:.2f} — "
                f"{profile.description}"
            )

    @classmethod
    def _gate_arrangement_audibility(
        cls, plan: ProducerArrangementPlanV2, result: ExtendedQAResult
    ) -> None:
        """Flag sections with too few roles to produce audible output."""
        min_roles = cls._GATE_THRESHOLDS["arrangement_audibility"]
        for s in plan.sections:
            if s.section_type in (SectionKind.INTRO, SectionKind.OUTRO,
                                   SectionKind.BRIDGE, SectionKind.BREAKDOWN):
                continue  # sparse sections are expected to have 1 role
            if len(s.active_roles) < min_roles:
                if "arrangement_audibility" not in result.gates_failed:
                    result.gates_failed.append("arrangement_audibility")
                result.warnings.append(
                    f"arrangement_audibility: {s.label} has only "
                    f"{len(s.active_roles)} active role(s) — likely inaudible"
                )

    # ------------------------------------------------------------------
    # Auto-repair pass
    # ------------------------------------------------------------------

    @classmethod
    def _auto_repair(
        cls,
        plan: ProducerArrangementPlanV2,
        result: ExtendedQAResult,
        profile: "SourceQualityProfile",  # type: ignore[name-defined]
    ) -> None:
        """Apply conservative repairs to the plan when gates have failed.

        Strategy:
        - Reduce simultaneous layers in non-hook sections.
        - Force hook sections to carry at least one more role than the verse.
        - Clamp melodic roles per section to the source quality cap.
        - Remove bass+other co-stacking when safe_low_end is required.
        - Suppress "other"/"full_mix" in non-intro/outro sections when
          group_ambiguous_roles is True.
        """
        sections = plan.sections
        if not sections:
            return

        repair_log: list[str] = []

        hooks = [s for s in sections if s.section_type == SectionKind.HOOK]
        verses = [s for s in sections if s.section_type == SectionKind.VERSE]

        # --- Repair: section_contrast / hook_payoff ---
        if "section_contrast" in result.gates_failed or "hook_payoff" in result.gates_failed:
            # Ensure hooks have at least 1 more role than the largest verse,
            # but never exceed the profile's hook layer cap.
            max_verse_roles = max((len(s.active_roles) for s in verses), default=0)
            for hook in hooks:
                # Use the profile cap as an upper bound so we never over-stack.
                target = min(max_verse_roles + 1, profile.max_layers_hook)
                target = max(target, 1)  # always keep at least 1 role
                if len(hook.active_roles) < target and plan.available_roles:
                    extras = [
                        r for r in plan.available_roles
                        if r not in hook.active_roles
                    ]
                    added = extras[: target - len(hook.active_roles)]
                    if added:
                        hook.active_roles = hook.active_roles + added
                        repair_log.append(
                            f"hook_boost: added roles {added} to {hook.label} "
                            "for section contrast"
                        )

            # Trim verse roles to leave room for hook to stand out
            verse_cap = max(1, profile.max_intro_verse_layers)
            for verse in verses:
                if len(verse.active_roles) > verse_cap:
                    trimmed = verse.active_roles[:verse_cap]
                    repair_log.append(
                        f"verse_trim: reduced {verse.label} from "
                        f"{verse.active_roles} → {trimmed}"
                    )
                    verse.active_roles = trimmed

        # --- Repair: melodic_overcrowding ---
        if "melodic_overcrowding" in result.gates_failed:
            cap = profile.max_melodic_layers
            for s in sections:
                if s.section_type in cls._PAYOFF_KINDS:
                    continue
                melodic = [r for r in s.active_roles if r in cls._MELODIC_ROLES]
                if len(melodic) > cap:
                    to_remove = melodic[cap:]
                    new_roles = [r for r in s.active_roles if r not in to_remove]
                    repair_log.append(
                        f"melodic_trim: removed {to_remove} from {s.label} "
                        f"(cap={cap})"
                    )
                    s.active_roles = new_roles

        # --- Repair: low_end_mud ---
        if "low_end_mud" in result.gates_failed:
            for s in sections:
                if "bass" in s.active_roles:
                    new_roles = [r for r in s.active_roles if r not in {"full_mix", "other"}]
                    if len(new_roles) < len(s.active_roles):
                        repair_log.append(
                            f"low_end_destack: removed full_mix/other from "
                            f"{s.label} to reduce low-end mud"
                        )
                        s.active_roles = new_roles

        # --- Repair: group_ambiguous_roles ---
        if profile.group_ambiguous_roles:
            for s in sections:
                if s.section_type in (SectionKind.INTRO, SectionKind.OUTRO):
                    continue
                ambiguous = [r for r in s.active_roles if r in {"other", "full_mix"}]
                if ambiguous:
                    new_roles = [r for r in s.active_roles if r not in {"other", "full_mix"}]
                    if new_roles:  # only drop if at least one concrete role remains
                        repair_log.append(
                            f"ambiguous_group: removed {ambiguous} from {s.label} "
                            "(ai_separated: prefer grouped concrete roles)"
                        )
                        s.active_roles = new_roles

        # --- Repair: arrangement_audibility ---
        if "arrangement_audibility" in result.gates_failed:
            for s in sections:
                if s.section_type in (SectionKind.INTRO, SectionKind.OUTRO,
                                       SectionKind.BRIDGE, SectionKind.BREAKDOWN):
                    continue
                if len(s.active_roles) < 2 and plan.available_roles:
                    extras = [r for r in plan.available_roles if r not in s.active_roles]
                    if extras:
                        s.active_roles = s.active_roles + [extras[0]]
                        repair_log.append(
                            f"audibility_boost: added {extras[0]} to {s.label}"
                        )

        if repair_log:
            result.repair_applied = True
            result.repair_actions.extend(repair_log)


# ---------------------------------------------------------------------------
# QA Retry / Safe Downgrade (Phase 5)
# ---------------------------------------------------------------------------

# Overall score below which a retry / downgrade is triggered
_RETRY_SCORE_THRESHOLD: float = 55.0

# Preset used for safe-downgrade retry
_SAFE_FALLBACK_PRESET: str = "sparse_trap"


@dataclass
class QARetryResult:
    """Result of a QA retry cycle.

    If ``retry_triggered`` is False, the original plan was good enough and
    was returned unchanged.  If True, ``retry_preset`` was used to rebuild
    the plan and ``final_qa`` reflects the post-retry score.
    """

    retry_triggered: bool = False
    retry_preset: Optional[str] = None
    original_score: float = 0.0
    final_qa: Optional[RenderQAResult] = None

    def to_dict(self) -> dict:
        return {
            "retry_triggered": self.retry_triggered,
            "retry_preset": self.retry_preset,
            "original_score": self.original_score,
            "final_qa": self.final_qa.to_dict() if self.final_qa else None,
        }


def evaluate_and_retry(
    plan: ProducerArrangementPlanV2,
    *,
    source_quality: "SourceQualityMode | str | None" = None,
    safe_preset: str = _SAFE_FALLBACK_PRESET,
) -> QARetryResult:
    """Score the plan and optionally rebuild it with a safer preset.

    If the overall QA score is below ``_RETRY_SCORE_THRESHOLD``:
    1. Apply the extended quality gate auto-repair pass.
    2. Re-score; if still below threshold, mark as retried with
       ``safe_preset`` for the caller to use when re-building the plan.

    This function never silently ships a muddy/poor arrangement — it always
    surfaces the quality state so the caller can act.

    Args:
        plan:           The arrangement plan to evaluate.
        source_quality: Source quality mode used for gate checks.
        safe_preset:    Preset name to recommend for a safe rebuild.

    Returns:
        ``QARetryResult`` with retry state and final QA score.
    """
    initial_qa = RenderQAService.score_plan(plan)
    retry_result = QARetryResult(
        retry_triggered=False,
        original_score=initial_qa.score.overall_score,
        final_qa=initial_qa,
    )

    if initial_qa.score.overall_score >= _RETRY_SCORE_THRESHOLD:
        return retry_result

    # Step 1: auto-repair via extended quality gates
    gate_result = ArrangementQualityGates.check_and_repair(plan, source_quality=source_quality)

    # Re-score after repair
    post_repair_qa = RenderQAService.score_plan(plan)
    retry_result.final_qa = post_repair_qa

    if post_repair_qa.score.overall_score >= _RETRY_SCORE_THRESHOLD:
        # Repair was enough — still mark as retried so callers know changes happened
        retry_result.retry_triggered = gate_result.repair_applied
        retry_result.retry_preset = None
        return retry_result

    # Step 2: flag for full rebuild with safe preset
    retry_result.retry_triggered = True
    retry_result.retry_preset = safe_preset

    logger.warning(
        "evaluate_and_retry: plan quality still below threshold after repair "
        "(%.1f < %.1f) — recommending rebuild with preset='%s'",
        post_repair_qa.score.overall_score,
        _RETRY_SCORE_THRESHOLD,
        safe_preset,
    )

    return retry_result

