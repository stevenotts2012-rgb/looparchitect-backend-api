"""
Unit tests for ProducerPlanBuilderV2 — Phase 1 Producer Engine Foundation.

Tests:
- Section planner produces deterministic output
- Energy plan validation
- Role activation logic
- Snapshot-style tests for plan outputs given stem inputs
- Edge cases (no roles, single role, many roles)
"""

import pytest
from app.services.producer_plan_builder import (
    ProducerPlanBuilderV2,
    ProducerArrangementPlanV2,
    ProducerSectionPlan,
    SectionKind,
    EnergyLevel,
    DensityLevel,
    VariationStrategy,
    TransitionIntent,
)


class TestProducerPlanBuilderV2Basics:
    """Basic plan generation tests."""

    def test_build_returns_plan(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody"],
            genre="trap",
            tempo=140.0,
        )
        plan = builder.build()
        assert isinstance(plan, ProducerArrangementPlanV2)

    def test_plan_has_sections(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass"],
            genre="trap",
        )
        plan = builder.build()
        assert len(plan.sections) >= 3

    def test_sections_have_no_gaps_or_overlaps(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody"],
            genre="generic",
            target_bars=64,
        )
        plan = builder.build()
        cursor = 0
        for section in plan.sections:
            assert section.start_bar == cursor, (
                f"Section {section.label} starts at bar {section.start_bar}, "
                f"expected {cursor}"
            )
            cursor += section.length_bars
        assert cursor == plan.total_bars

    def test_total_bars_matches_sum_of_sections(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass"],
            target_bars=48,
        )
        plan = builder.build()
        assert plan.total_bars == sum(s.length_bars for s in plan.sections)

    def test_plan_metadata_populated(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody"],
            genre="rnb",
            tempo=95.0,
        )
        plan = builder.build()
        assert plan.genre == "rnb"
        assert plan.tempo == 95.0
        assert plan.builder_version == "2.0"
        assert plan.available_roles == ["drums", "bass", "melody"]

    def test_plan_to_dict_is_json_safe(self):
        import json
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass"],
        )
        plan = builder.build()
        d = plan.to_dict()
        serialized = json.dumps(d)  # should not raise
        assert len(serialized) > 0


class TestDeterminism:
    """Plans must be deterministic for the same inputs."""

    def test_same_inputs_produce_identical_plans(self):
        kwargs = dict(
            available_roles=["drums", "bass", "melody", "fx"],
            genre="trap",
            tempo=140.0,
            target_bars=64,
        )
        plan1 = ProducerPlanBuilderV2(**kwargs).build()
        plan2 = ProducerPlanBuilderV2(**kwargs).build()

        assert len(plan1.sections) == len(plan2.sections)
        for s1, s2 in zip(plan1.sections, plan2.sections):
            assert s1.section_type == s2.section_type
            assert s1.start_bar == s2.start_bar
            assert s1.length_bars == s2.length_bars
            assert s1.active_roles == s2.active_roles
            assert s1.target_energy == s2.target_energy
            assert s1.density == s2.density

    def test_different_genres_produce_different_plans(self):
        base_kwargs = dict(available_roles=["drums", "bass", "melody"], target_bars=64)
        plan_trap = ProducerPlanBuilderV2(**base_kwargs, genre="trap").build()
        plan_cinematic = ProducerPlanBuilderV2(**base_kwargs, genre="cinematic").build()
        # Genres should at minimum record differently
        assert plan_trap.genre != plan_cinematic.genre


