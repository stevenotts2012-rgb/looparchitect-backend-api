"""
Tests for Arranger V2 — the deterministic, stateful arrangement engine.

Tests verify:
1. Hook sections have the highest density and energy.
2. Verse 2 differs from Verse 1 (role-level variation).
3. Every non-first section has a transition_in defined.
4. No two occurrences of the same section type produce identical stem maps
   (when enough stems are available).
5. Validator raises on flat energy / missing hook transitions.
6. Role engine rejects stems without valid roles.
"""

from __future__ import annotations

import pytest

from app.services.arranger_v2 import (
    ArrangementPlan,
    ArrangementValidationError,
    ArrangerState,
    RoleValidationError,
    SectionPlan,
    build_arrangement_plan,
    build_transition_plan,
    get_valid_role_strings,
    normalise_role,
    select_stems_for_section,
    validate_or_raise,
    validate_plan,
    validate_stem_roles,
)
from app.services.arranger_v2.planner import _compute_energy


# ---------------------------------------------------------------------------
# Test fixtures / constants
# ---------------------------------------------------------------------------

RICH_ROLES = ["drums", "bass", "melody", "pads", "fx", "vocal", "percussion", "synth"]
MINIMAL_ROLES = ["drums", "bass"]
FULL_MIX_ONLY = ["full_mix"]

STANDARD_STRUCTURE = [
    "intro", "verse", "pre_hook", "hook",
    "verse", "pre_hook", "hook", "outro",
]


# ===========================================================================
# 1. Hook has highest density
# ===========================================================================

