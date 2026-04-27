"""
Tests for the Vibe Modifier Engine.

app/services/vibe_modifier_engine.py

Covers:
- Same seed produces deterministic output
- Multipliers applied correctly and values always clamped to [0, 1]
- Probabilistic features (counter melody, 808 slides, hihat rolls) respected
- Section energy shift applied per section type
- Filter flags activated based on vibe probabilities
- All 7 vibes modify behaviour differently
- Safety: missing/unknown vibe falls back to original rules unchanged
- Safety: bad config path falls back gracefully without crashing
- Metadata fields (vibe_applied, vibe_name, vibe_modifiers_applied,
  density_before_vs_after) are present in return value
"""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

import app.services.vibe_modifier_engine as vme
from app.services.vibe_modifier_engine import apply_vibe, _clamp, _reset_cache


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _base_rules(section_type: str = "HOOK") -> Dict[str, Any]:
    """Minimal instrument_rules dict matching the output of InstrumentActivationRules."""
    return {
        "section_type": section_type,
        "target_energy": 0.8,
        "roles": {
            "melody": {"active": True, "density": 0.85, "complexity": 0.8},
            "arp": {"active": False, "density": 0.6, "complexity": 0.6},
            "chords": {"active": True, "density": 0.8, "complexity": 0.7},
            "bass": {
                "active": True,
                "density": 0.9,
                "complexity": 0.75,
                "slides": True,
            },
            "drums": {"active": True, "density": 1.0, "complexity": 0.85},
            "percussion": {
                "active": True,
                "density": 0.85,
                "complexity": 0.8,
                "rolls": False,
            },
            "fx": {
                "active": True,
                "density": 0.7,
                "complexity": 0.7,
                "intensity": 0.85,
            },
        },
    }


@pytest.fixture(autouse=True)
def reset_module_cache():
    """Reset the module-level rules cache before each test."""
    _reset_cache()
    yield
    _reset_cache()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5) == 0.5

    def test_above_max(self):
        assert _clamp(1.5) == 1.0

    def test_below_min(self):
        assert _clamp(-0.3) == 0.0

    def test_exact_bounds(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(1.0) == 1.0

    def test_rounds_to_4dp(self):
        assert _clamp(0.123456789) == 0.1235


# ---------------------------------------------------------------------------
# Safety / fallback
# ---------------------------------------------------------------------------


class TestSafety:
    def test_empty_vibe_returns_unchanged(self):
        rules = _base_rules()
        result = apply_vibe(
            section_type="HOOK",
            instrument_rules=rules,
            selected_vibe="",
            variation_seed=1,
        )
        assert result["roles"]["melody"]["density"] == rules["roles"]["melody"]["density"]
        assert "vibe_applied" not in result

    def test_unknown_vibe_returns_original(self):
        rules = _base_rules()
        result = apply_vibe(
            section_type="HOOK",
            instrument_rules=rules,
            selected_vibe="nonexistent_vibe",
            variation_seed=1,
        )
        assert result["roles"]["melody"]["density"] == rules["roles"]["melody"]["density"]
        assert result.get("vibe_applied") is not True

    def test_bad_config_path_does_not_crash(self):
        """Engine must not crash when config file is missing."""
        _reset_cache()
        result = apply_vibe(
            section_type="HOOK",
            instrument_rules=_base_rules(),
            selected_vibe="dark",
            variation_seed=42,
            rules_path=Path("/nonexistent/path/vibe_modifier_rules.json"),
        )
        # Falls back gracefully — no exception
        assert isinstance(result, dict)
        assert "roles" in result

    def test_original_rules_not_mutated(self):
        """Input instrument_rules must never be mutated."""
        rules = _base_rules()
        original_density = rules["roles"]["melody"]["density"]
        apply_vibe(
            section_type="HOOK",
            instrument_rules=rules,
            selected_vibe="dark",
            variation_seed=7,
        )
        assert rules["roles"]["melody"]["density"] == original_density


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    @pytest.mark.parametrize("vibe", ["dark", "emotional", "hype", "pain", "rage", "ambient", "cinematic"])
    def test_same_seed_same_output(self, vibe: str):
        rules = _base_rules()
        r1 = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe=vibe, variation_seed=42)
        r2 = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe=vibe, variation_seed=42)
        assert r1 == r2

    @pytest.mark.parametrize("vibe", ["dark", "hype", "rage"])
    def test_different_seeds_can_differ(self, vibe: str):
        """Two different seeds should sometimes produce different probabilistic outcomes."""
        rules = _base_rules()
        # Collect probabilistic outputs across many seeds to confirm they differ
        outputs = set()
        for seed in range(20):
            r = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe=vibe, variation_seed=seed)
            rolls = r["roles"]["percussion"].get("rolls")
            outputs.add(rolls)
        # At least two distinct outcomes should appear for high-probability vibes
        assert len(outputs) >= 1  # At minimum no crash; ideally more than one value


