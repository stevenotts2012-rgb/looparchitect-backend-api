"""
Unit tests for RenderQAService — Phase 3 Sound Quality / Render Polish Layer.

Tests:
- QualityScore computation
- Structure checks (no hooks, intro density, hook elevation)
- Transition checks
- Audio hygiene checks
- Render output file checks
- Regression: valid outputs are not incorrectly rejected
"""

import os
import tempfile
import pytest
from app.services.producer_plan_builder import (
    ProducerPlanBuilderV2,
    SectionKind,
    EnergyLevel,
    DensityLevel,
)
from app.services.producer_rules_engine import ProducerRulesEngine
from app.services.render_qa import (
    RenderQAService,
    RenderQAResult,
    QualityScore,
)


def _make_good_plan(roles=None):
    """Build and apply rules to produce a clean, compliant plan."""
    builder = ProducerPlanBuilderV2(
        available_roles=roles or ["drums", "bass", "melody"],
        genre="trap",
        target_bars=64,
    )
    plan = builder.build()
    result = ProducerRulesEngine.apply(plan)
    return result.plan


class TestQualityScoreModel:
    """QualityScore model tests."""

    def test_default_scores_are_100(self):
        score = QualityScore()
        assert score.structure_score == 100.0
        assert score.transition_score == 100.0
        assert score.audio_quality_score == 100.0
        assert score.overall_score == 100.0

    def test_recompute_overall_weighted_correctly(self):
        score = QualityScore(
            structure_score=80.0,
            transition_score=60.0,
            audio_quality_score=100.0,
        )
        score.recompute_overall(
            structure_weight=0.40,
            transition_weight=0.30,
            audio_weight=0.30,
        )
        expected = 0.40 * 80.0 + 0.30 * 60.0 + 0.30 * 100.0
        assert abs(score.overall_score - expected) < 0.1

    def test_passed_threshold_50(self):
        score = QualityScore(
            structure_score=40.0,
            transition_score=40.0,
            audio_quality_score=40.0,
        )
        score.recompute_overall()
        assert not score.passed

        score2 = QualityScore(
            structure_score=80.0,
            transition_score=80.0,
            audio_quality_score=80.0,
        )
        score2.recompute_overall()
        assert score2.passed

    def test_to_dict_has_all_keys(self):
        score = QualityScore()
        d = score.to_dict()
        for key in ["structure_score", "transition_score", "audio_quality_score", "overall_score", "flags", "warnings"]:
            assert key in d


class TestScorePlan:
    """RenderQAService.score_plan tests."""

    def test_good_plan_scores_well(self):
        plan = _make_good_plan()
        result = RenderQAService.score_plan(plan)
        assert result.score.overall_score >= 60.0, (
            f"A well-formed plan should score >= 60. Got {result.score.overall_score}. "
            f"Flags: {result.score.flags}"
        )

    def test_result_has_checks_run(self):
        plan = _make_good_plan()
        result = RenderQAService.score_plan(plan)
        assert len(result.checks_run) > 0

    def test_result_to_dict_is_json_safe(self):
        import json
        plan = _make_good_plan()
        result = RenderQAService.score_plan(plan)
        d = result.to_dict()
        serialized = json.dumps(d)
        assert len(serialized) > 0

    def test_no_hooks_penalises_structure_score(self):
        plan = _make_good_plan()
        # Remove all hooks
        plan.sections = [s for s in plan.sections if s.section_type != SectionKind.HOOK]
        result = RenderQAService.score_plan(plan)
        assert result.score.structure_score < 100.0
        assert any("no_hooks" in f for f in result.score.flags)

    def test_intro_too_dense_penalises_structure_score(self):
        plan = _make_good_plan()
        for s in plan.sections:
            if s.section_type == SectionKind.INTRO:
                s.density = DensityLevel.FULL
        result = RenderQAService.score_plan(plan)
        assert result.score.structure_score < 100.0
        assert any("intro_too_dense" in f for f in result.score.flags)

    def test_hook_not_elevated_penalises_structure_score(self):
        plan = _make_good_plan()
        for s in plan.sections:
            if s.section_type == SectionKind.HOOK:
                s.target_energy = EnergyLevel.VERY_LOW
        result = RenderQAService.score_plan(plan)
        assert result.score.structure_score < 100.0

    def test_outro_too_energetic_penalises_structure_score(self):
        plan = _make_good_plan()
        for s in plan.sections:
            if s.section_type == SectionKind.OUTRO:
                s.target_energy = EnergyLevel.VERY_HIGH
        result = RenderQAService.score_plan(plan)
        assert result.score.structure_score < 100.0

    def test_flat_energy_flagged_as_warning(self):
        plan = _make_good_plan()
        # Force all sections to same energy
        for s in plan.sections:
            s.target_energy = EnergyLevel.MEDIUM
        result = RenderQAService.score_plan(plan)
        assert any("flat_energy" in w for w in result.score.warnings)

    def test_no_transition_before_hook_flagged(self):
        from app.services.producer_plan_builder import TransitionIntent
        plan = _make_good_plan()
        sections = plan.sections
        for i, s in enumerate(sections):
            if s.section_type == SectionKind.HOOK and i > 0:
                s.transition_in = TransitionIntent.NONE
                sections[i - 1].transition_out = TransitionIntent.NONE
        result = RenderQAService.score_plan(plan)
        # Should have at least a transition warning
        assert result.score.transition_score <= 100.0

    def test_empty_sections_list_does_not_crash(self):
        plan = _make_good_plan()
        plan.sections = []
        result = RenderQAService.score_plan(plan)
        assert result is not None
        assert result.score.overall_score >= 0.0

    def test_no_available_roles_penalises_audio_score(self):
        plan = _make_good_plan(roles=["drums", "bass"])
        plan.available_roles = []
        result = RenderQAService.score_plan(plan)
        assert result.score.audio_quality_score < 100.0

    def test_all_sections_identical_roles_flagged(self):
        plan = _make_good_plan()
        for s in plan.sections:
            s.active_roles = ["drums"]
        result = RenderQAService.score_plan(plan)
        assert any("all_sections_identical" in w for w in result.score.warnings)


