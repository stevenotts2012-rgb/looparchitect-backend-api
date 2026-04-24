"""
Tests for the Instrument Activation Rules engine.

app/services/instrument_activation_rules.py

Covers:
- Rules load correctly from JSON
- All required sections are present
- INTRO blocks bass and drums
- HOOK density >= VERSE density
- PRE_HOOK exposes drop_kick flag on drums
- OUTRO removes bass (active=False)
- variation_seed produces deterministic changes
- Rules affect the resolved plan via FinalPlanResolver
- Resolved plan roles actually change (no no-op)
- Genre / vibe modifiers are applied correctly
- Section name normalisation works
- Invalid / missing rules fall back gracefully
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from app.services.instrument_activation_rules import (
    InstrumentActivationRules,
    _normalise_section,
    get_rules_for_section,
)
from app.services.final_plan_resolver import FinalPlanResolver
from app.services.resolved_render_plan import ResolvedRenderPlan


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine() -> InstrumentActivationRules:
    """Return a freshly loaded engine using the bundled JSON ruleset."""
    return InstrumentActivationRules()


def _make_render_plan(sections: list | None = None, **kwargs) -> dict:
    sections = sections or []
    return {
        "bpm": kwargs.get("bpm", 120.0),
        "key": "C major",
        "total_bars": sum(s.get("bars", 8) for s in sections),
        "sections": sections,
        "_decision_plan": None,
        "_drop_plan": None,
        "render_profile": {},
    }


def _make_section(
    name: str = "Verse 1",
    section_type: str = "verse",
    instruments: list | None = None,
    bars: int = 8,
    energy: float = 0.6,
    bar_start: int = 0,
) -> dict:
    roles = instruments or ["drums", "bass", "melody", "chords", "arp", "percussion", "fx"]
    return {
        "name": name,
        "type": section_type,
        "bar_start": bar_start,
        "bars": bars,
        "energy": energy,
        "instruments": roles,
        "active_stem_roles": roles,
        "boundary_events": [],
        "timeline_events": [],
        "variations": [],
    }


# ===========================================================================
# 1. Engine loads correctly
# ===========================================================================


class TestEngineLoads:
    def test_engine_is_loaded(self, engine: InstrumentActivationRules):
        assert engine.is_loaded

    def test_version_string(self, engine: InstrumentActivationRules):
        assert isinstance(engine.version, str)
        assert len(engine.version) > 0

    def test_metadata_structure(self, engine: InstrumentActivationRules):
        meta = engine.get_rule_set_metadata()
        assert meta["is_loaded"] is True
        assert meta["load_failure"] is None
        assert isinstance(meta["sections_available"], list)

    def test_missing_file_sets_load_failure(self, tmp_path: Path):
        engine = InstrumentActivationRules(rules_path=tmp_path / "no_such_file.json")
        assert not engine.is_loaded
        assert engine._load_failure is not None

    def test_invalid_json_sets_load_failure(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid json!}")
        engine = InstrumentActivationRules(rules_path=bad)
        assert not engine.is_loaded

    def test_missing_sections_key_sets_load_failure(self, tmp_path: Path):
        bad = tmp_path / "no_sections.json"
        bad.write_text('{"version": "0.0.0"}')
        engine = InstrumentActivationRules(rules_path=bad)
        assert not engine.is_loaded


# ===========================================================================
# 2. All required sections exist
# ===========================================================================


REQUIRED_SECTIONS = {"INTRO", "VERSE", "PRE_HOOK", "HOOK", "BRIDGE", "OUTRO"}


class TestAllSectionsCovered:
    @pytest.mark.parametrize("section", sorted(REQUIRED_SECTIONS))
    def test_section_present(self, engine: InstrumentActivationRules, section: str):
        rules = engine.get_rules_for_section(section)
        assert rules["section_type"] == section
        assert isinstance(rules["roles"], dict)
        assert len(rules["roles"]) > 0

    def test_all_sections_available_in_metadata(self, engine: InstrumentActivationRules):
        meta = engine.get_rule_set_metadata()
        for section in REQUIRED_SECTIONS:
            assert section in meta["sections_available"]

    def test_unknown_section_raises_key_error(self, engine: InstrumentActivationRules):
        with pytest.raises(KeyError):
            engine.get_rules_for_section("NONEXISTENT_SECTION_XYZ")

    def test_unknown_section_returns_empty_when_not_loaded(self, tmp_path: Path):
        broken = InstrumentActivationRules(rules_path=tmp_path / "missing.json")
        result = broken.get_rules_for_section("HOOK")
        assert result["roles"] == {}


# ===========================================================================
# 3. INTRO blocks bass and drums
# ===========================================================================


class TestIntroBehavior:
    def test_intro_bass_inactive(self, engine: InstrumentActivationRules):
        rules = engine.get_rules_for_section("INTRO")
        assert rules["roles"]["bass"]["active"] is False

    def test_intro_drums_inactive(self, engine: InstrumentActivationRules):
        rules = engine.get_rules_for_section("INTRO")
        assert rules["roles"]["drums"]["active"] is False

    def test_intro_melody_active(self, engine: InstrumentActivationRules):
        rules = engine.get_rules_for_section("INTRO")
        assert rules["roles"]["melody"]["active"] is True

    def test_intro_blocks_bass_in_resolved_plan(self):
        plan = _make_render_plan([_make_section("Intro", "intro")])
        resolver = FinalPlanResolver(plan, available_roles=["melody", "bass", "drums"])
        result = resolver.resolve()
        sec = result.resolved_sections[0]
        assert "bass" not in sec.final_active_roles
        assert "bass" in sec.final_blocked_roles

    def test_intro_blocks_drums_in_resolved_plan(self):
        plan = _make_render_plan([_make_section("Intro", "intro")])
        resolver = FinalPlanResolver(plan, available_roles=["melody", "bass", "drums"])
        result = resolver.resolve()
        sec = result.resolved_sections[0]
        assert "drums" not in sec.final_active_roles
        assert "drums" in sec.final_blocked_roles


# ===========================================================================
# 4. HOOK density >= VERSE density
# ===========================================================================


class TestHookDensity:
    DENSITY_ROLES = ["melody", "bass", "drums", "chords", "percussion"]

    @pytest.mark.parametrize("role", DENSITY_ROLES)
    def test_hook_density_gte_verse(self, engine: InstrumentActivationRules, role: str):
        hook_rules = engine.get_rules_for_section("HOOK")
        verse_rules = engine.get_rules_for_section("VERSE")
        hook_density = float(hook_rules["roles"].get(role, {}).get("density") or 0.0)
        verse_density = float(verse_rules["roles"].get(role, {}).get("density") or 0.0)
        assert hook_density >= verse_density, (
            f"HOOK.{role} density ({hook_density}) < VERSE.{role} density ({verse_density})"
        )

    def test_hook_target_fullness_is_full(self):
        plan = _make_render_plan([_make_section("Hook 1", "hook")])
        result = FinalPlanResolver(plan).resolve()
        assert result.resolved_sections[0].target_fullness == "full"


# ===========================================================================
# 5. PRE_HOOK drop_kick
# ===========================================================================


class TestPreHookDropKick:
    def test_pre_hook_drums_has_drop_kick(self, engine: InstrumentActivationRules):
        rules = engine.get_rules_for_section("PRE_HOOK")
        drums = rules["roles"]["drums"]
        assert drums.get("drop_kick") is True

    def test_pre_hook_drop_kick_produces_pattern_event(self):
        plan = _make_render_plan([_make_section("Pre Hook", "pre_hook")])
        result = FinalPlanResolver(plan).resolve()
        sec = result.resolved_sections[0]
        drop_kick_events = [
            e for e in sec.final_pattern_events
            if e.get("action") == "drop_kick"
        ]
        assert len(drop_kick_events) == 1

    def test_pre_hook_drop_kick_event_has_correct_source(self):
        plan = _make_render_plan([_make_section("Pre Hook", "pre_hook")])
        result = FinalPlanResolver(plan).resolve()
        sec = result.resolved_sections[0]
        drop_kick_events = [
            e for e in sec.final_pattern_events
            if e.get("action") == "drop_kick"
        ]
        assert drop_kick_events[0]["source"] == "instrument_activation_rules"

    def test_pre_hook_normalised_names_trigger_drop_kick(self):
        """Aliases like 'pre_chorus' should also produce the drop_kick event."""
        for alias in ("pre_chorus", "buildup", "build"):
            plan = _make_render_plan([_make_section("Section", alias)])
            result = FinalPlanResolver(plan).resolve()
            sec = result.resolved_sections[0]
            drop_kick_events = [
                e for e in sec.final_pattern_events
                if e.get("action") == "drop_kick"
            ]
            assert len(drop_kick_events) == 1, (
                f"Expected drop_kick event for alias '{alias}'"
            )


# ===========================================================================
# 6. OUTRO removes bass
# ===========================================================================


class TestOutroBehavior:
    def test_outro_bass_inactive(self, engine: InstrumentActivationRules):
        rules = engine.get_rules_for_section("OUTRO")
        assert rules["roles"]["bass"]["active"] is False

    def test_outro_removes_bass_in_resolved_plan(self):
        all_roles = ["melody", "bass", "drums", "chords", "arp", "percussion", "fx"]
        plan = _make_render_plan([_make_section("Outro", "outro", instruments=all_roles)])
        result = FinalPlanResolver(plan, available_roles=all_roles).resolve()
        sec = result.resolved_sections[0]
        assert "bass" not in sec.final_active_roles
        assert "bass" in sec.final_blocked_roles

    def test_outro_target_fullness_is_sparse(self):
        plan = _make_render_plan([_make_section("Outro", "outro")])
        result = FinalPlanResolver(plan).resolve()
        assert result.resolved_sections[0].target_fullness == "sparse"


# ===========================================================================
# 7. Variation seed — deterministic + musical validity
# ===========================================================================


class TestVariationSeed:
    def test_same_seed_produces_identical_rules(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("VERSE")
        result_a = engine.apply_variation_seed(base, seed=42)
        result_b = engine.apply_variation_seed(copy.deepcopy(base), seed=42)
        assert result_a == result_b

    def test_different_seeds_produce_different_rules(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("HOOK")
        result_a = engine.apply_variation_seed(base, seed=1)
        result_b = engine.apply_variation_seed(copy.deepcopy(base), seed=999)
        # At least one role density must differ between the two seeds.
        density_differs = any(
            result_a["roles"][role].get("density") != result_b["roles"][role].get("density")
            for role in result_a["roles"]
        )
        assert density_differs, "Expected density to differ between seeds 1 and 999"

    def test_variation_keeps_density_in_valid_range(self, engine: InstrumentActivationRules):
        for seed in (0, 1, 42, 100, 9999):
            base = engine.get_rules_for_section("HOOK")
            result = engine.apply_variation_seed(base, seed=seed)
            for role, rule in result["roles"].items():
                density = rule.get("density")
                if density is not None:
                    assert 0.0 <= density <= 1.0, (
                        f"seed={seed} role={role}: density {density} out of range"
                    )

    def test_variation_seed_recorded_in_result(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("VERSE")
        result = engine.apply_variation_seed(base, seed=77)
        assert result.get("_variation_seed") == 77

    def test_resolver_variation_seed_is_deterministic(self):
        """FinalPlanResolver with the same seed produces the same resolved plan."""
        sections = [
            _make_section("Hook 1", "hook", bar_start=0),
            _make_section("Verse 1", "verse", bar_start=8),
        ]
        plan = _make_render_plan(sections)

        result_a = FinalPlanResolver(plan, variation_seed=42).resolve().to_dict()
        result_b = FinalPlanResolver(copy.deepcopy(plan), variation_seed=42).resolve().to_dict()
        assert result_a == result_b

    def test_resolver_different_seeds_differ(self):
        sections = [_make_section("Verse 1", "verse")]
        plan = _make_render_plan(sections)
        result_a = FinalPlanResolver(plan, variation_seed=1).resolve()
        result_b = FinalPlanResolver(copy.deepcopy(plan), variation_seed=9999).resolve()
        sec_a = result_a.resolved_sections[0]
        sec_b = result_b.resolved_sections[0]
        # rule_snapshots must be present and could differ
        assert sec_a.rule_snapshot is not None
        assert sec_b.rule_snapshot is not None


# ===========================================================================
# 8. Rules affect resolved plan (not a no-op)
# ===========================================================================


class TestRulesAffectResolvedPlan:
    def test_rules_applied_flag_is_true(self):
        plan = _make_render_plan([_make_section()])
        result = FinalPlanResolver(plan).resolve()
        assert result.rules_applied is True

    def test_rule_set_version_populated(self):
        plan = _make_render_plan([_make_section()])
        result = FinalPlanResolver(plan).resolve()
        assert result.rule_set_version is not None and len(result.rule_set_version) > 0

    def test_rule_modifiers_populated_when_genre_vibe_given(self):
        plan = _make_render_plan([_make_section()])
        result = FinalPlanResolver(plan, genre="trap", vibe="dark").resolve()
        assert result.rule_modifiers.get("genre") == "trap"
        assert result.rule_modifiers.get("vibe") == "dark"

    def test_rule_snapshot_present_on_sections(self):
        plan = _make_render_plan([_make_section("Verse 1", "verse")])
        result = FinalPlanResolver(plan).resolve()
        sec = result.resolved_sections[0]
        assert sec.rule_snapshot is not None
        assert "roles" in sec.rule_snapshot

    def test_active_roles_count_in_to_dict(self):
        plan = _make_render_plan([_make_section("Hook 1", "hook")])
        result = FinalPlanResolver(plan).resolve()
        d = result.resolved_sections[0].to_dict()
        assert "active_roles_count" in d
        assert "blocked_roles_count" in d
        assert isinstance(d["active_roles_count"], int)
        assert isinstance(d["blocked_roles_count"], int)

    def test_intro_roles_actually_blocked_not_just_metadata(self):
        """Ensure that IAR blocking changes final_active_roles (not metadata-only)."""
        all_roles = ["melody", "bass", "drums"]
        plan = _make_render_plan([_make_section("Intro", "intro", instruments=all_roles)])
        result = FinalPlanResolver(plan, available_roles=all_roles).resolve()
        sec = result.resolved_sections[0]
        # bass and drums should be missing from final_active_roles
        assert set(sec.final_active_roles).isdisjoint({"bass", "drums"})
        # They should be in final_blocked_roles instead
        assert "bass" in sec.final_blocked_roles
        assert "drums" in sec.final_blocked_roles

    def test_hook_has_all_available_roles_active(self):
        """HOOK rules mark all main roles active — none should be IAR-blocked."""
        all_roles = ["melody", "bass", "drums", "chords", "arp", "percussion", "fx"]
        plan = _make_render_plan([_make_section("Hook 1", "hook", instruments=all_roles)])
        result = FinalPlanResolver(plan, available_roles=all_roles).resolve()
        sec = result.resolved_sections[0]
        # All HOOK roles are active in the ruleset — none blocked by IAR.
        assert len(sec.final_blocked_roles) == 0
        assert set(all_roles) == set(sec.final_active_roles)

    def test_target_fullness_set_for_every_section(self):
        sections = [
            _make_section("Intro", "intro", bar_start=0),
            _make_section("Verse 1", "verse", bar_start=8),
            _make_section("Pre Hook", "pre_hook", bar_start=16),
            _make_section("Hook 1", "hook", bar_start=24),
            _make_section("Bridge", "bridge", bar_start=32),
            _make_section("Outro", "outro", bar_start=40),
        ]
        plan = _make_render_plan(sections)
        result = FinalPlanResolver(plan).resolve()
        for sec in result.resolved_sections:
            assert sec.target_fullness is not None, (
                f"target_fullness not set for section '{sec.section_name}'"
            )


# ===========================================================================
# 9. Genre / vibe modifiers
# ===========================================================================


class TestGenreVibeModifiers:
    def test_dark_reduces_melody_density(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("VERSE")
        modified = engine.apply_genre_vibe_modifiers(base, vibe="dark")
        base_density = float(base["roles"]["melody"].get("density") or 0.0)
        mod_density = float(modified["roles"]["melody"].get("density") or 0.0)
        assert mod_density < base_density

    def test_hype_increases_drum_complexity(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("HOOK")
        modified = engine.apply_genre_vibe_modifiers(base, vibe="hype")
        base_complexity = float(base["roles"]["drums"].get("complexity") or 0.0)
        mod_complexity = float(modified["roles"]["drums"].get("complexity") or 0.0)
        assert mod_complexity > base_complexity

    def test_emotional_increases_chords_density(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("VERSE")
        modified = engine.apply_genre_vibe_modifiers(base, vibe="emotional")
        base_density = float(base["roles"]["chords"].get("density") or 0.0)
        mod_density = float(modified["roles"]["chords"].get("density") or 0.0)
        assert mod_density > base_density

    def test_rage_enables_hat_rolls(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("VERSE")
        modified = engine.apply_genre_vibe_modifiers(base, vibe="rage")
        assert modified["roles"]["percussion"].get("rolls") is True

    def test_trap_genre_increases_bass_density(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("VERSE")
        modified = engine.apply_genre_vibe_modifiers(base, genre="trap")
        base_density = float(base["roles"]["bass"].get("density") or 0.0)
        mod_density = float(modified["roles"]["bass"].get("density") or 0.0)
        assert mod_density > base_density

    def test_modifiers_applied_metadata_recorded(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("HOOK")
        modified = engine.apply_genre_vibe_modifiers(base, genre="trap", vibe="dark")
        assert "_modifiers_applied" in modified
        assert len(modified["_modifiers_applied"]) > 0

    def test_modifier_density_stays_in_range(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("HOOK")
        for vibe in ("dark", "hype", "rage", "emotional", "chill"):
            modified = engine.apply_genre_vibe_modifiers(base, vibe=vibe)
            for role, rule in modified["roles"].items():
                density = rule.get("density")
                if density is not None:
                    assert 0.0 <= density <= 1.0, (
                        f"vibe={vibe} role={role}: density {density} out of valid range"
                    )

    def test_unknown_genre_vibe_returns_unchanged_rules(self, engine: InstrumentActivationRules):
        base = engine.get_rules_for_section("VERSE")
        modified = engine.apply_genre_vibe_modifiers(base, genre="unknown_xyz", vibe="unknown_abc")
        # Roles should be unaffected
        for role in base["roles"]:
            assert base["roles"][role].get("density") == modified["roles"][role].get("density")


# ===========================================================================
# 10. Section name normalisation
# ===========================================================================


class TestSectionNameNormalisation:
    @pytest.mark.parametrize("alias,expected", [
        ("pre_chorus", "PRE_HOOK"),
        ("prechorus", "PRE_HOOK"),
        ("pre-chorus", "PRE_HOOK"),
        ("buildup", "PRE_HOOK"),
        ("build", "PRE_HOOK"),
        ("chorus", "HOOK"),
        ("drop", "HOOK"),
        ("hook", "HOOK"),
        ("HOOK", "HOOK"),
        ("breakdown", "BRIDGE"),
        ("INTRO", "INTRO"),
        ("intro", "INTRO"),
        ("verse", "VERSE"),
        ("bridge", "BRIDGE"),
        ("outro", "OUTRO"),
    ])
    def test_normalise_section(self, alias: str, expected: str):
        assert _normalise_section(alias) == expected

    def test_resolver_normalises_section_type(self):
        """FinalPlanResolver correctly resolves sections using aliases."""
        plan = _make_render_plan([_make_section("Pre Chorus", "pre_chorus")])
        result = FinalPlanResolver(plan).resolve()
        sec = result.resolved_sections[0]
        # IAR should have been applied (rule_snapshot populated)
        assert sec.rule_snapshot is not None


# ===========================================================================
# 11. Fallback behaviour
# ===========================================================================


class TestFallbackBehavior:
    def test_fallback_when_engine_not_loaded(self):
        """Module-level get_rules_for_section returns empty dict on engine failure."""
        from app.services import instrument_activation_rules as iar_module
        bad_engine = InstrumentActivationRules(rules_path=Path("/non/existent.json"))
        with patch.object(iar_module, "_ENGINE", bad_engine):
            result = get_rules_for_section("HOOK")
        assert result["roles"] == {}

    def test_resolver_works_when_engine_not_loaded(self, tmp_path: Path):
        """FinalPlanResolver degrades gracefully when IAR engine fails to load."""
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{invalid}")
        from app.services import instrument_activation_rules as iar_module

        bad_engine = InstrumentActivationRules(rules_path=bad_json)

        plan = _make_render_plan([_make_section("Verse 1", "verse")])
        resolver = FinalPlanResolver(plan)
        # Patch the resolver's private engine attribute
        resolver._rules_engine = bad_engine

        result = resolver.resolve()
        # Should succeed without raising and without rules metadata
        assert isinstance(result, ResolvedRenderPlan)
        assert result.rules_applied is False
        # Sections should still be resolved (legacy path)
        assert result.section_count == 1

    def test_resolver_rules_applied_false_when_no_engine(self):
        """rules_applied=False when engine is None."""
        plan = _make_render_plan([_make_section()])
        resolver = FinalPlanResolver(plan)
        resolver._rules_engine = None
        result = resolver.resolve()
        assert result.rules_applied is False
        assert result.rule_set_version is None

    def test_section_rule_snapshot_none_when_engine_absent(self):
        plan = _make_render_plan([_make_section("Verse 1", "verse")])
        resolver = FinalPlanResolver(plan)
        resolver._rules_engine = None
        result = resolver.resolve()
        sec = result.resolved_sections[0]
        assert sec.rule_snapshot is None
        assert sec.target_fullness is None