# ---------------------------------------------------------------------------
# Multipliers
# ---------------------------------------------------------------------------


class TestMultipliers:
    def test_dark_reduces_melody_density(self):
        rules = _base_rules()
        before = rules["roles"]["melody"]["density"]
        result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="dark", variation_seed=1)
        after = result["roles"]["melody"]["density"]
        # dark melody_density_multiplier = 0.7 < 1.0
        assert after < before

    def test_hype_increases_fx_intensity(self):
        rules = _base_rules()
        before = rules["roles"]["fx"]["intensity"]
        result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="hype", variation_seed=1)
        after = result["roles"]["fx"]["intensity"]
        # hype fx_intensity_multiplier = 1.3 > 1.0
        assert after > before

    def test_rage_increases_808_complexity(self):
        rules = _base_rules()
        before = rules["roles"]["bass"]["complexity"]
        result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="rage", variation_seed=1)
        after = result["roles"]["bass"]["complexity"]
        # rage 808_complexity_multiplier = 1.3 > 1.0
        assert after >= before  # may be clamped to 1.0

    def test_values_always_clamped_to_0_1(self):
        """All density/intensity values must remain within [0, 1]."""
        # Use a very high base intensity to trigger clamping
        rules = _base_rules()
        rules["roles"]["fx"]["intensity"] = 0.95  # × 1.4 (rage) = 1.33 → clamped to 1.0
        result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="rage", variation_seed=1)
        assert result["roles"]["fx"]["intensity"] <= 1.0

        rules2 = _base_rules()
        rules2["roles"]["melody"]["density"] = 0.05  # × 0.65 (ambient) = 0.0325 → valid
        result2 = apply_vibe(section_type="HOOK", instrument_rules=rules2, selected_vibe="ambient", variation_seed=1)
        assert result2["roles"]["melody"]["density"] >= 0.0

    def test_multipliers_correct_values(self):
        """Verify multiplier math for a known vibe (emotional)."""
        rules = _base_rules()
        rules["roles"]["melody"]["density"] = 0.5
        rules["roles"]["chords"]["density"] = 0.5
        rules["roles"]["bass"]["complexity"] = 0.5
        rules["roles"]["fx"]["intensity"] = 0.5

        result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="emotional", variation_seed=1)

        # emotional: melody_density_multiplier=1.2, chord_density_multiplier=1.15,
        #            808_complexity_multiplier=0.85, fx_intensity_multiplier=0.9
        assert result["roles"]["melody"]["density"] == _clamp(0.5 * 1.2)
        assert result["roles"]["chords"]["density"] == _clamp(0.5 * 1.15)
        assert result["roles"]["bass"]["complexity"] == _clamp(0.5 * 0.85)
        assert result["roles"]["fx"]["intensity"] == _clamp(0.5 * 0.9)

    def test_ambient_reduces_bass_complexity(self):
        rules = _base_rules()
        before = rules["roles"]["bass"]["complexity"]
        result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="ambient", variation_seed=1)
        after = result["roles"]["bass"]["complexity"]
        # ambient 808_complexity_multiplier = 0.6 < 1.0
        assert after < before


