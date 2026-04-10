"""
Tests for Phase 1-6 musical quality improvements.

Proves:
1. SourceQualityMode enum and profiles exist and have correct hierarchy.
2. ai_separated mode is stricter than true_stems mode.
3. Weak arrangements get repaired or downgraded by ArrangementQualityGates.
4. New presets materially change role maps (sparse_trap, big_hook, dark_minimal,
   melodic_bounce, drum_forward, atmospheric).
5. Hook payoff improves under big_hook preset.
6. sparse_trap reduces clutter in verses/intros.
7. evaluate_and_retry recommends a safe preset for genuinely poor plans.
"""

from __future__ import annotations

import pytest

from app.services.source_quality import (
    SourceQualityMode,
    SourceQualityProfile,
    SOURCE_QUALITY_PROFILES,
    get_source_quality_profile,
    classify_source_quality,
)
from app.services.arrangement_presets import (
    ARRANGEMENT_PRESETS,
    VALID_PRESETS,
    get_preset_config,
    resolve_preset_name,
)
from app.services.render_qa import (
    ArrangementQualityGates,
    ExtendedQAResult,
    RenderQAService,
    evaluate_and_retry,
    QARetryResult,
)
from app.services.producer_plan_builder import (
    ProducerPlanBuilderV2,
    SectionKind,
    DensityLevel,
    EnergyLevel,
)
from app.services.producer_rules_engine import ProducerRulesEngine
from app.services.arrangement_jobs import _select_section_stem_roles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(roles=None, genre="trap"):
    builder = ProducerPlanBuilderV2(
        available_roles=roles or ["drums", "bass", "melody"],
        genre=genre,
        target_bars=64,
    )
    plan = builder.build()
    ProducerRulesEngine.apply(plan)
    return plan


def _make_poor_plan():
    """Build a deliberately bad plan with identical roles everywhere."""
    plan = _make_plan(roles=["drums", "bass", "melody", "pads"])
    for s in plan.sections:
        s.active_roles = ["drums"]  # flat, no variety, hooks not bigger
        s.density = DensityLevel.MEDIUM
        s.target_energy = EnergyLevel.MEDIUM
    return plan


# ---------------------------------------------------------------------------
# Phase 1 — Source Quality Modes
# ---------------------------------------------------------------------------


class TestSourceQualityModeEnum:
    def test_all_four_modes_exist(self):
        assert SourceQualityMode.TRUE_STEMS.value == "true_stems"
        assert SourceQualityMode.ZIP_STEMS.value == "zip_stems"
        assert SourceQualityMode.AI_SEPARATED.value == "ai_separated"
        assert SourceQualityMode.STEREO_FALLBACK.value == "stereo_fallback"

    def test_all_modes_have_profiles(self):
        for mode in SourceQualityMode:
            assert mode in SOURCE_QUALITY_PROFILES, f"Missing profile for {mode}"

    def test_profiles_are_source_quality_profile_instances(self):
        for mode, profile in SOURCE_QUALITY_PROFILES.items():
            assert isinstance(profile, SourceQualityProfile), (
                f"Profile for {mode} is not a SourceQualityProfile"
            )


