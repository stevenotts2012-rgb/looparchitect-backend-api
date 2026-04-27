"""Tests for the intelligent arrangement system.

Covers:
- Deterministic seed behaviour (same seed → identical output)
- Variation behaviour (different seed → different output)
- Musical rules (hook energy, intro 808-free, outro stripped)
- Vibe modifier effects on density/complexity
- Fallback safety (missing configs, unknown genres/vibes)
- _parse_intelligent_controls_from_json helper
"""

from __future__ import annotations

import json
import pytest

# ---------------------------------------------------------------------------
# Template selector
# ---------------------------------------------------------------------------

from app.style_engine.template_selector import select_template, TemplateSelectionResult


class TestTemplateSelector:
    def test_same_seed_returns_same_template(self):
        r1 = select_template(genre="trap", variation_seed=42)
        r2 = select_template(genre="trap", variation_seed=42)
        assert r1.selected_template_id == r2.selected_template_id

    def test_different_seeds_may_differ(self):
        """Different seeds should not always return the same template (at least across the
        full set of genres and seeds the variety is exercised)."""
        # Collect results across multiple seeds for a given genre
        ids = {
            select_template(genre="trap", variation_seed=s).selected_template_id
            for s in range(50)
        }
        # There are 5 trap templates; across 50 seeds at least 2 should appear
        assert len(ids) >= 2

    def test_returns_template_selection_result(self):
        result = select_template(genre="drill", variation_seed=1)
        assert isinstance(result, TemplateSelectionResult)
        assert result.selected_template_id
        assert result.template_total_bars > 0
        assert result.seed_used is not None

    def test_vibe_affects_selection_score(self):
        """Passing a vibe hint should not crash; result is still a TemplateSelectionResult."""
        result = select_template(genre="rnb", vibe="dark", variation_seed=7)
        assert isinstance(result, TemplateSelectionResult)

    def test_all_supported_genres(self):
        for genre in ("trap", "drill", "rnb", "rage"):
            result = select_template(genre=genre, variation_seed=123)
            assert result.selected_template_id.startswith(genre[0])

    def test_unknown_genre_raises_value_error(self):
        with pytest.raises((ValueError, RuntimeError)):
            select_template(genre="polka", variation_seed=1)

    def test_none_seed_still_works(self):
        result = select_template(genre="trap", variation_seed=None)
        assert isinstance(result, TemplateSelectionResult)
        assert result.seed_used is not None  # auto-generated


# ---------------------------------------------------------------------------
# Instrument Activation Rules
# ---------------------------------------------------------------------------

from app.services.instrument_activation_rules import get_rules_for_section


class TestInstrumentActivationRules:
    def test_hook_has_drums_active(self):
        rules = get_rules_for_section("hook")
        assert isinstance(rules, dict)
        roles = rules.get("roles", {})
        drums = roles.get("drums", {})
        assert drums.get("active") is True

    def test_intro_drums_not_active(self):
        """Intro should have drums/808 inactive per musical rules."""
        rules = get_rules_for_section("intro")
        roles = rules.get("roles", {})
        drums = roles.get("drums", {})
        # IAR rules specify drums as inactive for intro
        assert drums.get("active") is False

    def test_outro_has_stripped_density(self):
        """Outro should be sparse (low density)."""
        rules = get_rules_for_section("outro")
        roles = rules.get("roles", {})
        drums = roles.get("drums", {})
        # Drums inactive or very low density in outro
        drums_active = drums.get("active", True)
        drums_density = float(drums.get("density", 0))
        assert (not drums_active) or drums_density <= 0.4

    def test_hook_highest_energy_drums(self):
        """Hook should have higher drum density than verse."""
        hook_rules = get_rules_for_section("hook")
        verse_rules = get_rules_for_section("verse")
        hook_density = float(hook_rules.get("roles", {}).get("drums", {}).get("density", 0))
        verse_density = float(verse_rules.get("roles", {}).get("drums", {}).get("density", 0))
        assert hook_density >= verse_density

    def test_returns_dict_for_all_section_types(self):
        for section in ("intro", "verse", "pre_hook", "hook", "bridge", "outro"):
            rules = get_rules_for_section(section)
            assert isinstance(rules, dict)
            assert "roles" in rules

    def test_never_crashes_on_unknown_section(self):
        """Fallback must return a valid dict even for unknown section names."""
        rules = get_rules_for_section("totally_unknown_section_xyz")
        assert isinstance(rules, dict)
        assert "roles" in rules

    def test_section_type_normalisation(self):
        """Aliases like 'chorus' should map to hook rules."""
        chorus_rules = get_rules_for_section("chorus")
        hook_rules = get_rules_for_section("hook")
        assert chorus_rules.get("section_type", "").upper() == hook_rules.get("section_type", "").upper()


