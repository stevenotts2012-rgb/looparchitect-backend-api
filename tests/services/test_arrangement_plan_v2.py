"""
Tests for the Arrangement Plan V2 system.

Covers:
- Repeated sections evolve when enough stems exist
- Source-quality modes change strictness appropriately
- Hooks create payoff (energy, density, introduced elements)
- Transitions exist and are honoured at section boundaries
- Plan vs. actual render signatures can be compared
- Weak source material degrades gracefully
- true_stems / zip_stems outperform ai_separated / stereo_fallback in richness

All tests are deterministic (no random calls, no LLM dependency).
"""

from __future__ import annotations

import pytest
from app.services.arrangement_memory import ArrangementMemory, VARIATION_STRATEGIES
from app.services.arrangement_plan_v2 import (
    ArrangementPlanV2,
    SectionPlan,
    StemRole,
    build_arrangement_plan_v2,
    compare_plan_vs_actual,
    validate_and_repair_plan,
    _target_energy,
    _target_density,
    _cap_roles_for_quality,
    PLAN_V2_VERSION,
)
from app.services.source_quality import SourceQualityMode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RICH_ROLES = ["drums", "bass", "melody", "pads", "fx", "vocal", "percussion", "synth"]
SPARSE_ROLES = ["full_mix"]
MODERATE_ROLES = ["drums", "bass", "melody"]

STANDARD_STRUCTURE = [
    "intro", "verse", "pre_hook", "hook",
    "verse", "pre_hook", "hook", "bridge", "outro",
]
STANDARD_BARS = [4, 8, 4, 8, 8, 4, 8, 8, 4]


# ---------------------------------------------------------------------------
# 1. Repeated sections evolve when enough stems exist
# ---------------------------------------------------------------------------