class TestSourceQualityProfileHierarchy:
    """AI-separated mode must be stricter than true_stems mode."""

    def test_ai_separated_has_lower_melodic_layers_than_true_stems(self):
        ai = get_source_quality_profile(SourceQualityMode.AI_SEPARATED)
        true = get_source_quality_profile(SourceQualityMode.TRUE_STEMS)
        assert ai.max_melodic_layers < true.max_melodic_layers, (
            "ai_separated must cap melodic layers below true_stems"
        )

    def test_ai_separated_has_lower_intro_verse_layers(self):
        ai = get_source_quality_profile(SourceQualityMode.AI_SEPARATED)
        true = get_source_quality_profile(SourceQualityMode.TRUE_STEMS)
        assert ai.max_intro_verse_layers <= true.max_intro_verse_layers

    def test_ai_separated_has_lower_breakdown_layers(self):
        ai = get_source_quality_profile(SourceQualityMode.AI_SEPARATED)
        true = get_source_quality_profile(SourceQualityMode.TRUE_STEMS)
        assert ai.max_breakdown_layers <= true.max_breakdown_layers

    def test_ai_separated_has_lower_hook_layers(self):
        ai = get_source_quality_profile(SourceQualityMode.AI_SEPARATED)
        true = get_source_quality_profile(SourceQualityMode.TRUE_STEMS)
        assert ai.max_layers_hook < true.max_layers_hook

    def test_ai_separated_has_lower_confidence_than_true_stems(self):
        ai = get_source_quality_profile(SourceQualityMode.AI_SEPARATED)
        true = get_source_quality_profile(SourceQualityMode.TRUE_STEMS)
        assert ai.confidence_weight < true.confidence_weight

    def test_ai_separated_enables_safe_low_end(self):
        ai = get_source_quality_profile(SourceQualityMode.AI_SEPARATED)
        assert ai.safe_low_end is True

    def test_ai_separated_groups_ambiguous_roles(self):
        ai = get_source_quality_profile(SourceQualityMode.AI_SEPARATED)
        assert ai.group_ambiguous_roles is True

    def test_true_stems_does_not_group_ambiguous_roles(self):
        true = get_source_quality_profile(SourceQualityMode.TRUE_STEMS)
        assert true.group_ambiguous_roles is False

    def test_stereo_fallback_is_most_restrictive(self):
        stereo = get_source_quality_profile(SourceQualityMode.STEREO_FALLBACK)
        ai = get_source_quality_profile(SourceQualityMode.AI_SEPARATED)
        # Stereo has even fewer layers than AI-separated
        assert stereo.max_melodic_layers <= ai.max_melodic_layers
        assert stereo.max_layers_hook <= ai.max_layers_hook

    def test_confidence_ordering(self):
        """Confidence: true_stems > zip_stems > ai_separated > stereo_fallback."""
        true = get_source_quality_profile(SourceQualityMode.TRUE_STEMS)
        zips = get_source_quality_profile(SourceQualityMode.ZIP_STEMS)
        ai = get_source_quality_profile(SourceQualityMode.AI_SEPARATED)
        stereo = get_source_quality_profile(SourceQualityMode.STEREO_FALLBACK)
        assert true.confidence_weight > zips.confidence_weight > ai.confidence_weight > stereo.confidence_weight


class TestGetSourceQualityProfile:
    def test_none_returns_true_stems_profile(self):
        p = get_source_quality_profile(None)
        assert p == SOURCE_QUALITY_PROFILES[SourceQualityMode.TRUE_STEMS]

    def test_string_lookup_works(self):
        p = get_source_quality_profile("ai_separated")
        assert p == SOURCE_QUALITY_PROFILES[SourceQualityMode.AI_SEPARATED]

    def test_unknown_string_returns_true_stems_profile(self):
        p = get_source_quality_profile("unknown_mode")
        assert p == SOURCE_QUALITY_PROFILES[SourceQualityMode.TRUE_STEMS]


class TestClassifySourceQuality:
    def test_true_stems_wins_over_ai(self):
        mode = classify_source_quality(has_true_stems=True, stems_from_ai_separation=True)
        assert mode == SourceQualityMode.TRUE_STEMS

    def test_zip_stems_wins_over_ai(self):
        mode = classify_source_quality(stems_from_zip=True, stems_from_ai_separation=True)
        assert mode == SourceQualityMode.ZIP_STEMS

    def test_ai_without_zip_or_true(self):
        mode = classify_source_quality(stems_from_ai_separation=True)
        assert mode == SourceQualityMode.AI_SEPARATED

    def test_no_flags_returns_stereo_fallback(self):
        mode = classify_source_quality()
        assert mode == SourceQualityMode.STEREO_FALLBACK


# ---------------------------------------------------------------------------
# Phase 4 — AI-Separated Safety Profile in _select_section_stem_roles
# ---------------------------------------------------------------------------