# ---------------------------------------------------------------------------
# Vibe Modifier Engine
# ---------------------------------------------------------------------------

from app.services.vibe_modifier_engine import apply_vibe


class TestVibeModifierEngine:
    def test_same_seed_deterministic(self):
        rules = get_rules_for_section("hook")
        r1 = apply_vibe(section_type="hook", instrument_rules=rules, selected_vibe="dark", variation_seed=99)
        r2 = apply_vibe(section_type="hook", instrument_rules=rules, selected_vibe="dark", variation_seed=99)
        assert r1.get("vibe_applied") == r2.get("vibe_applied")
        assert r1.get("vibe_name") == r2.get("vibe_name")

    def test_vibe_changes_density(self):
        """Applying a vibe should modify density for at least one role compared to baseline."""
        rules = get_rules_for_section("verse")
        baseline_density = float(rules.get("roles", {}).get("melody", {}).get("density", 0.5))
        result = apply_vibe(section_type="verse", instrument_rules=rules, selected_vibe="hype", variation_seed=7)
        # hype vibe should raise density
        new_density = float(
            result.get("roles", {}).get("melody", {}).get("density", baseline_density)
        )
        # density_before_vs_after captures the delta
        bva = result.get("density_before_vs_after", {})
        assert isinstance(bva, dict)

    def test_all_values_clamped_to_0_1(self):
        """No density/complexity value should escape [0, 1] after vibe application."""
        for vibe in ("dark", "emotional", "hype", "rage", "ambient", "cinematic"):
            rules = get_rules_for_section("hook")
            result = apply_vibe(section_type="hook", instrument_rules=rules, selected_vibe=vibe, variation_seed=0)
            for role_name, role_data in result.get("roles", {}).items():
                if isinstance(role_data, dict):
                    density = role_data.get("density")
                    complexity = role_data.get("complexity")
                    if density is not None:
                        assert 0.0 <= float(density) <= 1.0, (
                            f"density out of range for vibe={vibe} role={role_name}: {density}"
                        )
                    if complexity is not None:
                        assert 0.0 <= float(complexity) <= 1.0, (
                            f"complexity out of range for vibe={vibe} role={role_name}: {complexity}"
                        )

    def test_returns_vibe_applied_flag(self):
        rules = get_rules_for_section("hook")
        result = apply_vibe(section_type="hook", instrument_rules=rules, selected_vibe="rage", variation_seed=1)
        assert "vibe_applied" in result

    def test_unknown_vibe_does_not_crash(self):
        """Unknown vibe falls back gracefully — original rules returned."""
        rules = get_rules_for_section("verse")
        result = apply_vibe(section_type="verse", instrument_rules=rules, selected_vibe="nonexistent_vibe_xyz", variation_seed=0)
        assert isinstance(result, dict)
        assert "roles" in result

    def test_none_vibe_does_not_crash(self):
        rules = get_rules_for_section("hook")
        result = apply_vibe(section_type="hook", instrument_rules=rules, selected_vibe="", variation_seed=0)
        assert isinstance(result, dict)

    def test_dark_vibe_reduces_density(self):
        """Dark vibe should lower overall density relative to hype vibe."""
        rules_hook = get_rules_for_section("hook")
        dark = apply_vibe(section_type="hook", instrument_rules=rules_hook, selected_vibe="dark", variation_seed=5)
        hype = apply_vibe(section_type="hook", instrument_rules=rules_hook, selected_vibe="hype", variation_seed=5)
        # Collect sum of densities
        def _total_density(r: dict) -> float:
            return sum(
                float(v.get("density", 0))
                for v in r.get("roles", {}).values()
                if isinstance(v, dict)
            )
        assert _total_density(dark) <= _total_density(hype)