class TestHookHasHighestDensity:
    """Hook sections must have higher density than all other section types."""

    def test_hook_density_exceeds_verse(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        hooks = [s for s in plan.sections if s.section_type == "hook"]
        verses = [s for s in plan.sections if s.section_type == "verse"]
        assert hooks, "Plan must contain at least one hook section"
        assert verses, "Plan must contain at least one verse section"

        min_hook_density = min(s.target_density for s in hooks)
        max_verse_density = max(s.target_density for s in verses)
        assert min_hook_density > max_verse_density, (
            f"Hook density {min_hook_density:.2f} must exceed verse "
            f"density {max_verse_density:.2f}"
        )

    def test_hook_energy_is_maximum(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        hooks = [s for s in plan.sections if s.section_type == "hook"]
        max_energy = max(s.target_energy for s in plan.sections)
        max_hook_energy = max(s.target_energy for s in hooks)
        assert max_hook_energy == max_energy, (
            f"Max hook energy {max_hook_energy} must equal arrangement max {max_energy}. "
            "At least one hook must reach peak energy."
        )

    def test_hook_role_count_exceeds_verse(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        hooks = [s for s in plan.sections if s.section_type == "hook"]
        verses = [s for s in plan.sections if s.section_type == "verse"]
        min_hook_roles = min(len(s.active_roles) for s in hooks)
        max_verse_roles = max(len(s.active_roles) for s in verses)
        assert min_hook_roles >= max_verse_roles, (
            f"Hook should have at least as many roles as verse "
            f"(hook={min_hook_roles}, verse={max_verse_roles})"
        )


# ===========================================================================
# 2. Verse 2 differs from Verse 1
# ===========================================================================

class TestVerse2DiffersFromVerse1:
    """Second occurrence of verse must differ by at least one role."""

    def test_verse_roles_differ_across_occurrences(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        verses = [s for s in plan.sections if s.section_type == "verse"]
        assert len(verses) >= 2, "Plan must contain at least two verse sections"

        v1_roles = frozenset(verses[0].active_roles)
        v2_roles = frozenset(verses[1].active_roles)
        assert v1_roles != v2_roles, (
            f"Verse 1 and Verse 2 have identical roles {sorted(v1_roles)}. "
            "Repeat evolution is not working."
        )

    def test_verse_2_has_variation_strategy(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        verses = [s for s in plan.sections if s.section_type == "verse"]
        if len(verses) >= 2:
            verse_2 = verses[1]
            assert verse_2.variation_strategy != "none", (
                f"Verse 2 has variation_strategy='none' — should have an explicit strategy"
            )

    def test_hook_2_has_layer_extra_or_rotation(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        hooks = [s for s in plan.sections if s.section_type == "hook"]
        if len(hooks) >= 2:
            hook_2 = hooks[1]
            escalating_strategies = {"layer_extra", "role_rotation", "support_swap", "add_percussion"}
            assert hook_2.variation_strategy in escalating_strategies or len(hook_2.active_roles) >= len(hooks[0].active_roles), (
                f"Hook 2 strategy={hook_2.variation_strategy} does not indicate escalation"
            )


# ===========================================================================
# 3. Transitions exist for all non-first sections
# ===========================================================================

class TestTransitionsExist:
    """Every section except the first must have a transition_in."""

    def test_all_non_first_sections_have_transition(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        for i, section in enumerate(plan.sections):
            if i == 0:
                continue
            assert section.transition_in and section.transition_in != "none", (
                f"Section {i} ({section.name}) has no transition_in"
            )

    def test_hooks_have_riser_transition(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        riser_types = {"riser", "silence_gap", "fx_rise", "reverse_fx"}
        for i, section in enumerate(plan.sections):
            if section.section_type == "hook" and i > 0:
                assert section.transition_in in riser_types, (
                    f"{section.name} has transition_in={section.transition_in!r}, "
                    f"expected a riser type from {riser_types}"
                )

    def test_transition_plan_has_all_boundaries(self):
        section_types = ["intro", "verse", "hook", "verse", "hook", "outro"]
        energy_curve = [1, 3, 5, 4, 5, 1]
        transitions = build_transition_plan(section_types, energy_curve)
        # All except the first section should have an entry in the plan.
        assert len(transitions) == len(section_types)
        # Hooks must have riser or silence_gap.
        riser_types = {"riser", "silence_gap", "reverse_fx"}
        for t in transitions:
            if t["to_type"] == "hook" and t["from_type"]:
                assert t["transition_in"] in riser_types, (
                    f"Hook transition_in={t['transition_in']!r} is not a riser type"
                )


# ===========================================================================
# 4. No duplicate stem maps
# ===========================================================================

class TestNoDuplicateStemMaps:
    """Same section type should not produce identical role sets (with rich stems)."""

    def test_no_identical_verse_stem_maps(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        verses = [s for s in plan.sections if s.section_type == "verse"]
        if len(verses) >= 2:
            combos = [frozenset(v.active_roles) for v in verses]
            unique_combos = set(combos)
            assert len(unique_combos) > 1, (
                f"All {len(verses)} verse sections use identical roles "
                f"{sorted(combos[0])}. Variation engine is not working."
            )

    def test_no_identical_hook_stem_maps_with_rich_stems(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        hooks = [s for s in plan.sections if s.section_type == "hook"]
        if len(hooks) >= 2:
            combos = [frozenset(h.active_roles) for h in hooks]
            unique_combos = set(combos)
            assert len(unique_combos) > 1, (
                f"All {len(hooks)} hook sections use identical roles "
                f"{sorted(combos[0])}."
            )

    def test_section_stem_map_reflects_sections(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        assert len(plan.section_stem_map) == len(plan.sections)
        for i, sp in enumerate(plan.sections):
            assert plan.section_stem_map[i] == sp.active_roles, (
                f"section_stem_map[{i}] mismatch: "
                f"{plan.section_stem_map[i]} != {sp.active_roles}"
            )


# ===========================================================================
# 5. Validator raises on invalid plans
# ===========================================================================

class TestValidator:
    """Validator must raise or warn on invalid/degenerate plans."""

    def test_flat_energy_plan_fails_validation(self):
        """A plan where every section has the same energy must fail."""
        sections = [
            SectionPlan(
                name=f"Verse {i+1}",
                section_type="verse",
                occurrence=i + 1,
                index=i,
                target_density=0.5,
                target_density_label="medium",
                target_energy=3,
                active_roles=["drums", "bass"],
                variation_strategy="none",
                bars=8,
                start_bar=i * 8,
            )
            for i in range(4)
        ]
        plan = ArrangementPlan(
            sections=sections,
            structure=["verse"] * 4,
            energy_curve=[3, 3, 3, 3],
            section_stem_map=[["drums", "bass"]] * 4,
            total_bars=32,
        )
        result = validate_plan(plan)
        assert not result.valid, "Flat energy plan should fail validation"
        assert any("flat" in e.lower() for e in result.errors)

    def test_hook_missing_transition_fails(self):
        """Hook with no transition_in must produce an error."""
        sections = [
            SectionPlan(
                name="Verse",
                section_type="verse",
                occurrence=1,
                index=0,
                target_density=0.55,
                target_density_label="medium",
                target_energy=3,
                active_roles=["drums", "bass"],
                variation_strategy="none",
                bars=8,
                start_bar=0,
                transition_in="none",
            ),
            SectionPlan(
                name="Hook",
                section_type="hook",
                occurrence=1,
                index=1,
                target_density=1.0,
                target_density_label="full",
                target_energy=5,
                active_roles=["drums", "bass", "melody"],
                variation_strategy="none",
                bars=8,
                start_bar=8,
                transition_in="none",  # Missing!
            ),
        ]
        plan = ArrangementPlan(
            sections=sections,
            structure=["verse", "hook"],
            energy_curve=[3, 5],
            section_stem_map=[["drums", "bass"], ["drums", "bass", "melody"]],
            total_bars=16,
        )
        result = validate_plan(plan)
        assert not result.valid, "Hook with no transition should fail validation"
        assert any("riser" in e.lower() or "transition" in e.lower() for e in result.errors)

    def test_validate_or_raise_raises_on_invalid(self):
        """validate_or_raise must raise ArrangementValidationError on invalid plan."""
        flat_sections = [
            SectionPlan(
                name=f"Section {i}",
                section_type="verse",
                occurrence=i + 1,
                index=i,
                target_density=0.5,
                target_density_label="medium",
                target_energy=3,
                active_roles=["drums"],
                variation_strategy="none",
                bars=8,
                start_bar=i * 8,
            )
            for i in range(3)
        ]
        plan = ArrangementPlan(
            sections=flat_sections,
            structure=["verse"] * 3,
            energy_curve=[3, 3, 3],
            section_stem_map=[["drums"]] * 3,
            total_bars=24,
        )
        with pytest.raises(ArrangementValidationError):
            validate_or_raise(plan)

    def test_valid_plan_passes_validation(self):
        """A well-formed plan built by the planner must pass validation."""
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        result = validate_plan(plan)
        assert result.valid, f"Valid plan failed: {result.errors}"


# ===========================================================================
# 6. Role engine rejects stems without valid roles
# ===========================================================================

class TestRoleEngine:
    """Role engine must reject unrecognised roles when strict=True."""

    def test_valid_roles_pass(self):
        models = validate_stem_roles(["drums", "bass", "melody"])
        assert len(models) == 3
        role_names = [m.role for m in models]
        assert "drums" in role_names
        assert "bass" in role_names
        assert "melody" in role_names

    def test_alias_is_normalised(self):
        models = validate_stem_roles(["kick", "808", "lead"])
        role_names = [m.role for m in models]
        assert "drums" in role_names   # kick → drums
        assert "bass" in role_names    # 808 → bass
        assert "melody" in role_names  # lead → melody

    def test_unknown_role_strict_raises(self):
        with pytest.raises(RoleValidationError):
            validate_stem_roles(["completely_unknown_role_xyz"], strict=True)

    def test_empty_input_raises(self):
        with pytest.raises(RoleValidationError):
            validate_stem_roles(["completely_unknown_xyz"], strict=False)

    def test_deduplication(self):
        models = validate_stem_roles(["drums", "drums", "bass"])
        assert len(models) == 2

    def test_get_valid_role_strings(self):
        roles = get_valid_role_strings(["kick", "snare", "bass", "melody"])
        # kick and snare both alias to drums → deduplicated to one
        assert "drums" in roles
        assert "bass" in roles
        assert "melody" in roles
        # drums appears only once despite two inputs
        assert roles.count("drums") == 1


# ===========================================================================
# 7. ArrangerState tracking
# ===========================================================================

class TestArrangerState:
    """State tracks used combos and detects flat energy."""

    def test_is_combo_used(self):
        state = ArrangerState()
        state.record_section("verse", ["drums", "bass"], energy=3)
        assert state.is_combo_used("verse", ["drums", "bass"])
        assert not state.is_combo_used("verse", ["drums", "bass", "melody"])
        assert not state.is_combo_used("hook", ["drums", "bass"])

    def test_flat_energy_detection(self):
        state = ArrangerState()
        # Not flat with < 3 sections.
        state.record_section("intro", ["pads"], energy=1)
        state.record_section("verse", ["drums", "bass"], energy=3)
        assert not state.is_energy_flat()
        # Record 3 sections with same energy.
        state.record_section("verse", ["drums", "bass", "melody"], energy=3)
        state.record_section("hook", ["drums", "bass", "melody"], energy=3)
        assert state.is_energy_flat()

    def test_previous_roles_for(self):
        state = ArrangerState()
        state.record_section("verse", ["drums", "bass"], energy=3)
        state.record_section("verse", ["drums", "bass", "melody"], energy=4)
        prev = state.previous_roles_for("verse")
        assert sorted(prev) == ["bass", "drums", "melody"]


# ===========================================================================
# 8. Density engine respects constraints
# ===========================================================================

class TestDensityEngine:
    """select_stems_for_section enforces density and section rules."""

    def test_intro_excludes_drums(self):
        state = ArrangerState()
        roles = select_stems_for_section(
            available_roles=RICH_ROLES,
            section_type="intro",
            target_density=0.25,
            state=state,
        )
        assert "drums" not in roles, f"Intro should not include drums, got {roles}"

    def test_hook_includes_drums_and_bass(self):
        state = ArrangerState()
        roles = select_stems_for_section(
            available_roles=RICH_ROLES,
            section_type="hook",
            target_density=1.0,
            state=state,
        )
        assert "drums" in roles, f"Hook must include drums, got {roles}"
        assert "bass" in roles, f"Hook must include bass, got {roles}"

    def test_low_density_produces_fewer_roles(self):
        state = ArrangerState()
        sparse = select_stems_for_section(
            available_roles=RICH_ROLES,
            section_type="verse",
            target_density=0.1,
            state=state,
        )
        full = select_stems_for_section(
            available_roles=RICH_ROLES,
            section_type="verse",
            target_density=1.0,
            state=state,
        )
        assert len(sparse) <= len(full), (
            f"Sparse ({len(sparse)}) should have fewer roles than full ({len(full)})"
        )

    def test_stereo_fallback_returns_full_mix(self):
        """When only full_mix is available, it should be returned."""
        state = ArrangerState()
        roles = select_stems_for_section(
            available_roles=FULL_MIX_ONLY,
            section_type="verse",
            target_density=0.55,
            state=state,
        )
        assert "full_mix" in roles


# ===========================================================================
# 9. Plan converts to render_plan correctly
# ===========================================================================

class TestRenderPlanConversion:
    """ArrangementPlan.to_render_plan() must produce a valid render_plan dict."""

    def test_to_render_plan_has_required_keys(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        render_plan = plan.to_render_plan(arrangement_id=42)
        required_keys = {
            "bpm", "key", "total_bars", "sections", "events",
            "section_boundaries", "sections_count", "events_count",
        }
        for key in required_keys:
            assert key in render_plan, f"render_plan missing required key: {key!r}"

    def test_sections_count_matches(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        render_plan = plan.to_render_plan()
        assert render_plan["sections_count"] == len(plan.sections)
        assert len(render_plan["sections"]) == len(plan.sections)

    def test_section_instruments_populated(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        render_plan = plan.to_render_plan()
        for raw_section in render_plan["sections"]:
            assert "instruments" in raw_section, "Section missing instruments key"
            assert len(raw_section["instruments"]) >= 1, (
                f"Section {raw_section.get('name')} has no instruments"
            )

    def test_transition_events_present_for_hooks(self):
        plan = build_arrangement_plan(
            available_roles=RICH_ROLES,
            target_total_bars=64,
        )
        render_plan = plan.to_render_plan()
        events = render_plan.get("events", [])
        # At least one riser-type event should be present.
        riser_event_types = {"riser_fx", "reverse_cymbal", "silence_drop", "pre_hook_silence_drop"}
        transition_events = [e for e in events if e.get("type") in riser_event_types]
        assert len(transition_events) > 0, (
            "No riser/transition events found in render_plan events. "
            "Hooks should have riser events."
        )