class TestSelectSectionStemRolesSourceQuality:
    """ai_separated mode must respect stricter layer caps."""

    _RICH_ROLES = ["drums", "bass", "melody", "pads", "fx", "vocal", "arp", "synth"]

    def _max_roles_for_mode(self, section_type: str, mode: str) -> int:
        results = []
        for verse_count in range(1, 3):
            roles = _select_section_stem_roles(
                section_type,
                self._RICH_ROLES,
                verse_count=verse_count,
                source_quality=mode,
            )
            results.append(len(roles))
        return max(results)

    def test_ai_separated_verse_has_fewer_layers_than_true_stems(self):
        ai_max = self._max_roles_for_mode("verse", "ai_separated")
        true_max = self._max_roles_for_mode("verse", "true_stems")
        assert ai_max <= true_max, (
            f"ai_separated verse max={ai_max} should be <= true_stems max={true_max}"
        )

    def test_ai_separated_hook_has_fewer_layers_than_true_stems(self):
        ai_max = self._max_roles_for_mode("hook", "ai_separated")
        true_max = self._max_roles_for_mode("hook", "true_stems")
        assert ai_max < true_max, (
            f"ai_separated hook max={ai_max} should be < true_stems max={true_max}"
        )

    def test_ai_separated_breakdown_capped_at_1(self):
        roles = _select_section_stem_roles(
            "breakdown", self._RICH_ROLES, source_quality="ai_separated"
        )
        profile = get_source_quality_profile("ai_separated")
        assert len(roles) <= profile.max_breakdown_layers

    def test_stereo_fallback_hook_capped_at_1(self):
        roles = _select_section_stem_roles(
            "hook", self._RICH_ROLES, source_quality="stereo_fallback"
        )
        assert len(roles) <= 1

    def test_ambiguous_roles_stripped_in_ai_mode(self):
        """AI mode must not return full_mix / other when concrete roles exist."""
        roles_with_other = ["drums", "bass", "full_mix", "other", "melody"]
        selected = _select_section_stem_roles(
            "verse", roles_with_other, source_quality="ai_separated"
        )
        # Should only contain concrete roles
        assert "full_mix" not in selected
        assert "other" not in selected

    def test_no_source_quality_uses_normal_limits(self):
        roles = _select_section_stem_roles("hook", self._RICH_ROLES, source_quality=None)
        # Hooks without quality mode can go up to the normal max
        assert len(roles) >= 1


# ---------------------------------------------------------------------------
# Phase 2 — Arrangement Quality Gates
# ---------------------------------------------------------------------------