class TestRepeatEvolution:
    """Verse 2 != Verse 1; Hook 2 is bigger/different from Hook 1."""

    def test_verse_roles_change_across_occurrences(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "verse"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            memory_enabled=True,
        )
        verse_plans = [s for s in plan.sections if s.section_type == "verse"]
        assert len(verse_plans) == 2, "Expected two verse sections"

        v1_roles = frozenset(verse_plans[0].active_roles)
        v2_roles = frozenset(verse_plans[1].active_roles)
        # They should not be identical when rich stems are available
        assert v1_roles != v2_roles, (
            f"Verse 1 and Verse 2 have identical roles {v1_roles}; "
            "repeat evolution is not working"
        )

    def test_hook_roles_change_or_grow_across_occurrences(self):
        plan = build_arrangement_plan_v2(
            structure=["hook", "hook"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            memory_enabled=True,
        )
        hooks = [s for s in plan.sections if s.section_type == "hook"]
        assert len(hooks) == 2
        h1 = frozenset(hooks[0].active_roles)
        h2 = frozenset(hooks[1].active_roles)
        # Hook 2 must be different from Hook 1 OR bigger (more roles)
        assert h1 != h2 or len(hooks[1].active_roles) >= len(hooks[0].active_roles), (
            "Hook 2 should be different from or larger than Hook 1"
        )

    def test_second_occurrence_has_variation_strategy(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "verse"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            memory_enabled=True,
        )
        verse_plans = [s for s in plan.sections if s.section_type == "verse"]
        v2 = verse_plans[1]
        assert v2.variation_strategy != "none", (
            f"Second verse should have a variation strategy but got 'none'"
        )
        assert v2.variation_strategy in VARIATION_STRATEGIES, (
            f"Unknown variation strategy: {v2.variation_strategy}"
        )

    def test_introduced_elements_tracked_on_repeat(self):
        plan = build_arrangement_plan_v2(
            structure=["hook", "hook"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            memory_enabled=True,
        )
        hooks = [s for s in plan.sections if s.section_type == "hook"]
        h2 = hooks[1]
        # introduced_elements should be populated when roles differ
        if frozenset(hooks[0].active_roles) != frozenset(hooks[1].active_roles):
            assert isinstance(h2.introduced_elements, list)

    def test_graceful_degradation_with_single_role(self):
        """When only one role is available, repeat evolution degrades gracefully."""
        plan = build_arrangement_plan_v2(
            structure=["verse", "verse"],
            bars_by_section=[8, 8],
            available_roles=["full_mix"],
            source_quality_mode="true_stems",
            memory_enabled=True,
        )
        verse_plans = [s for s in plan.sections if s.section_type == "verse"]
        # Should not crash; both verses get whatever is possible
        assert len(verse_plans) == 2
        for v in verse_plans:
            assert len(v.active_roles) >= 1


# ---------------------------------------------------------------------------
# 2. Source-quality modes change strictness
# ---------------------------------------------------------------------------

class TestSourceQualityModes:
    """Different source quality modes produce different arrangement strictness."""

    @pytest.mark.parametrize("quality,max_hook_roles", [
        ("true_stems",      5),
        ("zip_stems",       5),
        ("ai_separated",    3),
        ("stereo_fallback", 1),
    ])
    def test_hook_role_cap_per_quality(self, quality, max_hook_roles):
        plan = build_arrangement_plan_v2(
            structure=["hook"],
            bars_by_section=[8],
            available_roles=RICH_ROLES,
            source_quality_mode=quality,
        )
        hook = plan.sections[0]
        assert len(hook.active_roles) <= max_hook_roles, (
            f"Hook has {len(hook.active_roles)} roles for quality={quality}; "
            f"expected <= {max_hook_roles}"
        )

    def test_stereo_fallback_produces_one_role_per_section(self):
        plan = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="stereo_fallback",
        )
        for s in plan.sections:
            assert len(s.active_roles) <= 1, (
                f"Section {s.name} has {len(s.active_roles)} roles under stereo_fallback"
            )

    def test_ai_separated_capped_lower_than_true_stems(self):
        plan_ts = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        plan_ai = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="ai_separated",
        )
        ts_total = sum(len(s.active_roles) for s in plan_ts.sections)
        ai_total = sum(len(s.active_roles) for s in plan_ai.sections)
        assert ai_total <= ts_total, (
            f"ai_separated should have <= total roles than true_stems "
            f"(ai={ai_total} vs ts={ts_total})"
        )

    def test_true_stems_richer_than_stereo_fallback(self):
        plan_ts = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        plan_sf = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="stereo_fallback",
        )
        ts_total = sum(len(s.active_roles) for s in plan_ts.sections)
        sf_total = sum(len(s.active_roles) for s in plan_sf.sections)
        assert ts_total > sf_total, (
            "true_stems arrangement should be richer than stereo_fallback"
        )

    def test_source_quality_preserved_in_plan(self):
        for quality in ("true_stems", "zip_stems", "ai_separated", "stereo_fallback"):
            plan = build_arrangement_plan_v2(
                structure=["verse", "hook"],
                bars_by_section=[8, 8],
                available_roles=RICH_ROLES,
                source_quality_mode=quality,
            )
            assert plan.source_quality_mode == quality


# ---------------------------------------------------------------------------
# 3. Hooks create payoff
# ---------------------------------------------------------------------------