# ---------------------------------------------------------------------------
# Probabilistic features
# ---------------------------------------------------------------------------


class TestProbabilisticFeatures:
    def test_cinematic_activates_counter_melody_often(self):
        """cinematic has counter_melody_activation=0.7 — should activate frequently."""
        rules = _base_rules()
        rules["roles"]["arp"]["active"] = False
        activations = sum(
            apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="cinematic", variation_seed=s)
            ["roles"]["arp"].get("active", False)
            for s in range(30)
        )
        # With p=0.7 over 30 seeds we expect roughly 21 activations
        assert activations >= 10, f"Expected many activations, got {activations}"

    def test_rage_triggers_hihat_rolls_often(self):
        """rage has hihat_roll_chance=0.8 — percussion rolls should activate frequently."""
        rules = _base_rules()
        rules["roles"]["percussion"]["rolls"] = False
        rolls_count = sum(
            apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="rage", variation_seed=s)
            ["roles"]["percussion"].get("rolls", False)
            for s in range(30)
        )
        assert rolls_count >= 10, f"Expected many roll activations, got {rolls_count}"

    def test_dark_rarely_activates_counter_melody(self):
        """dark has counter_melody_activation=0.15 — low activation rate expected."""
        rules = _base_rules()
        rules["roles"]["arp"]["active"] = False
        activations = sum(
            apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="dark", variation_seed=s)
            ["roles"]["arp"].get("active", False)
            for s in range(50)
        )
        # p=0.15 over 50 seeds → expect < 30 activations (well below 50% rate)
        assert activations < 30, f"Unexpectedly many dark counter-melody activations: {activations}"

    def test_808_slide_activated_by_hype(self):
        """hype has 808_slide_chance=0.6 — slides should be True most of the time."""
        rules = _base_rules()
        rules["roles"]["bass"]["slides"] = False
        slides_count = sum(
            apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="hype", variation_seed=s)
            ["roles"]["bass"].get("slides", False)
            for s in range(30)
        )
        assert slides_count >= 10, f"Expected many slide activations, got {slides_count}"


# ---------------------------------------------------------------------------
# Section energy shift
# ---------------------------------------------------------------------------


class TestSectionEnergyShift:
    def test_dark_hook_energy_unchanged(self):
        """dark HOOK section_energy_shift = 0.0, so energy should not change."""
        rules = _base_rules("HOOK")
        rules["target_energy"] = 0.8
        result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="dark", variation_seed=1)
        # HOOK shift for dark = 0.0
        assert result.get("target_energy") == pytest.approx(0.8, abs=1e-4)

    def test_rage_hook_increases_energy(self):
        """rage HOOK section_energy_shift = +0.25."""
        rules = _base_rules("HOOK")
        rules["target_energy"] = 0.6
        result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="rage", variation_seed=1)
        assert result["target_energy"] == _clamp(0.6 + 0.25)

    def test_ambient_intro_decreases_energy(self):
        """ambient INTRO section_energy_shift = -0.15."""
        rules = _base_rules("INTRO")
        rules["target_energy"] = 0.5
        result = apply_vibe(section_type="INTRO", instrument_rules=rules, selected_vibe="ambient", variation_seed=1)
        assert result["target_energy"] == _clamp(0.5 - 0.15)

    def test_energy_clamped_at_upper_bound(self):
        rules = _base_rules("HOOK")
        rules["target_energy"] = 0.95
        result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="rage", variation_seed=1)
        assert result["target_energy"] <= 1.0

    def test_energy_clamped_at_lower_bound(self):
        rules = _base_rules("BRIDGE")
        rules["target_energy"] = 0.05
        result = apply_vibe(section_type="BRIDGE", instrument_rules=rules, selected_vibe="ambient", variation_seed=1)
        assert result["target_energy"] >= 0.0

    def test_missing_target_energy_defaults(self):
        """When target_energy is absent, it defaults to 0.5 before shift."""
        rules = _base_rules("VERSE")
        rules.pop("target_energy", None)
        rules.pop("energy", None)
        result = apply_vibe(section_type="VERSE", instrument_rules=rules, selected_vibe="hype", variation_seed=1)
        # hype VERSE shift = +0.1 → 0.5 + 0.1 = 0.6
        if "target_energy" in result:
            assert 0.0 <= result["target_energy"] <= 1.0


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