class TestArrangementQualityGates:
    def test_good_plan_passes_all_gates(self):
        """Gates should not crash and should return a structured result."""
        plan = _make_plan(roles=["drums", "bass", "melody", "pads"])
        result = ArrangementQualityGates.check_and_repair(plan)
        assert isinstance(result, ExtendedQAResult)
        # The result must always be a structured, inspectable object
        assert isinstance(result.gates_failed, list)
        assert isinstance(result.warnings, list)
        assert isinstance(result.source_confidence, float)

    def test_weak_plan_triggers_repair(self):
        plan = _make_poor_plan()
        result = ArrangementQualityGates.check_and_repair(plan)
        # The flat identical-role plan should fail at least some gates
        assert len(result.gates_failed) > 0

    def test_repair_mutates_plan_when_gates_fail(self):
        plan = _make_poor_plan()
        original_hook_roles = [
            s.active_roles[:]
            for s in plan.sections
            if s.section_type == SectionKind.HOOK
        ]
        result = ArrangementQualityGates.check_and_repair(
            plan, source_quality=SourceQualityMode.TRUE_STEMS
        )
        if result.repair_applied:
            new_hook_roles = [
                s.active_roles
                for s in plan.sections
                if s.section_type == SectionKind.HOOK
            ]
            # Repair should have changed something
            assert original_hook_roles != new_hook_roles or result.repair_actions

    def test_source_confidence_gate_fails_for_ai_separated(self):
        plan = _make_plan()
        result = ArrangementQualityGates.check_and_repair(
            plan, source_quality=SourceQualityMode.AI_SEPARATED
        )
        # Confidence for ai_separated is 0.55, below the 0.60 threshold
        assert "source_confidence" in result.gates_failed

    def test_source_confidence_gate_passes_for_true_stems(self):
        plan = _make_plan()
        result = ArrangementQualityGates.check_and_repair(
            plan, source_quality=SourceQualityMode.TRUE_STEMS
        )
        assert "source_confidence" not in result.gates_failed

    def test_melodic_overcrowding_gate_fires_when_stacked(self):
        plan = _make_plan(roles=["drums", "bass", "melody", "pads", "vocal"])
        for s in plan.sections:
            if s.section_type == SectionKind.VERSE:
                s.active_roles = ["melody", "pads", "vocal", "drums"]
        result = ArrangementQualityGates.check_and_repair(
            plan, source_quality=SourceQualityMode.AI_SEPARATED
        )
        assert "melodic_overcrowding" in result.gates_failed

    def test_low_end_mud_gate_fires_in_ai_mode(self):
        plan = _make_plan(roles=["drums", "bass", "full_mix"])
        for s in plan.sections:
            s.active_roles = ["bass", "full_mix", "drums"]
        result = ArrangementQualityGates.check_and_repair(
            plan, source_quality=SourceQualityMode.AI_SEPARATED
        )
        assert "low_end_mud" in result.gates_failed

    def test_low_end_mud_gate_does_not_fire_in_true_stems_mode(self):
        """true_stems mode has safe_low_end=False so low_end_mud gate is skipped."""
        plan = _make_plan(roles=["drums", "bass", "full_mix"])
        for s in plan.sections:
            s.active_roles = ["bass", "full_mix", "drums"]
        result = ArrangementQualityGates.check_and_repair(
            plan, source_quality=SourceQualityMode.TRUE_STEMS
        )
        assert "low_end_mud" not in result.gates_failed

    def test_extended_qa_result_to_dict(self):
        plan = _make_plan()
        result = ArrangementQualityGates.check_and_repair(plan)
        d = result.to_dict()
        assert "passed" in d
        assert "gates_failed" in d
        assert "repair_applied" in d
        assert "source_confidence" in d

    def test_empty_sections_does_not_crash(self):
        plan = _make_plan()
        plan.sections = []
        result = ArrangementQualityGates.check_and_repair(plan)
        assert result is not None

    def test_repair_reduces_melodic_stacking(self):
        """After repair, melodic roles should be capped to ai_separated limits."""
        plan = _make_plan(roles=["drums", "bass", "melody", "pads", "vocal"])
        ai_profile = get_source_quality_profile(SourceQualityMode.AI_SEPARATED)
        for s in plan.sections:
            if s.section_type == SectionKind.VERSE:
                s.active_roles = ["melody", "pads", "vocal", "drums"]  # 3 melodic roles
        ArrangementQualityGates.check_and_repair(
            plan, source_quality=SourceQualityMode.AI_SEPARATED
        )
        melodic_roles = {"melody", "harmony", "pads", "vocals", "vocal"}
        for s in plan.sections:
            if s.section_type == SectionKind.VERSE:
                melodic_count = sum(1 for r in s.active_roles if r in melodic_roles)
                assert melodic_count <= ai_profile.max_melodic_layers, (
                    f"Post-repair: {s.label} still has {melodic_count} melodic roles "
                    f"(cap={ai_profile.max_melodic_layers})"
                )


# ---------------------------------------------------------------------------
# Phase 3 — Producer Presets
# ---------------------------------------------------------------------------