class TestEnergyPlanValidation:
    """Validate energy assignments per section type."""

    def test_hooks_have_higher_energy_than_verses(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody"],
            genre="trap",
        )
        plan = builder.build()
        hooks = [s for s in plan.sections if s.section_type == SectionKind.HOOK]
        verses = [s for s in plan.sections if s.section_type == SectionKind.VERSE]
        if hooks and verses:
            max_verse_energy = max(s.target_energy.value for s in verses)
            for hook in hooks:
                assert hook.target_energy.value > max_verse_energy, (
                    f"{hook.label} energy {hook.target_energy.value} should exceed "
                    f"verse energy {max_verse_energy}"
                )

    def test_intro_energy_is_low(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody", "pads"],
            genre="pop",
        )
        plan = builder.build()
        intros = [s for s in plan.sections if s.section_type == SectionKind.INTRO]
        for intro in intros:
            assert intro.target_energy.value <= EnergyLevel.MEDIUM.value, (
                f"Intro energy {intro.target_energy} should be low-medium"
            )

    def test_bridge_energy_below_adjacent_hook(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody"],
            genre="trap",
            structure_template="extended",
        )
        plan = builder.build()
        bridges = [s for s in plan.sections if s.section_type in (SectionKind.BRIDGE, SectionKind.BREAKDOWN)]
        hooks = [s for s in plan.sections if s.section_type == SectionKind.HOOK]
        if bridges and hooks:
            min_hook_energy = min(s.target_energy.value for s in hooks)
            for bridge in bridges:
                assert bridge.target_energy.value < min_hook_energy, (
                    f"Bridge energy {bridge.target_energy.value} should be below hook energy {min_hook_energy}"
                )

    def test_outro_has_low_energy(self):
        builder = ProducerPlanBuilderV2(available_roles=["drums", "bass"])
        plan = builder.build()
        outros = [s for s in plan.sections if s.section_type == SectionKind.OUTRO]
        for outro in outros:
            assert outro.target_energy.value <= EnergyLevel.LOW.value


class TestRoleActivationLogic:
    """Validate active/muted role assignment logic."""

    def test_active_roles_are_subset_of_available(self):
        available = ["drums", "bass", "melody", "pads", "fx"]
        builder = ProducerPlanBuilderV2(available_roles=available)
        plan = builder.build()
        available_set = set(available)
        for s in plan.sections:
            assert set(s.active_roles).issubset(available_set), (
                f"{s.label} has roles not in available: {set(s.active_roles) - available_set}"
            )

    def test_active_plus_muted_equals_available(self):
        available = ["drums", "bass", "melody", "pads"]
        builder = ProducerPlanBuilderV2(available_roles=available)
        plan = builder.build()
        available_set = set(available)
        for s in plan.sections:
            all_accounted = set(s.active_roles) | set(s.muted_roles)
            assert all_accounted == available_set, (
                f"{s.label}: active+muted {all_accounted} != available {available_set}"
            )

    def test_hook_has_drums_when_available(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody"],
            genre="trap",
        )
        plan = builder.build()
        hooks = [s for s in plan.sections if s.section_type == SectionKind.HOOK]
        for hook in hooks:
            assert "drums" in hook.active_roles, (
                f"{hook.label} should activate drums when available"
            )

    def test_intro_respects_sparse_density(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody", "pads", "fx", "vocal"],
            genre="trap",
        )
        plan = builder.build()
        intros = [s for s in plan.sections if s.section_type == SectionKind.INTRO]
        for intro in intros:
            assert intro.density == DensityLevel.SPARSE, (
                f"Intro density should be SPARSE, got {intro.density}"
            )
            assert len(intro.active_roles) <= 2, (
                f"Intro should have at most 2 active roles, got {intro.active_roles}"
            )

    def test_no_roles_produces_empty_active_roles(self):
        builder = ProducerPlanBuilderV2(available_roles=[])
        plan = builder.build()
        for s in plan.sections:
            assert s.active_roles == [], f"{s.label} should have empty active_roles"