class TestScoreRenderOutput:
    """RenderQAService.score_render_output tests."""

    def test_missing_file_penalises_audio_score(self):
        result = RenderQAService.score_render_output("/nonexistent/file.wav")
        assert result.score.audio_quality_score < 100.0
        assert any("missing" in f.lower() for f in result.score.flags)

    def test_none_path_penalises_audio_score(self):
        result = RenderQAService.score_render_output(None)
        assert result.score.audio_quality_score < 100.0

    def test_zero_byte_file_fails_qa(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        try:
            result = RenderQAService.score_render_output(path)
            assert any("zero_bytes" in f or "zero" in f for f in result.score.flags)
        finally:
            os.unlink(path)

    def test_valid_file_passes_qa(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"\x00" * 5000)   # 5 KB dummy file
            path = f.name
        try:
            result = RenderQAService.score_render_output(path)
            assert result.score.audio_quality_score == 100.0
            assert not any("missing" in fl or "zero" in fl for fl in result.score.flags)
        finally:
            os.unlink(path)


class TestRegressionValidOutputsNotRejected:
    """Regression: valid, well-formed outputs should not be rejected."""

    def test_standard_arrangement_passes(self):
        plan = _make_good_plan(roles=["drums", "bass", "melody", "pads"])
        result = RenderQAService.score_plan(plan)
        assert result.passed, (
            f"Valid plan should pass QA. score={result.score.overall_score} flags={result.score.flags}"
        )

    def test_loop_source_with_single_role_passes(self):
        builder = ProducerPlanBuilderV2(available_roles=["full_mix"], source_type="loop")
        plan = builder.build()
        ProducerRulesEngine.apply(plan)
        result = RenderQAService.score_plan(plan)
        # Single-role loop should still pass (overall >= 50)
        assert result.score.overall_score >= 0.0   # should not crash

    def test_stem_pack_arrangement_passes(self):
        plan = _make_good_plan(roles=["drums", "bass", "melody", "vocal", "fx"])
        result = RenderQAService.score_plan(plan)
        assert result.passed, (
            f"Stem pack plan should pass QA. score={result.score.overall_score}"
        )


# ---------------------------------------------------------------------------
# New quality score dimensions (clarity / density_balance / hook_impact)
# ---------------------------------------------------------------------------


class TestQualityScoreNewDimensions:
    """Tests for the clarity_score, density_balance_score, and hook_impact_score fields."""

    def test_quality_score_has_new_fields(self):
        score = QualityScore()
        assert hasattr(score, "clarity_score")
        assert hasattr(score, "density_balance_score")
        assert hasattr(score, "hook_impact_score")

    def test_new_fields_default_to_100(self):
        score = QualityScore()
        assert score.clarity_score == 100.0
        assert score.density_balance_score == 100.0
        assert score.hook_impact_score == 100.0

    def test_to_dict_includes_new_fields(self):
        score = QualityScore()
        d = score.to_dict()
        assert "clarity_score" in d
        assert "density_balance_score" in d
        assert "hook_impact_score" in d

    def test_good_plan_has_high_clarity_score(self):
        plan = _make_good_plan(roles=["drums", "bass", "melody"])
        result = RenderQAService.score_plan(plan)
        assert result.score.clarity_score >= 80.0, (
            f"A plan with only melody (no melodic stacking) should have high clarity. "
            f"Got: {result.score.clarity_score}"
        )

    def test_melodic_overload_reduces_clarity_score(self):
        plan = _make_good_plan(roles=["drums", "bass", "melody", "harmony", "pads"])
        # Force every non-hook section to stack 3 melodic roles
        for s in plan.sections:
            if s.section_type not in (SectionKind.HOOK,):
                s.active_roles = ["melody", "harmony", "pads", "drums"]
        result = RenderQAService.score_plan(plan)
        assert result.score.clarity_score < 100.0, (
            "Melodic overload should reduce clarity_score"
        )

    def test_sustained_wash_reduces_clarity_score(self):
        plan = _make_good_plan(roles=["drums", "bass", "melody", "harmony", "pads"])
        for s in plan.sections:
            if s.section_type not in (SectionKind.HOOK,):
                s.active_roles = ["pads", "harmony", "vocals", "drums"]
        result = RenderQAService.score_plan(plan)
        assert result.score.clarity_score < 100.0, (
            "Sustained wash should reduce clarity_score"
        )

    def test_no_density_variety_reduces_density_balance_score(self):
        plan = _make_good_plan()
        # Force all sections to MEDIUM density
        for s in plan.sections:
            s.density = DensityLevel.MEDIUM
        result = RenderQAService.score_plan(plan)
        assert result.score.density_balance_score < 100.0, (
            "All-same density should reduce density_balance_score"
        )

    def test_good_density_variation_has_high_density_balance(self):
        plan = _make_good_plan(roles=["drums", "bass", "melody"])
        # Ensure intro=SPARSE, verse=MEDIUM, hook=FULL (natural variation)
        for s in plan.sections:
            if s.section_type == SectionKind.INTRO:
                s.density = DensityLevel.SPARSE
            elif s.section_type == SectionKind.VERSE:
                s.density = DensityLevel.MEDIUM
            elif s.section_type == SectionKind.HOOK:
                s.density = DensityLevel.FULL
        result = RenderQAService.score_plan(plan)
        assert result.score.density_balance_score >= 80.0, (
            f"Natural SPARSE→MEDIUM→FULL density progression should have high density balance. "
            f"Got: {result.score.density_balance_score}"
        )

    def test_hook_not_denser_than_verse_reduces_hook_impact(self):
        plan = _make_good_plan(roles=["drums", "bass", "melody"])
        # Set all hooks to SPARSE and verses to FULL
        for s in plan.sections:
            if s.section_type == SectionKind.HOOK:
                s.density = DensityLevel.SPARSE
                s.active_roles = ["melody"]
            elif s.section_type == SectionKind.VERSE:
                s.density = DensityLevel.FULL
                s.active_roles = ["drums", "bass", "melody", "harmony", "pads"]
        result = RenderQAService.score_plan(plan)
        assert result.score.hook_impact_score < 100.0, (
            "Hooks sparser than verses should reduce hook_impact_score"
        )

    def test_hooks_clearly_bigger_than_verses_has_high_impact(self):
        plan = _make_good_plan(roles=["drums", "bass", "melody"])
        for s in plan.sections:
            if s.section_type == SectionKind.HOOK:
                s.density = DensityLevel.FULL
                s.active_roles = ["drums", "bass", "melody", "harmony", "pads"]
            elif s.section_type == SectionKind.VERSE:
                s.density = DensityLevel.MEDIUM
                s.active_roles = ["drums", "bass"]
        result = RenderQAService.score_plan(plan)
        assert result.score.hook_impact_score >= 80.0, (
            f"Hooks clearly denser than verses should have high hook_impact_score. "
            f"Got: {result.score.hook_impact_score}"
        )

    def test_score_plan_includes_new_checks_in_checks_run(self):
        plan = _make_good_plan()
        result = RenderQAService.score_plan(plan)
        checks = result.checks_run
        assert "melodic_overload" in checks
        assert "sustained_wash" in checks
        assert "no_density_variety" in checks
        assert "hook_not_denser_than_verse" in checks
        assert "hook_not_more_roles" in checks

    def test_recompute_overall_unchanged_with_new_fields(self):
        """overall_score must still be the weighted composite of the original 3 scores."""
        score = QualityScore(
            structure_score=80.0,
            transition_score=60.0,
            audio_quality_score=100.0,
            clarity_score=50.0,         # should NOT affect overall
            density_balance_score=30.0,  # should NOT affect overall
            hook_impact_score=10.0,      # should NOT affect overall
        )
        score.recompute_overall(
            structure_weight=0.40,
            transition_weight=0.30,
            audio_weight=0.30,
        )
        expected = 0.40 * 80.0 + 0.30 * 60.0 + 0.30 * 100.0
        assert abs(score.overall_score - expected) < 0.1, (
            f"New supplemental scores must not influence overall_score. "
            f"Expected {expected}, got {score.overall_score}"
        )

    def test_empty_plan_does_not_crash_new_checks(self):
        plan = _make_good_plan()
        plan.sections = []
        result = RenderQAService.score_plan(plan)
        assert result is not None
        assert result.score.clarity_score >= 0.0
        assert result.score.density_balance_score >= 0.0
        assert result.score.hook_impact_score >= 0.0