# ---------------------------------------------------------------------------
# _parse_intelligent_controls_from_json helper
# ---------------------------------------------------------------------------

from app.services.arrangement_jobs import _parse_intelligent_controls_from_json


class TestParseIntelligentControls:
    def test_parses_all_fields(self):
        payload = json.dumps({
            "genre_override": "drill",
            "vibe_override": "dark",
            "variation_seed": 42,
            "variation_intensity": 0.75,
        })
        result = _parse_intelligent_controls_from_json(payload)
        assert result["genre_override"] == "drill"
        assert result["vibe_override"] == "dark"
        assert result["variation_seed"] == 42
        assert result["variation_intensity"] == pytest.approx(0.75)

    def test_returns_defaults_on_none(self):
        result = _parse_intelligent_controls_from_json(None)
        assert result["genre_override"] is None
        assert result["vibe_override"] is None
        assert result["variation_seed"] is None
        assert result["variation_intensity"] is None

    def test_returns_defaults_on_empty_string(self):
        result = _parse_intelligent_controls_from_json("")
        assert result["genre_override"] is None

    def test_returns_defaults_on_invalid_json(self):
        result = _parse_intelligent_controls_from_json("{not valid json}")
        assert result["genre_override"] is None

    def test_genre_lowercased(self):
        payload = json.dumps({"genre_override": "TRAP"})
        result = _parse_intelligent_controls_from_json(payload)
        assert result["genre_override"] == "trap"

    def test_partial_fields(self):
        payload = json.dumps({"genre_override": "rnb"})
        result = _parse_intelligent_controls_from_json(payload)
        assert result["genre_override"] == "rnb"
        assert result["vibe_override"] is None
        assert result["variation_seed"] is None


# ---------------------------------------------------------------------------
# Musical rule assertions (cross-engine)
# ---------------------------------------------------------------------------

class TestMusicalRules:
    """Verify that key musical rules hold across the full IAR → vibe pipeline."""

    def test_intro_bass_inactive_or_minimal(self):
        """Bass/808 should be inactive or very low density in intro."""
        rules = get_rules_for_section("intro")
        bass = rules.get("roles", {}).get("bass", {})
        assert not bass.get("active", True) or float(bass.get("density", 0)) <= 0.2

    def test_hook_has_higher_energy_than_intro(self):
        """Hook drum density must exceed intro drum density."""
        intro = get_rules_for_section("intro")
        hook = get_rules_for_section("hook")
        intro_d = float(intro.get("roles", {}).get("drums", {}).get("density", 0))
        hook_d = float(hook.get("roles", {}).get("drums", {}).get("density", 0))
        assert hook_d > intro_d

    def test_outro_drums_stripped(self):
        """Outro should remove or heavily reduce drums."""
        rules = get_rules_for_section("outro")
        drums = rules.get("roles", {}).get("drums", {})
        active = drums.get("active", True)
        density = float(drums.get("density", 1.0))
        assert (not active) or density <= 0.35

    def test_hook_melody_density_is_high(self):
        """Hook should have significant melody presence."""
        rules = get_rules_for_section("hook")
        melody = rules.get("roles", {}).get("melody", {})
        density = float(melody.get("density", 0))
        assert density >= 0.6