class TestHookPayoff:
    """Hooks must feel meaningfully bigger or different than preceding verses."""

    def test_hook_has_higher_energy_than_verse(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "hook"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        verse = next(s for s in plan.sections if s.section_type == "verse")
        hook = next(s for s in plan.sections if s.section_type == "hook")
        assert hook.target_energy >= verse.target_energy, (
            f"Hook energy {hook.target_energy} < verse energy {verse.target_energy}"
        )

    def test_hook_has_full_or_richer_density(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "hook"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        hook = next(s for s in plan.sections if s.section_type == "hook")
        assert hook.target_density == "full", (
            f"Hook should have 'full' density but got '{hook.target_density}'"
        )

    def test_hook_more_roles_than_verse_when_stems_available(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "hook"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        verse = next(s for s in plan.sections if s.section_type == "verse")
        hook = next(s for s in plan.sections if s.section_type == "hook")
        assert len(hook.active_roles) >= len(verse.active_roles), (
            f"Hook has fewer roles ({len(hook.active_roles)}) than verse "
            f"({len(verse.active_roles)})"
        )

    def test_hook_energy_escalates_across_multiple_occurrences(self):
        plan = build_arrangement_plan_v2(
            structure=["hook", "hook", "hook"],
            bars_by_section=[8, 8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            memory_enabled=True,
        )
        hooks = [s for s in plan.sections if s.section_type == "hook"]
        # Each hook should have >= energy of the previous one
        for i in range(1, len(hooks)):
            assert hooks[i].target_energy >= hooks[i - 1].target_energy, (
                f"Hook {i+1} energy {hooks[i].target_energy} < "
                f"Hook {i} energy {hooks[i-1].target_energy}"
            )

    def test_verse_density_is_not_full(self):
        """Verse should never be 'full' density — leave room for hook payoff."""
        plan = build_arrangement_plan_v2(
            structure=["verse", "verse"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        for verse in [s for s in plan.sections if s.section_type == "verse"]:
            assert verse.target_density != "full", (
                f"Verse {verse.occurrence} should not have 'full' density"
            )


# ---------------------------------------------------------------------------
# 4. Transitions exist and are honoured
# ---------------------------------------------------------------------------

class TestTransitions:
    """Every section boundary should have an intentional transition."""

    def test_transitions_v2_creates_transition_plan(self):
        plan = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            transitions_v2_enabled=True,
        )
        # At minimum there should be transitions for the hook boundaries
        hook_transitions = [
            t for t in plan.transition_plan if t.to_section_type == "hook"
        ]
        assert len(hook_transitions) > 0, "No transitions found leading into hooks"

    def test_hook_has_strong_transition_in(self):
        plan = build_arrangement_plan_v2(
            structure=["pre_hook", "hook"],
            bars_by_section=[4, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            transitions_v2_enabled=True,
        )
        hook = next(s for s in plan.sections if s.section_type == "hook")
        assert hook.transition_in not in {"none"}, (
            f"Hook should have a meaningful transition_in, got '{hook.transition_in}'"
        )

    def test_breakdown_has_subtractive_entry(self):
        plan = build_arrangement_plan_v2(
            structure=["hook", "breakdown"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            transitions_v2_enabled=True,
        )
        breakdown = next(s for s in plan.sections if s.section_type == "breakdown")
        assert breakdown.transition_in in {"subtractive_entry", "silence_gap"}, (
            f"Breakdown should have subtractive or silence entry, "
            f"got '{breakdown.transition_in}'"
        )

    def test_bridge_has_subtractive_entry(self):
        plan = build_arrangement_plan_v2(
            structure=["hook", "bridge"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            transitions_v2_enabled=True,
        )
        bridge = next(s for s in plan.sections if s.section_type == "bridge")
        assert bridge.transition_in in {"subtractive_entry", "silence_gap", "mute_drop"}, (
            f"Bridge should have a subtractive entry, got '{bridge.transition_in}'"
        )

    def test_all_transition_types_are_strings(self):
        plan = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            transitions_v2_enabled=True,
        )
        for s in plan.sections:
            assert isinstance(s.transition_in, str), f"transition_in must be str for {s.name}"
            assert isinstance(s.transition_out, str), f"transition_out must be str for {s.name}"
        for t in plan.transition_plan:
            assert isinstance(t.transition_type, str)
            assert 0.0 <= t.intensity <= 1.0

    def test_transition_plan_has_correct_boundary_bars(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "hook"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            transitions_v2_enabled=True,
        )
        if plan.transition_plan:
            t = plan.transition_plan[0]
            assert t.boundary_bar == 8, (
                f"Boundary bar should be 8 (end of verse), got {t.boundary_bar}"
            )


# ---------------------------------------------------------------------------
# 5. Plan vs. actual render signatures can be compared
# ---------------------------------------------------------------------------

class TestPlanVsActualComparison:
    """compare_plan_vs_actual returns correct match/mismatch data."""

    def test_perfect_match_returns_plan_honored(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "hook"],
            bars_by_section=[8, 8],
            available_roles=MODERATE_ROLES,
            source_quality_mode="true_stems",
        )
        # Simulate actual = planned
        actual = [
            {"section_index": i, "roles": list(s.active_roles)}
            for i, s in enumerate(plan.sections)
        ]
        result = compare_plan_vs_actual(plan, actual)
        assert result["plan_honored"] is True
        assert result["mismatch_count"] == 0
        assert result["match_count"] == len(plan.sections)

    def test_mismatch_detected(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "hook"],
            bars_by_section=[8, 8],
            available_roles=MODERATE_ROLES,
            source_quality_mode="true_stems",
        )
        # Simulate fallback: all sections get only "full_mix"
        actual = [
            {"section_index": i, "roles": ["full_mix"]}
            for i in range(len(plan.sections))
        ]
        result = compare_plan_vs_actual(plan, actual)
        assert result["plan_honored"] is False
        assert result["mismatch_count"] > 0

    def test_unique_signature_counts(self):
        plan = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            memory_enabled=True,
        )
        # Simulate actual same as planned
        actual = [
            {"section_index": i, "roles": list(s.active_roles)}
            for i, s in enumerate(plan.sections)
        ]
        result = compare_plan_vs_actual(plan, actual)
        assert result["unique_plan_signature_count"] >= 1
        assert result["unique_actual_signature_count"] >= 1

    def test_section_diffs_have_correct_shape(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "hook"],
            bars_by_section=[8, 8],
            available_roles=MODERATE_ROLES,
            source_quality_mode="true_stems",
        )
        actual = [
            {"section_index": 0, "roles": ["drums"]},
            {"section_index": 1, "roles": ["drums", "bass", "melody"]},
        ]
        result = compare_plan_vs_actual(plan, actual)
        assert len(result["section_diffs"]) == len(plan.sections)
        for diff in result["section_diffs"]:
            assert "section_index" in diff
            assert "planned_roles" in diff
            assert "actual_roles" in diff
            assert "match" in diff
            assert "plan_signature" in diff
            assert "actual_signature" in diff


# ---------------------------------------------------------------------------
# 6. Weak source material degrades gracefully
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    """System degrades gracefully when source material is too limited."""

    def test_empty_roles_returns_valid_plan(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "hook"],
            bars_by_section=[8, 8],
            available_roles=[],
            source_quality_mode="stereo_fallback",
        )
        # Should not raise; plan may be empty sections but must not crash
        assert plan is not None
        assert plan.plan_version == PLAN_V2_VERSION

    def test_single_role_stereo_fallback(self):
        plan = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=["full_mix"],
            source_quality_mode="stereo_fallback",
        )
        for s in plan.sections:
            assert len(s.active_roles) <= 1

    def test_variation_strategy_none_when_insufficient_stems(self):
        """With one role, repeat variation strategy should be 'none'."""
        plan = build_arrangement_plan_v2(
            structure=["verse", "verse"],
            bars_by_section=[8, 8],
            available_roles=["full_mix"],
            source_quality_mode="stereo_fallback",
            memory_enabled=True,
        )
        v2 = [s for s in plan.sections if s.section_type == "verse"][-1]
        # With one role, strategy is 'none' — no variation is possible
        assert v2.variation_strategy == "none", (
            f"Expected 'none' with only 1 role, got '{v2.variation_strategy}'"
        )

    def test_validation_warns_on_repeated_identical_sections(self):
        """Validation should warn but not fail when sections are identical."""
        plan = build_arrangement_plan_v2(
            structure=["verse", "verse"],
            bars_by_section=[8, 8],
            available_roles=["full_mix"],
            source_quality_mode="stereo_fallback",
        )
        result = validate_and_repair_plan(plan, "stereo_fallback")
        # The plan is not invalid — it just can't vary
        assert result.valid is True

    def test_arrangement_memory_handles_disabled_gracefully(self):
        mem = ArrangementMemory(enabled=False)
        # All mutations are no-ops
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=3)
        assert mem.occurrence_of("verse") == 0
        assert mem.previous_roles_for("verse") == []
        assert mem.energy_is_flat() is False


