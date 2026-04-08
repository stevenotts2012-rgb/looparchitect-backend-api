"""Unit tests for the arrangement presets system.

Covers:
- ArrangementPresetConfig and PresetSectionOverride data integrity
- get_preset_config lookup (case-insensitive, unknown values)
- resolve_preset_name fallback to DEFAULT_PRESET
- get_effective_profile integration: preset values override base SectionProfile
- Section density / role priority / transition overrides per preset
- Input normalisation via AudioArrangementGenerateRequest.arrangement_preset validator
"""

from __future__ import annotations

import pytest

from app.services.arrangement_presets import (
    ARRANGEMENT_PRESETS,
    DEFAULT_PRESET,
    VALID_PRESETS,
    ArrangementPresetConfig,
    PresetSectionOverride,
    get_preset_config,
    resolve_preset_name,
)
from app.services.section_identity_engine import (
    SECTION_PROFILES,
    get_effective_profile,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALL_PRESET_NAMES = list(ARRANGEMENT_PRESETS.keys())
_SECTION_TYPES = ["intro", "verse", "pre_hook", "hook", "bridge", "breakdown", "outro"]


# ---------------------------------------------------------------------------
# Preset catalogue integrity
# ---------------------------------------------------------------------------

def test_valid_presets_matches_catalogue() -> None:
    """VALID_PRESETS must exactly match the keys in ARRANGEMENT_PRESETS."""
    assert VALID_PRESETS == frozenset(ARRANGEMENT_PRESETS.keys())


def test_default_preset_in_catalogue() -> None:
    assert DEFAULT_PRESET in ARRANGEMENT_PRESETS


@pytest.mark.parametrize("preset_name", _ALL_PRESET_NAMES)
def test_each_preset_covers_all_section_types(preset_name: str) -> None:
    config = ARRANGEMENT_PRESETS[preset_name]
    missing = set(_SECTION_TYPES) - set(config.section_overrides)
    assert not missing, f"Preset '{preset_name}' is missing overrides for: {missing}"


@pytest.mark.parametrize("preset_name", _ALL_PRESET_NAMES)
def test_density_range_is_valid(preset_name: str) -> None:
    config = ARRANGEMENT_PRESETS[preset_name]
    for section_type, override in config.section_overrides.items():
        if override.density_min is not None and override.density_max is not None:
            assert override.density_min <= override.density_max, (
                f"Preset '{preset_name}' section '{section_type}': "
                f"density_min ({override.density_min}) > density_max ({override.density_max})"
            )


@pytest.mark.parametrize("preset_name", _ALL_PRESET_NAMES)
def test_role_priorities_are_non_empty_tuples(preset_name: str) -> None:
    config = ARRANGEMENT_PRESETS[preset_name]
    for section_type, override in config.section_overrides.items():
        if override.role_priorities is not None:
            assert isinstance(override.role_priorities, tuple), (
                f"Preset '{preset_name}' section '{section_type}': "
                "role_priorities should be a tuple"
            )
            assert len(override.role_priorities) > 0, (
                f"Preset '{preset_name}' section '{section_type}': "
                "role_priorities must not be empty"
            )


# ---------------------------------------------------------------------------
# get_preset_config
# ---------------------------------------------------------------------------

def test_get_preset_config_known_preset() -> None:
    config = get_preset_config("trap")
    assert isinstance(config, ArrangementPresetConfig)
    assert config.name == "trap"


def test_get_preset_config_case_insensitive() -> None:
    assert get_preset_config("CINEMATIC") is get_preset_config("cinematic")
    assert get_preset_config("Drill") is get_preset_config("drill")


def test_get_preset_config_unknown_returns_none() -> None:
    assert get_preset_config("unknown_genre") is None
    assert get_preset_config("") is None


def test_get_preset_config_none_returns_none() -> None:
    assert get_preset_config(None) is None


@pytest.mark.parametrize("preset_name", _ALL_PRESET_NAMES)
def test_get_preset_config_all_presets_resolve(preset_name: str) -> None:
    config = get_preset_config(preset_name)
    assert config is not None
    assert config.name == preset_name


# ---------------------------------------------------------------------------
# resolve_preset_name
# ---------------------------------------------------------------------------

def test_resolve_preset_name_none_returns_default() -> None:
    assert resolve_preset_name(None) == DEFAULT_PRESET


def test_resolve_preset_name_empty_string_returns_default() -> None:
    assert resolve_preset_name("") == DEFAULT_PRESET


def test_resolve_preset_name_unknown_returns_default() -> None:
    assert resolve_preset_name("jazz") == DEFAULT_PRESET
    assert resolve_preset_name("rock_opera") == DEFAULT_PRESET


def test_resolve_preset_name_known_preset() -> None:
    for name in _ALL_PRESET_NAMES:
        assert resolve_preset_name(name) == name


def test_resolve_preset_name_case_insensitive() -> None:
    assert resolve_preset_name("TRAP") == "trap"
    assert resolve_preset_name("Cinematic") == "cinematic"
    assert resolve_preset_name("  Drill  ") == "drill"


# ---------------------------------------------------------------------------
# get_effective_profile - preset overrides are applied
# ---------------------------------------------------------------------------

def test_effective_profile_with_no_preset_returns_base() -> None:
    """Without a preset the base SECTION_PROFILES value is returned unchanged."""
    for section_type in _SECTION_TYPES:
        base = SECTION_PROFILES.get(section_type)
        if base is None:
            continue
        effective = get_effective_profile(section_type, None)
        assert effective.density_min == base.density_min
        assert effective.density_max == base.density_max
        assert effective.role_priorities == base.role_priorities


@pytest.mark.parametrize("preset_name", _ALL_PRESET_NAMES)
def test_effective_profile_applies_density_override(preset_name: str) -> None:
    config = ARRANGEMENT_PRESETS[preset_name]
    for section_type, override in config.section_overrides.items():
        effective = get_effective_profile(section_type, preset_name)
        if override.density_min is not None:
            assert effective.density_min == override.density_min, (
                f"Preset '{preset_name}' section '{section_type}': "
                f"expected density_min={override.density_min}, got {effective.density_min}"
            )
        if override.density_max is not None:
            assert effective.density_max == override.density_max, (
                f"Preset '{preset_name}' section '{section_type}': "
                f"expected density_max={override.density_max}, got {effective.density_max}"
            )


@pytest.mark.parametrize("preset_name", _ALL_PRESET_NAMES)
def test_effective_profile_applies_role_priority_override(preset_name: str) -> None:
    config = ARRANGEMENT_PRESETS[preset_name]
    for section_type, override in config.section_overrides.items():
        if override.role_priorities is None:
            continue
        effective = get_effective_profile(section_type, preset_name)
        assert effective.role_priorities == override.role_priorities, (
            f"Preset '{preset_name}' section '{section_type}': role_priorities mismatch"
        )


def test_effective_profile_unknown_preset_falls_back_to_base() -> None:
    """An unrecognised preset should not raise - it falls back to base profiles."""
    for section_type in _SECTION_TYPES:
        base = SECTION_PROFILES.get(section_type)
        if base is None:
            continue
        effective = get_effective_profile(section_type, "totally_unknown_preset")
        assert effective.density_min == base.density_min
        assert effective.density_max == base.density_max


# ---------------------------------------------------------------------------
# Per-preset semantic assertions
# ---------------------------------------------------------------------------

def test_cinematic_preset_forbids_drums_in_intro() -> None:
    config = ARRANGEMENT_PRESETS["cinematic"]
    intro = config.section_overrides["intro"]
    assert intro.forbidden_roles is not None
    assert "drums" in intro.forbidden_roles
    assert "bass" in intro.forbidden_roles


def test_trap_preset_hook_density_exceeds_verse() -> None:
    config = ARRANGEMENT_PRESETS["trap"]
    verse = config.section_overrides["verse"]
    hook = config.section_overrides["hook"]
    assert hook.density_min >= verse.density_min
    assert hook.density_max >= verse.density_max


def test_drill_preset_verse_density_is_minimal() -> None:
    config = ARRANGEMENT_PRESETS["drill"]
    verse = config.section_overrides["verse"]
    # Drill is deliberately sparse in verses
    assert verse.density_max is not None
    assert verse.density_max <= 3


def test_house_preset_intro_includes_drums() -> None:
    config = ARRANGEMENT_PRESETS["house"]
    intro = config.section_overrides["intro"]
    assert intro.role_priorities is not None
    assert "drums" in intro.role_priorities


def test_afrobeats_preset_percussion_leads_verse() -> None:
    config = ARRANGEMENT_PRESETS["afrobeats"]
    verse = config.section_overrides["verse"]
    assert verse.role_priorities is not None
    assert verse.role_priorities[0] == "percussion"


def test_lofi_preset_bridge_forbids_drums_and_fx() -> None:
    config = ARRANGEMENT_PRESETS["lofi"]
    bridge = config.section_overrides["bridge"]
    assert bridge.forbidden_roles is not None
    assert "drums" in bridge.forbidden_roles
    assert "fx" in bridge.forbidden_roles


# ---------------------------------------------------------------------------
# Schema validator - AudioArrangementGenerateRequest.arrangement_preset
# ---------------------------------------------------------------------------

def test_schema_validator_normalises_unknown_to_default() -> None:
    from app.schemas.arrangement import AudioArrangementGenerateRequest

    req = AudioArrangementGenerateRequest(
        loop_id=1,
        target_seconds=60,
        arrangement_preset="jazz",
    )
    assert req.arrangement_preset == DEFAULT_PRESET


def test_schema_validator_normalises_none_to_default() -> None:
    from app.schemas.arrangement import AudioArrangementGenerateRequest

    req = AudioArrangementGenerateRequest(
        loop_id=1,
        target_seconds=60,
        arrangement_preset=None,
    )
    assert req.arrangement_preset == DEFAULT_PRESET


def test_schema_validator_accepts_valid_presets() -> None:
    from app.schemas.arrangement import AudioArrangementGenerateRequest

    for preset_name in _ALL_PRESET_NAMES:
        req = AudioArrangementGenerateRequest(
            loop_id=1,
            target_seconds=60,
            arrangement_preset=preset_name,
        )
        assert req.arrangement_preset == preset_name


def test_schema_validator_normalises_case() -> None:
    from app.schemas.arrangement import AudioArrangementGenerateRequest

    req = AudioArrangementGenerateRequest(
        loop_id=1,
        target_seconds=60,
        arrangement_preset="CINEMATIC",
    )
    assert req.arrangement_preset == "cinematic"


def test_schema_defaults_to_trap_when_omitted() -> None:
    from app.schemas.arrangement import AudioArrangementGenerateRequest

    req = AudioArrangementGenerateRequest(
        loop_id=1,
        target_seconds=60,
    )
    assert req.arrangement_preset == DEFAULT_PRESET