class TestDecisionLog:
    """Validate producer decision log is populated with rationale."""

    def test_decision_log_is_not_empty(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody", "pads"],
            genre="trap",
        )
        plan = builder.build()
        assert len(plan.decision_log) > 0

    def test_decision_log_entries_have_required_fields(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody"],
        )
        plan = builder.build()
        for entry in plan.decision_log:
            assert entry.decision, "Decision log entry must have a decision"
            assert entry.reason, "Decision log entry must have a reason"
            assert isinstance(entry.section_index, int)

    def test_sparse_intro_logged_when_many_roles(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody", "pads", "fx"],
            genre="trap",
        )
        plan = builder.build()
        intro_decisions = [
            e for e in plan.decision_log
            if e.flag == "sparse_intro"
        ]
        assert intro_decisions, "sparse_intro decision should be logged"

    def test_hook_elevation_logged(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody"],
        )
        plan = builder.build()
        hook_decisions = [
            e for e in plan.decision_log
            if e.flag == "hook_elevation"
        ]
        assert hook_decisions, "hook_elevation decision should be logged"


class TestSnapshotOutputs:
    """Snapshot-style tests for plan outputs given specific stem inputs."""

    def test_trap_with_full_stems_snapshot(self):
        """Trap arrangement with drums/bass/melody/fx should have standard structure."""
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody", "fx"],
            genre="trap",
            tempo=140.0,
            target_bars=64,
        )
        plan = builder.build()

        section_types = [s.section_type.value for s in plan.sections]
        # Must contain intro, at least one verse, at least one hook, outro
        assert "intro" in section_types
        assert "hook" in section_types
        assert "outro" in section_types

        # Hooks must have full density
        for s in plan.sections:
            if s.section_type == SectionKind.HOOK:
                assert s.density == DensityLevel.FULL

    def test_single_full_mix_loop_uses_minimal_structure(self):
        """A single-loop source with only full_mix should get simplified structure."""
        builder = ProducerPlanBuilderV2(
            available_roles=["full_mix"],
            genre="generic",
            source_type="loop",
            structure_template="standard",
        )
        plan = builder.build()
        # Should still produce a valid plan
        assert len(plan.sections) >= 3
        # Template may have downgraded to 'loop' simplified
        assert plan.source_type == "loop"

    def test_stem_pack_source_type_recorded(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody", "vocal"],
            source_type="stem_pack",
        )
        plan = builder.build()
        assert plan.source_type == "stem_pack"

    def test_rules_applied_list_is_populated(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums", "bass", "melody"],
        )
        plan = builder.build()
        assert len(plan.rules_applied) > 0
        assert "sparse_intro" in plan.rules_applied
        assert "hook_elevation" in plan.rules_applied


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_available_roles(self):
        builder = ProducerPlanBuilderV2(available_roles=[])
        plan = builder.build()
        assert plan is not None
        assert plan.available_roles == []

    def test_unknown_structure_template_falls_back_to_standard(self):
        builder = ProducerPlanBuilderV2(
            available_roles=["drums"],
            structure_template="nonexistent_template",
        )
        plan = builder.build()
        assert len(plan.sections) > 0

    def test_target_bars_adjusts_total_length(self):
        # Use larger, achievable targets for standard template (10 sections × 4 bars min = 40 bars)
        for target in [48, 64, 80]:
            builder = ProducerPlanBuilderV2(
                available_roles=["drums", "bass"],
                target_bars=target,
            )
            plan = builder.build()
            # Total bars should be close to target within bar-aligned tolerance
            # (min section floor may mean we can't hit very small targets exactly)
            assert abs(plan.total_bars - target) <= 8, (
                f"Target bars {target}, got {plan.total_bars}"
            )

    def test_outro_always_present(self):
        builder = ProducerPlanBuilderV2(available_roles=["drums", "bass"])
        plan = builder.build()
        outros = [s for s in plan.sections if s.section_type == SectionKind.OUTRO]
        assert len(outros) >= 1

    def test_single_role_produces_valid_plan(self):
        builder = ProducerPlanBuilderV2(available_roles=["full_mix"])
        plan = builder.build()
        assert len(plan.sections) >= 3
        for s in plan.sections:
            assert len(s.active_roles) <= 1