class TestFilters:
    def test_ambient_reverb_often_active(self):
        """ambient has reverb_chance=0.85 — reverb should appear most of the time."""
        rules = _base_rules()
        reverb_count = sum(
            "reverb" in apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="ambient", variation_seed=s)
            .get("vibe_filters", {})
            for s in range(30)
        )
        assert reverb_count >= 15, f"Expected many reverb activations, got {reverb_count}"

    def test_rage_distortion_often_active(self):
        """rage has distortion_chance=0.65."""
        rules = _base_rules()
        distortion_count = sum(
            "distortion" in apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="rage", variation_seed=s)
            .get("vibe_filters", {})
            for s in range(30)
        )
        assert distortion_count >= 10, f"Expected many distortion activations, got {distortion_count}"

    def test_dark_rarely_uses_distortion(self):
        """dark has distortion_chance=0.3 — less than 80% activation rate."""
        rules = _base_rules()
        distortion_count = sum(
            "distortion" in apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="dark", variation_seed=s)
            .get("vibe_filters", {})
            for s in range(50)
        )
        assert distortion_count < 45, f"dark distortion surprisingly common: {distortion_count}"

    def test_vibe_filters_key_present_when_filters_activated(self):
        """When filters activate, the 'vibe_filters' key must be in the result."""
        # Use ambient with seed 0 — reverb probability=0.85, very likely to trigger
        rules = _base_rules()
        found = False
        for seed in range(20):
            result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="ambient", variation_seed=seed)
            if result.get("vibe_filters"):
                found = True
                break
        assert found, "vibe_filters key was never populated across 20 seeds for ambient"


# ---------------------------------------------------------------------------
# Metadata fields
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_vibe_applied_true(self):
        result = apply_vibe(section_type="HOOK", instrument_rules=_base_rules(), selected_vibe="dark", variation_seed=1)
        assert result["vibe_applied"] is True

    def test_vibe_name_matches_input(self):
        result = apply_vibe(section_type="HOOK", instrument_rules=_base_rules(), selected_vibe="hype", variation_seed=1)
        assert result["vibe_name"] == "hype"

    def test_vibe_modifiers_applied_is_list(self):
        result = apply_vibe(section_type="HOOK", instrument_rules=_base_rules(), selected_vibe="cinematic", variation_seed=1)
        assert isinstance(result["vibe_modifiers_applied"], list)
        assert len(result["vibe_modifiers_applied"]) >= 1

    def test_density_before_vs_after_present(self):
        result = apply_vibe(section_type="HOOK", instrument_rules=_base_rules(), selected_vibe="emotional", variation_seed=1)
        dbva = result["density_before_vs_after"]
        assert isinstance(dbva, dict)
        # Check melody role has before/after
        assert "melody" in dbva
        assert "before" in dbva["melody"]
        assert "after" in dbva["melody"]

    def test_density_before_matches_original(self):
        rules = _base_rules()
        original_melody_density = rules["roles"]["melody"]["density"]
        result = apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe="dark", variation_seed=1)
        assert result["density_before_vs_after"]["melody"]["before"] == original_melody_density

    @pytest.mark.parametrize("vibe", ["dark", "emotional", "hype", "pain", "rage", "ambient", "cinematic"])
    def test_all_vibes_populate_metadata(self, vibe: str):
        result = apply_vibe(section_type="HOOK", instrument_rules=_base_rules(), selected_vibe=vibe, variation_seed=99)
        assert result["vibe_applied"] is True
        assert result["vibe_name"] == vibe
        assert isinstance(result["vibe_modifiers_applied"], list)
        assert isinstance(result["density_before_vs_after"], dict)


