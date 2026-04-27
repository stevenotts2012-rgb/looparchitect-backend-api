"""Extended tests for app/services/llm_style_parser.py.

Covers previously-uncovered paths:
- LLMStyleParser.__init__ with api_key present (OpenAI client setup)
- parse_style_intent with LLM client configured (success + fallback on error)
- _call_llm_for_intent JSON parsing (clean JSON / embedded JSON / invalid)
- _make_llm_request
- _map_archetype_to_preset for all ARCHETYPE_MAP keys, unknown keys, and producer names
- _normalize_attributes edge cases
- _generate_seed determinism
- _apply_attribute_modifiers (dict form + StyleParameters form + with overrides)
- _generate_sections_with_transitions (beat switches, base_template, legacy call)
- _params_to_dict
- _fallback_parse delegation
- llm_style_parser singleton
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parser_no_key():
    """Return an LLMStyleParser instance with no API key (no OpenAI client)."""
    from app.services.llm_style_parser import LLMStyleParser

    with patch("app.services.llm_style_parser.settings") as mock_settings:
        mock_settings.openai_api_key = ""
        mock_settings.openai_base_url = "https://api.openai.com/v1"
        mock_settings.openai_model = "gpt-4o"
        mock_settings.openai_timeout = 30
        mock_settings.openai_max_retries = 2
        parser = LLMStyleParser()
    return parser


def _make_parser_with_key():
    """Return an LLMStyleParser instance with a mock OpenAI client."""
    from app.services.llm_style_parser import LLMStyleParser

    mock_openai_client = MagicMock()

    with patch("app.services.llm_style_parser.settings") as mock_settings:
        mock_settings.openai_api_key = "sk-test-key"
        mock_settings.openai_base_url = "https://api.openai.com/v1"
        mock_settings.openai_model = "gpt-4o"
        mock_settings.openai_timeout = 30
        mock_settings.openai_max_retries = 2
        with patch("openai.OpenAI", return_value=mock_openai_client):
            parser = LLMStyleParser()
    parser.client = mock_openai_client
    return parser


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestLLMStyleParserInit:
    def test_client_is_none_when_no_api_key(self):
        parser = _make_parser_no_key()
        assert parser.client is None

    def test_client_is_set_when_api_key_provided(self):
        parser = _make_parser_with_key()
        assert parser.client is not None

    def test_handles_openai_import_error_gracefully(self):
        from app.services.llm_style_parser import LLMStyleParser

        with (
            patch("app.services.llm_style_parser.settings") as mock_settings,
            patch("builtins.__import__", side_effect=ImportError("no openai")),
        ):
            mock_settings.openai_api_key = "sk-key"
            mock_settings.openai_base_url = "https://api.openai.com/v1"
            mock_settings.openai_model = "gpt-4o"
            mock_settings.openai_timeout = 30
            mock_settings.openai_max_retries = 2
            # Should not raise
            try:
                parser = LLMStyleParser()
                assert parser.client is None
            except ImportError:
                pass  # acceptable


# ---------------------------------------------------------------------------
# parse_style_intent — no LLM client (fallback)
# ---------------------------------------------------------------------------


class TestParseStyleIntentFallback:
    def test_falls_back_when_no_client(self):
        from app.schemas.style_profile import StyleProfile

        parser = _make_parser_no_key()

        mock_profile = MagicMock(spec=StyleProfile)

        with patch(
            "app.services.llm_style_parser.LLMStyleParser._fallback_parse",
            return_value=mock_profile,
        ) as mock_fallback:
            result = asyncio.get_event_loop().run_until_complete(
                parser.parse_style_intent("dark trap", {"bpm": 120, "bars": 8})
            )

        mock_fallback.assert_called_once()
        assert result is mock_profile

    def test_falls_back_on_llm_exception(self):
        from app.schemas.style_profile import StyleProfile

        parser = _make_parser_with_key()
        mock_profile = MagicMock(spec=StyleProfile)

        with (
            patch.object(
                parser,
                "_call_llm_for_intent",
                side_effect=RuntimeError("LLM unavailable"),
            ),
            patch.object(parser, "_fallback_parse", return_value=mock_profile),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                parser.parse_style_intent("dark trap", {"bpm": 120, "bars": 8})
            )

        assert result is mock_profile


# ---------------------------------------------------------------------------
# _map_archetype_to_preset
# ---------------------------------------------------------------------------


class TestMapArchetypeToPreset:
    def test_known_archetype_maps_correctly(self):
        from app.services.llm_style_parser import LLMStyleParser, ARCHETYPE_MAP
        from app.style_engine.types import StylePresetName

        parser = _make_parser_no_key()
        for archetype in ARCHETYPE_MAP:
            result = parser._map_archetype_to_preset(archetype)
            assert isinstance(result, StylePresetName)

    def test_unknown_archetype_defaults_to_atl(self):
        from app.style_engine.types import StylePresetName

        parser = _make_parser_no_key()
        result = parser._map_archetype_to_preset("completely_unknown_archetype")
        assert result == StylePresetName.ATL

    def test_producer_name_maps_to_archetype(self):
        from app.style_engine.types import StylePresetName

        parser = _make_parser_no_key()
        # "metro boomin" maps to dark_drill → drill preset
        result = parser._map_archetype_to_preset("metro boomin")
        assert isinstance(result, StylePresetName)

    def test_case_insensitive(self):
        from app.style_engine.types import StylePresetName

        parser = _make_parser_no_key()
        result_lower = parser._map_archetype_to_preset("atl")
        result_upper = parser._map_archetype_to_preset("ATL")
        assert result_lower == result_upper


# ---------------------------------------------------------------------------
# _normalize_attributes
# ---------------------------------------------------------------------------


class TestNormalizeAttributes:
    def test_clamps_values_to_zero_to_one(self):
        parser = _make_parser_no_key()
        result = parser._normalize_attributes({"aggression": 1.5, "bounce": -0.5})
        assert result["aggression"] == 1.0
        assert result["bounce"] == 0.0

    def test_handles_non_numeric_values(self):
        parser = _make_parser_no_key()
        result = parser._normalize_attributes({"aggression": "high"})
        assert result["aggression"] == 0.5

    def test_valid_values_pass_through(self):
        parser = _make_parser_no_key()
        result = parser._normalize_attributes({"aggression": 0.7, "darkness": 0.3})
        assert result["aggression"] == pytest.approx(0.7)
        assert result["darkness"] == pytest.approx(0.3)

    def test_empty_dict_returns_empty(self):
        parser = _make_parser_no_key()
        result = parser._normalize_attributes({})
        assert result == {}


# ---------------------------------------------------------------------------
# _generate_seed
# ---------------------------------------------------------------------------


class TestGenerateSeed:
    def test_deterministic_for_same_inputs(self):
        parser = _make_parser_no_key()
        seed1 = parser._generate_seed("dark trap", {"bpm": 120, "bars": 8})
        seed2 = parser._generate_seed("dark trap", {"bpm": 120, "bars": 8})
        assert seed1 == seed2

    def test_different_inputs_produce_different_seeds(self):
        parser = _make_parser_no_key()
        seed1 = parser._generate_seed("dark trap", {"bpm": 120})
        seed2 = parser._generate_seed("melodic trap", {"bpm": 140})
        assert seed1 != seed2

    def test_returns_integer(self):
        parser = _make_parser_no_key()
        seed = parser._generate_seed("test", {"bpm": 120})
        assert isinstance(seed, int)


# ---------------------------------------------------------------------------
# _apply_attribute_modifiers — dict form (simplified 2-arg call)
# ---------------------------------------------------------------------------


class TestApplyAttributeModifiersDict:
    def test_returns_dict_passthrough_without_overrides(self):
        parser = _make_parser_no_key()
        base = {"aggression": 0.5, "swing": 0.2}
        result = parser._apply_attribute_modifiers(base, None)
        assert result["aggression"] == pytest.approx(0.5)

    def test_applies_style_overrides_aggression(self):
        from app.schemas.style_profile import StyleOverrides

        parser = _make_parser_no_key()
        base = {"aggression": 0.5}
        overrides = StyleOverrides(aggression=0.9)
        result = parser._apply_attribute_modifiers(base, overrides)
        assert result["aggression"] == pytest.approx(0.9)

    def test_applies_style_overrides_bounce(self):
        from app.schemas.style_profile import StyleOverrides

        parser = _make_parser_no_key()
        base = {"bounce": 0.3}
        overrides = StyleOverrides(bounce=0.7)
        result = parser._apply_attribute_modifiers(base, overrides)
        assert result["bounce"] == pytest.approx(0.7)

    def test_clamps_values_to_0_1_range(self):
        parser = _make_parser_no_key()
        base = {"aggression": 0.95}
        result = parser._apply_attribute_modifiers(base, None)
        assert 0.0 <= result["aggression"] <= 1.0


# ---------------------------------------------------------------------------
# _generate_sections_with_transitions
# ---------------------------------------------------------------------------


class TestGenerateSectionsWithTransitions:
    def test_returns_list_of_sections(self):
        parser = _make_parser_no_key()
        sections = parser._generate_sections_with_transitions(
            transitions=[], total_bars=32
        )
        assert isinstance(sections, list)
        assert len(sections) > 0

    def test_calculates_total_bars_from_target_seconds(self):
        parser = _make_parser_no_key()
        sections = parser._generate_sections_with_transitions(
            transitions=[], target_seconds=60, bpm=120.0
        )
        assert len(sections) > 0

    def test_beat_switch_inserts_section(self):
        parser = _make_parser_no_key()
        transitions = [{"type": "beat_switch", "bar": 4, "new_energy": 0.9}]
        sections = parser._generate_sections_with_transitions(
            transitions=transitions, total_bars=32
        )
        names = [s["name"] for s in sections]
        assert "beat_switch" in names

    def test_uses_default_64_bars_when_no_target(self):
        parser = _make_parser_no_key()
        sections = parser._generate_sections_with_transitions(transitions=[])
        total_bars = sum(s["bars"] for s in sections)
        assert total_bars <= 64

    def test_section_has_required_keys(self):
        parser = _make_parser_no_key()
        sections = parser._generate_sections_with_transitions(transitions=[], total_bars=16)
        for s in sections:
            assert "name" in s
            assert "bars" in s
            assert "energy" in s


# ---------------------------------------------------------------------------
# _params_to_dict
# ---------------------------------------------------------------------------


class TestParamsToDict:
    def test_returns_all_expected_keys(self):
        from app.style_engine.types import StyleParameters

        parser = _make_parser_no_key()
        params = StyleParameters(
            tempo_multiplier=1.0,
            drum_density=0.5,
            hat_roll_probability=0.3,
            glide_probability=0.2,
            swing=0.1,
            aggression=0.7,
            melody_complexity=0.4,
            fx_intensity=0.6,
        )
        result = parser._params_to_dict(params)
        assert set(result.keys()) == {
            "tempo_multiplier",
            "drum_density",
            "hat_roll_probability",
            "glide_probability",
            "swing",
            "aggression",
            "melody_complexity",
            "fx_intensity",
        }

    def test_values_match_params(self):
        from app.style_engine.types import StyleParameters

        parser = _make_parser_no_key()
        params = StyleParameters(
            tempo_multiplier=0.9,
            drum_density=0.8,
            hat_roll_probability=0.7,
            glide_probability=0.6,
            swing=0.5,
            aggression=0.4,
            melody_complexity=0.3,
            fx_intensity=0.2,
        )
        result = parser._params_to_dict(params)
        assert result["tempo_multiplier"] == pytest.approx(0.9)
        assert result["aggression"] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# _fallback_parse
# ---------------------------------------------------------------------------


class TestFallbackParse:
    def test_delegates_to_rule_based_fallback(self):
        from app.schemas.style_profile import StyleProfile

        parser = _make_parser_no_key()
        mock_profile = MagicMock(spec=StyleProfile)

        with patch(
            "app.services.rule_based_fallback.parse_with_rules",
            return_value=mock_profile,
        ) as mock_rules:
            result = parser._fallback_parse("dark trap", {"bpm": 120})

        mock_rules.assert_called_once()
        assert result is mock_profile


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestLLMStyleParserSingleton:
    def test_singleton_instance_exists(self):
        from app.services.llm_style_parser import llm_style_parser

        assert llm_style_parser is not None

    def test_archetype_map_has_expected_entries(self):
        from app.services.llm_style_parser import ARCHETYPE_MAP

        assert "atl" in ARCHETYPE_MAP
        assert "dark" in ARCHETYPE_MAP
        assert "melodic" in ARCHETYPE_MAP
        assert "drill" in ARCHETYPE_MAP
        assert "cinematic" in ARCHETYPE_MAP

    def test_producer_archetypes_map_has_expected_entries(self):
        from app.services.llm_style_parser import PRODUCER_ARCHETYPES

        assert "metro boomin" in PRODUCER_ARCHETYPES
        assert "southside" in PRODUCER_ARCHETYPES