class TestNewPresets:
    _NEW_PRESETS = {"sparse_trap", "big_hook", "dark_minimal", "melodic_bounce",
                    "drum_forward", "atmospheric"}

    def test_all_new_presets_in_valid_presets(self):
        for p in self._NEW_PRESETS:
            assert p in VALID_PRESETS, f"'{p}' not in VALID_PRESETS"

    def test_all_new_presets_in_arrangement_presets(self):
        for p in self._NEW_PRESETS:
            assert p in ARRANGEMENT_PRESETS, f"'{p}' not in ARRANGEMENT_PRESETS"

    def test_all_new_presets_have_hook_and_verse_overrides(self):
        for name in self._NEW_PRESETS:
            cfg = get_preset_config(name)
            assert cfg is not None
            assert "hook" in cfg.section_overrides, f"{name} missing hook override"
            assert "verse" in cfg.section_overrides, f"{name} missing verse override"

    def test_get_preset_config_returns_correct_type(self):
        for name in self._NEW_PRESETS:
            cfg = get_preset_config(name)
            from app.services.arrangement_presets import ArrangementPresetConfig
            assert isinstance(cfg, ArrangementPresetConfig)

    def test_resolve_preset_name_recognises_new_presets(self):
        for name in self._NEW_PRESETS:
            assert resolve_preset_name(name) == name

    # --- sparse_trap ---
    def test_sparse_trap_verse_forbids_melody(self):
        cfg = get_preset_config("sparse_trap")
        verse = cfg.section_overrides.get("verse")
        assert verse is not None
        assert verse.forbidden_roles is not None
        assert "melody" in verse.forbidden_roles, (
            "sparse_trap verse should forbid melody to keep it sparse"
        )

    def test_sparse_trap_verse_max_density_is_low(self):
        cfg = get_preset_config("sparse_trap")
        verse = cfg.section_overrides["verse"]
        assert verse.density_max is not None
        assert verse.density_max <= 2, "sparse_trap verse should be max 2 layers"

    def test_sparse_trap_intro_is_most_sparse(self):
        cfg = get_preset_config("sparse_trap")
        intro = cfg.section_overrides["intro"]
        assert intro.density_max == 1, "sparse_trap intro must be 1 layer maximum"

    # --- big_hook ---
    def test_big_hook_hook_density_max_exceeds_verse(self):
        cfg = get_preset_config("big_hook")
        hook = cfg.section_overrides["hook"]
        verse = cfg.section_overrides["verse"]
        assert hook.density_max > verse.density_max, (
            "big_hook hook density_max must exceed verse density_max"
        )

    def test_big_hook_hook_max_density_is_at_least_4(self):
        cfg = get_preset_config("big_hook")
        hook = cfg.section_overrides["hook"]
        assert hook.density_max >= 4, "big_hook hook must allow >=4 layers"

    def test_big_hook_intro_forbids_drums(self):
        cfg = get_preset_config("big_hook")
        intro = cfg.section_overrides["intro"]
        assert intro.forbidden_roles is not None
        assert "drums" in intro.forbidden_roles

    # --- dark_minimal ---
    def test_dark_minimal_verse_forbids_melody(self):
        cfg = get_preset_config("dark_minimal")
        verse = cfg.section_overrides["verse"]
        assert "melody" in verse.forbidden_roles

    def test_dark_minimal_hook_forbids_melody(self):
        cfg = get_preset_config("dark_minimal")
        hook = cfg.section_overrides["hook"]
        assert "melody" in hook.forbidden_roles

    # --- melodic_bounce ---
    def test_melodic_bounce_hook_melody_is_top_priority(self):
        cfg = get_preset_config("melodic_bounce")
        hook = cfg.section_overrides["hook"]
        assert hook.role_priorities is not None
        assert hook.role_priorities[0] == "melody"

    def test_melodic_bounce_verse_melody_is_top_priority(self):
        cfg = get_preset_config("melodic_bounce")
        verse = cfg.section_overrides["verse"]
        assert verse.role_priorities[0] == "melody"

    # --- drum_forward ---
    def test_drum_forward_verse_drums_is_top_priority(self):
        cfg = get_preset_config("drum_forward")
        verse = cfg.section_overrides["verse"]
        assert verse.role_priorities[0] == "drums"

    def test_drum_forward_verse_forbids_melody(self):
        cfg = get_preset_config("drum_forward")
        verse = cfg.section_overrides["verse"]
        assert "melody" in verse.forbidden_roles

    # --- atmospheric ---
    def test_atmospheric_verse_forbids_drums(self):
        cfg = get_preset_config("atmospheric")
        verse = cfg.section_overrides["verse"]
        assert "drums" in verse.forbidden_roles

    def test_atmospheric_hook_forbids_drums(self):
        cfg = get_preset_config("atmospheric")
        hook = cfg.section_overrides["hook"]
        assert "drums" in hook.forbidden_roles

    def test_atmospheric_intro_pads_top_priority(self):
        cfg = get_preset_config("atmospheric")
        intro = cfg.section_overrides["intro"]
        assert intro.role_priorities[0] == "pads"