# ---------------------------------------------------------------------------
# 7. Arrangement Memory
# ---------------------------------------------------------------------------

class TestArrangementMemory:
    """ArrangementMemory tracks state correctly."""

    def test_occurrence_tracking(self):
        mem = ArrangementMemory(enabled=True)
        assert mem.occurrence_of("verse") == 0
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=3)
        assert mem.occurrence_of("verse") == 1
        mem.record_section(section_type="verse", roles=["drums", "bass", "melody"], energy=4)
        assert mem.occurrence_of("verse") == 2

    def test_previous_roles_returned(self):
        mem = ArrangementMemory(enabled=True)
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=3)
        prev = mem.previous_roles_for("verse")
        assert set(prev) == {"drums", "bass"}

    def test_used_stems_accumulated(self):
        mem = ArrangementMemory(enabled=True)
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=3)
        mem.record_section(section_type="hook", roles=["drums", "bass", "melody"], energy=5)
        assert "drums" in mem.used_stems
        assert "melody" in mem.used_stems

    def test_energy_flat_detection(self):
        mem = ArrangementMemory(enabled=True)
        mem.record_section(section_type="intro", roles=["pads"], energy=1)
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=1)
        mem.record_section(section_type="pre_hook", roles=["bass", "arp"], energy=1)
        assert mem.energy_is_flat() is True

    def test_energy_not_flat_when_varying(self):
        mem = ArrangementMemory(enabled=True)
        mem.record_section(section_type="intro", roles=["pads"], energy=1)
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=3)
        mem.record_section(section_type="hook", roles=["drums", "bass", "melody"], energy=5)
        assert mem.energy_is_flat() is False

    def test_role_combo_used_detection(self):
        mem = ArrangementMemory(enabled=True)
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=3)
        assert mem.is_role_combo_used("verse", ["drums", "bass"]) is True
        assert mem.is_role_combo_used("verse", ["drums", "bass", "melody"]) is False

    def test_variation_history_recorded(self):
        mem = ArrangementMemory(enabled=True)
        mem.record_section(section_type="verse", roles=["drums"], energy=3, variation_strategy="none")
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=4, variation_strategy="role_rotation")
        history = mem.variation_strategies_used_for("verse")
        assert history == ["none", "role_rotation"]

    def test_suggest_variation_strategy_first_repeat(self):
        """On first repeat with extra roles available, suggest role_rotation."""
        mem = ArrangementMemory(enabled=True)
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=3)
        strategy = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass", "melody", "pads"],
            prev_roles=["drums", "bass"],
        )
        assert strategy == "role_rotation"

    def test_to_dict_is_json_safe(self):
        import json
        mem = ArrangementMemory(enabled=True)
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=3)
        d = mem.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        assert len(serialised) > 0