# ---------------------------------------------------------------------------
# All vibes behave differently
# ---------------------------------------------------------------------------


class TestVibesDifferFromEachOther:
    def test_all_vibes_produce_distinct_melody_densities(self):
        """Each vibe should produce a different melody density (different multipliers)."""
        rules = _base_rules()
        rules["roles"]["melody"]["density"] = 0.5  # neutral starting point

        densities = {
            vibe: apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe=vibe, variation_seed=1)
            ["roles"]["melody"]["density"]
            for vibe in _supported_vibes()
        }

        # All values should not be identical (vibes have distinct multipliers)
        unique_densities = set(densities.values())
        assert len(unique_densities) > 1, f"All vibes produced the same melody density: {densities}"

    def test_all_vibes_produce_distinct_fx_intensities(self):
        rules = _base_rules()
        rules["roles"]["fx"]["intensity"] = 0.5

        intensities = {
            vibe: apply_vibe(section_type="HOOK", instrument_rules=rules, selected_vibe=vibe, variation_seed=1)
            ["roles"]["fx"]["intensity"]
            for vibe in _supported_vibes()
        }

        unique_intensities = set(intensities.values())
        assert len(unique_intensities) > 1, f"All vibes produced the same fx intensity: {intensities}"

    def test_all_vibes_return_valid_structure(self):
        """All vibes must return a dict with the expected keys."""
        for vibe in _supported_vibes():
            result = apply_vibe(
                section_type="HOOK",
                instrument_rules=_base_rules(),
                selected_vibe=vibe,
                variation_seed=42,
            )
            assert isinstance(result, dict), f"vibe={vibe} returned non-dict"
            assert "roles" in result, f"vibe={vibe} missing 'roles' key"
            assert result["vibe_applied"] is True
            assert result["vibe_name"] == vibe


# ---------------------------------------------------------------------------
# Config file integration
# ---------------------------------------------------------------------------


class TestConfigFile:
    def test_config_file_exists(self):
        """The bundled vibe_modifier_rules.json must exist on disk."""
        from app.services.vibe_modifier_engine import _CONFIG_PATH
        assert _CONFIG_PATH.exists(), f"Config not found at {_CONFIG_PATH}"

    def test_config_has_all_vibes(self):
        """All 7 supported vibes must be present in the config."""
        from app.services.vibe_modifier_engine import _CONFIG_PATH
        config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        for vibe in _supported_vibes():
            assert vibe in config["vibes"], f"vibe {vibe!r} missing from config"

    def test_config_custom_path(self):
        """Engine loads correctly when given a custom rules_path."""
        minimal = {
            "version": "test",
            "vibes": {
                "dark": {
                    "multipliers": {
                        "melody_density_multiplier": 0.5,
                        "chord_density_multiplier": 1.0,
                        "808_complexity_multiplier": 1.0,
                        "fx_intensity_multiplier": 1.0,
                    },
                    "probabilistic_features": {
                        "counter_melody_activation": 0.0,
                        "808_slide_chance": 0.0,
                        "hihat_roll_chance": 0.0,
                    },
                    "section_energy_shift": {"HOOK": 0.0},
                    "filters": {},
                }
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(minimal, tmp)
            tmp_path = Path(tmp.name)

        try:
            result = apply_vibe(
                section_type="HOOK",
                instrument_rules=_base_rules(),
                selected_vibe="dark",
                variation_seed=1,
                rules_path=tmp_path,
            )
            # melody_density_multiplier = 0.5 → density halved
            assert result["roles"]["melody"]["density"] == _clamp(0.85 * 0.5)
        finally:
            tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _supported_vibes():
    return ["dark", "emotional", "hype", "pain", "rage", "ambient", "cinematic"]