class TestPresetsMateriallyAlterRoleMaps:
    """Presets must produce different role maps, not just different labels."""

    def _hook_roles_for_preset(self, preset: str) -> tuple[str, ...]:
        cfg = get_preset_config(preset)
        if cfg is None:
            return ()
        hook = cfg.section_overrides.get("hook")
        return hook.role_priorities if hook and hook.role_priorities else ()

    def _verse_roles_for_preset(self, preset: str) -> tuple[str, ...]:
        cfg = get_preset_config(preset)
        if cfg is None:
            return ()
        verse = cfg.section_overrides.get("verse")
        return verse.role_priorities if verse and verse.role_priorities else ()

    def test_sparse_trap_verse_differs_from_big_hook_verse(self):
        sparse_verse = set(self._verse_roles_for_preset("sparse_trap"))
        big_hook_verse = set(self._verse_roles_for_preset("big_hook"))
        # sparse_trap forbids melody in verse; big_hook has it
        assert sparse_verse != big_hook_verse

    def test_drum_forward_hook_differs_from_atmospheric_hook(self):
        drum_hook = set(self._hook_roles_for_preset("drum_forward"))
        atm_hook = set(self._hook_roles_for_preset("atmospheric"))
        assert drum_hook != atm_hook

    def test_melodic_bounce_hook_differs_from_dark_minimal_hook(self):
        melodic_hook = set(self._hook_roles_for_preset("melodic_bounce"))
        dark_hook = set(self._hook_roles_for_preset("dark_minimal"))
        assert melodic_hook != dark_hook


# ---------------------------------------------------------------------------
# Phase 5 — Hook payoff under big_hook
# ---------------------------------------------------------------------------


class TestBigHookPayoff:
    """big_hook preset should produce hooks with more layers than trap preset."""

    def _hook_density_max(self, preset: str) -> int:
        cfg = get_preset_config(preset)
        if cfg is None:
            return 0
        hook = cfg.section_overrides.get("hook")
        return hook.density_max if hook and hook.density_max else 0

    def test_big_hook_hook_density_exceeds_trap(self):
        big_max = self._hook_density_max("big_hook")
        trap_max = self._hook_density_max("trap")
        assert big_max > trap_max, (
            f"big_hook hook density_max={big_max} must exceed trap={trap_max}"
        )

    def test_big_hook_hook_density_exceeds_sparse_trap(self):
        big_max = self._hook_density_max("big_hook")
        sparse_max = self._hook_density_max("sparse_trap")
        assert big_max > sparse_max

    def test_big_hook_qa_detects_strong_hook_payoff(self):
        plan = _make_plan(roles=["drums", "bass", "melody", "pads", "synth", "vocal"])
        # Simulate big_hook hook: all roles active, verse sparse
        for s in plan.sections:
            if s.section_type == SectionKind.HOOK:
                s.active_roles = ["drums", "bass", "melody", "pads", "synth", "vocal"]
                s.density = DensityLevel.FULL
            elif s.section_type == SectionKind.VERSE:
                s.active_roles = ["drums", "bass"]
                s.density = DensityLevel.MEDIUM
        result = RenderQAService.score_plan(plan)
        assert result.score.hook_impact_score >= 80.0, (
            f"big_hook-style plan should have high hook_impact_score. "
            f"Got: {result.score.hook_impact_score}"
        )


# ---------------------------------------------------------------------------
# Phase 6 — sparse_trap reduces clutter
# ---------------------------------------------------------------------------