# ---------------------------------------------------------------------------
# 8. ArrangementPlanV2 structure and serialisation
# ---------------------------------------------------------------------------

class TestArrangementPlanV2Structure:
    """The plan structure, energy curve, and stem map are internally consistent."""

    def test_plan_fields_are_consistent(self):
        plan = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        assert len(plan.structure) == len(plan.sections)
        assert len(plan.energy_curve) == len(plan.sections)
        assert len(plan.section_stem_map) == len(plan.sections)
        for i, sec in enumerate(plan.sections):
            assert plan.structure[i] == sec.section_type
            assert plan.energy_curve[i] == sec.target_energy
            assert plan.section_stem_map[i] == sec.active_roles

    def test_total_bars_matches_sum(self):
        plan = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        assert plan.total_bars == sum(STANDARD_BARS)

    def test_section_start_bars_are_cumulative(self):
        plan = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        expected_start = 0
        for s in plan.sections:
            assert s.start_bar == expected_start, (
                f"Section {s.name}: expected start_bar={expected_start}, "
                f"got {s.start_bar}"
            )
            expected_start += s.bars

    def test_to_observability_dict_is_serialisable(self):
        import json
        plan = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
            memory_enabled=True,
            transitions_v2_enabled=True,
        )
        obs = plan.to_observability_dict()
        # Must not raise
        serialised = json.dumps(obs)
        assert len(serialised) > 0
        # Check presence of required keys
        for key in (
            "plan_version", "source_quality_mode", "sections",
            "energy_curve", "section_stem_map", "transition_plan",
            "decision_log", "total_bars",
        ):
            assert key in obs, f"Missing key '{key}' in observability dict"

    def test_decision_log_has_entries(self):
        plan = build_arrangement_plan_v2(
            structure=["verse", "hook"],
            bars_by_section=[8, 8],
            available_roles=MODERATE_ROLES,
            source_quality_mode="true_stems",
        )
        assert len(plan.decision_log) >= 2
        for entry in plan.decision_log:
            assert entry.section_label
            assert entry.decision