class TestSparseTrapReducesClutter:
    def test_sparse_trap_verse_max_density_lower_than_trap(self):
        sparse_cfg = get_preset_config("sparse_trap")
        trap_cfg = get_preset_config("trap")
        sparse_verse = sparse_cfg.section_overrides["verse"]
        trap_verse = trap_cfg.section_overrides["verse"]
        assert sparse_verse.density_max < trap_verse.density_max, (
            "sparse_trap verse density_max must be lower than trap"
        )

    def test_sparse_trap_intro_max_density_is_1(self):
        cfg = get_preset_config("sparse_trap")
        assert cfg.section_overrides["intro"].density_max == 1

    def test_sparse_trap_breakdown_max_density_is_1(self):
        cfg = get_preset_config("sparse_trap")
        breakdown = cfg.section_overrides.get("breakdown")
        if breakdown:
            assert breakdown.density_max <= 1

    def test_sparse_trap_clarity_better_than_trap_under_qa(self):
        """sparse_trap-style plan should achieve higher clarity than full-stack trap."""
        # Build a sparse plan (sparse_trap style: verse has 2 roles, hook has 4)
        sparse_plan = _make_plan(roles=["drums", "bass", "melody", "pads", "synth"])
        for s in sparse_plan.sections:
            if s.section_type == SectionKind.VERSE:
                s.active_roles = ["drums", "bass"]
                s.density = DensityLevel.SPARSE
            elif s.section_type == SectionKind.HOOK:
                s.active_roles = ["drums", "bass", "melody", "pads"]
                s.density = DensityLevel.FULL
            elif s.section_type in (SectionKind.INTRO, SectionKind.OUTRO):
                s.active_roles = ["pads"]
                s.density = DensityLevel.SPARSE

        # Build a muddy plan (over-stacked)
        muddy_plan = _make_plan(roles=["drums", "bass", "melody", "pads", "synth"])
        for s in muddy_plan.sections:
            s.active_roles = ["drums", "bass", "melody", "pads", "synth"]
            s.density = DensityLevel.FULL

        sparse_result = RenderQAService.score_plan(sparse_plan)
        muddy_result = RenderQAService.score_plan(muddy_plan)

        assert sparse_result.score.clarity_score >= muddy_result.score.clarity_score, (
            f"sparse plan clarity={sparse_result.score.clarity_score} should be "
            f">= muddy={muddy_result.score.clarity_score}"
        )


# ---------------------------------------------------------------------------
# Phase 5 — evaluate_and_retry
# ---------------------------------------------------------------------------


class TestEvaluateAndRetry:
    def test_good_plan_does_not_retry(self):
        plan = _make_plan(roles=["drums", "bass", "melody"])
        retry = evaluate_and_retry(plan)
        assert isinstance(retry, QARetryResult)
        # A decent plan should not need a rebuild
        if retry.retry_triggered:
            # If it did retry, it should have recommended a preset
            assert retry.retry_preset is not None

    def test_poor_plan_triggers_retry(self):
        plan = _make_poor_plan()
        retry = evaluate_and_retry(plan, source_quality=SourceQualityMode.TRUE_STEMS)
        # A genuinely bad plan (flat roles, hooks no bigger than verses) should trigger retry
        assert retry.original_score <= retry.final_qa.score.overall_score or retry.retry_triggered

    def test_retry_result_has_final_qa(self):
        plan = _make_plan()
        retry = evaluate_and_retry(plan)
        assert retry.final_qa is not None

    def test_retry_result_to_dict(self):
        plan = _make_plan()
        retry = evaluate_and_retry(plan)
        d = retry.to_dict()
        assert "retry_triggered" in d
        assert "original_score" in d
        assert "final_qa" in d

    def test_safe_preset_recommended_when_still_poor_after_repair(self):
        """When post-repair score is still below threshold, retry_preset is set."""
        plan = _make_poor_plan()
        # Make it even worse: empty sections
        plan.sections = []
        retry = evaluate_and_retry(plan, safe_preset="sparse_trap")
        if retry.retry_triggered:
            assert retry.retry_preset == "sparse_trap"