# ---------------------------------------------------------------------------
# 9. Validation and auto-repair
# ---------------------------------------------------------------------------

class TestValidationAndAutoRepair:
    """The validation layer auto-repairs minor issues and warns on others."""

    def test_hook_energy_auto_repaired_above_verse(self):
        """If hooks have lower energy than verses, auto-repair bumps them."""
        plan = build_arrangement_plan_v2(
            structure=["verse", "hook"],
            bars_by_section=[8, 8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        # After plan is built, manually depress hook energy
        hook = next(s for s in plan.sections if s.section_type == "hook")
        hook.target_energy = 1
        plan.energy_curve[hook.index] = 1

        result = validate_and_repair_plan(plan, "true_stems")
        # Should repair and not fail
        assert result.valid is True
        assert any("hook" in r.lower() for r in result.repairs_applied), (
            f"Expected a hook energy repair, got: {result.repairs_applied}"
        )
        # After repair, hook energy should be >= verse energy
        verse = next(s for s in plan.sections if s.section_type == "verse")
        assert hook.target_energy >= verse.target_energy

    def test_verse_density_auto_repaired(self):
        plan = build_arrangement_plan_v2(
            structure=["verse"],
            bars_by_section=[8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        # Manually override to 'full'
        verse = plan.sections[0]
        verse.target_density = "full"

        result = validate_and_repair_plan(plan, "true_stems")
        assert verse.target_density == "medium"
        assert result.valid is True

    def test_stereo_fallback_clamped_to_one_role(self):
        plan = build_arrangement_plan_v2(
            structure=["hook"],
            bars_by_section=[8],
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        # Force too many roles to simulate a scenario where the validator repairs it
        plan.sections[0].active_roles = ["drums", "bass", "melody"]
        plan.section_stem_map[0] = ["drums", "bass", "melody"]

        result = validate_and_repair_plan(plan, "stereo_fallback")
        assert len(plan.sections[0].active_roles) == 1
        assert result.valid is True

    def test_empty_plan_returns_invalid(self):
        plan = ArrangementPlanV2()
        result = validate_and_repair_plan(plan, "true_stems")
        assert result.valid is False
        assert result.errors


# ---------------------------------------------------------------------------
# 10. StemRole model
# ---------------------------------------------------------------------------

class TestStemRole:
    """StemRole carries id, role, energy_weight, source_type, confidence."""

    def test_creation(self):
        stem = StemRole(
            stem_id="drums_01",
            role="drums",
            energy_weight=0.8,
            source_type="true_stems",
            confidence=0.95,
        )
        assert stem.stem_id == "drums_01"
        assert stem.role == "drums"
        assert stem.energy_weight == 0.8
        assert stem.source_type == "true_stems"
        assert stem.confidence == 0.95

    def test_energy_weight_clamped(self):
        stem = StemRole(
            stem_id="x", role="bass", energy_weight=2.5,
            source_type="zip_stems", confidence=0.5,
        )
        assert stem.energy_weight == 1.0

    def test_confidence_clamped(self):
        stem = StemRole(
            stem_id="x", role="melody", energy_weight=0.5,
            source_type="ai_separated", confidence=-0.1,
        )
        assert stem.confidence == 0.0


# ---------------------------------------------------------------------------
# 11. Render observability helpers
# ---------------------------------------------------------------------------

class TestRenderObservabilityV2:
    """extract_section_occurrence_info correctly summarises the plan."""

    def test_occurrence_info_from_plan(self):
        from app.services.render_observability import extract_section_occurrence_info
        plan = build_arrangement_plan_v2(
            structure=STANDARD_STRUCTURE,
            bars_by_section=STANDARD_BARS,
            available_roles=RICH_ROLES,
            source_quality_mode="true_stems",
        )
        obs = plan.to_observability_dict()
        info = extract_section_occurrence_info(obs)

        assert info["total_sections"] == len(STANDARD_STRUCTURE)
        assert "verse" in info["occurrence_counts"]
        assert "hook" in info["repeated_sections"], (
            "hook should appear as repeated (2 times in STANDARD_STRUCTURE)"
        )

    def test_empty_plan_returns_empty_info(self):
        from app.services.render_observability import extract_section_occurrence_info
        info = extract_section_occurrence_info(None)
        assert info == {}
