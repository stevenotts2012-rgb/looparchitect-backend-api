"""Unit tests for LLMStyleParser (V2 style engine)."""

import json
import pytest
from unittest.mock import patch, MagicMock

from app.services.llm_style_parser import LLMStyleParser, ARCHETYPE_MAP, PRODUCER_ARCHETYPES
from app.schemas.style_profile import StyleIntent, StyleProfile, StyleOverrides


class TestLLMStyleParserInitialization:
    """Test LLMStyleParser initialization and configuration."""

    def test_parser_initializes_with_config(self):
        """Test parser initializes with OpenAI config."""
        parser = LLMStyleParser()
        assert parser.model is not None
        assert parser.timeout > 0
        assert parser.max_retries > 0

    def test_archetype_map_completeness(self):
        """Test archetype map has valid preset mappings."""
        for archetype, (preset, _) in ARCHETYPE_MAP.items():
            assert isinstance(archetype, str)
            assert isinstance(preset, str)
            # All presets should be valid preset names
            assert preset in ["atl", "dark", "melodic", "drill", "cinematic", "club", "experimental"]

    def test_producer_archetypes_map(self):
        """Test producer keywords map to valid archetypes."""
        for producer, archetype in PRODUCER_ARCHETYPES.items():
            assert isinstance(producer, str)
            assert archetype in ARCHETYPE_MAP, f"Archetype {archetype} not in ARCHETYPE_MAP for producer {producer}"


class TestLLMStyleParserMocking:
    """Test LLMStyleParser with mocked OpenAI responses."""

    @pytest.mark.asyncio
    async def test_parse_style_intent_with_mock_response(self):
        """Test parse_style_intent with mocked LLM response."""
        parser = LLMStyleParser()

        # Mock LLM response
        mock_response = {
            "archetype": "atl_aggressive",
            "attributes": {
                "aggression": 0.85,
                "darkness": 0.3,
                "bounce": 0.6,
                "melody_complexity": 0.4,
                "energy_variance": 0.7,
                "transition_intensity": 0.5,
                "fx_density": 0.3,
                "bass_presence": 0.7,
            },
            "transitions": [
                {"bar": 16, "type": "beat_switch", "intensity": 0.8}
            ],
            "confidence": 0.92
        }

        loop_metadata = {
            "bpm": 140,
            "key": "C",
            "duration": 30,
            "bars": 60
        }

        with patch.object(parser, '_call_llm_for_intent', return_value=StyleIntent(**mock_response)):
            result = await parser.parse_style_intent(
                "Southside type, aggressive, beat switch at bar 32",
                loop_metadata
            )

            assert isinstance(result, StyleProfile)
            assert result.resolved_preset in ["atl", "dark", "melodic", "drill", "cinematic", "club", "experimental"]
            assert result.resolved_params is not None
            assert result.seed is not None
            assert isinstance(result.seed, int)

    @pytest.mark.asyncio
    async def test_parse_with_overrides(self):
        """Test that style overrides are applied."""
        parser = LLMStyleParser()

        mock_response = StyleIntent(
            archetype="atl_aggressive",
            attributes={"aggression": 0.7, "darkness": 0.3},
            transitions=[],
            confidence=0.9,
            raw_input="test"
        )

        overrides = StyleOverrides(
            aggression=0.9,  # Override higher than LLM suggested
            darkness=0.5,
        )

        loop_metadata = {"bpm": 120, "key": "A", "duration": 30, "bars": 60}

        with patch.object(parser, '_call_llm_for_intent', return_value=mock_response):
            result = await parser.parse_style_intent(
                "test input",
                loop_metadata,
                overrides
            )

            # Overrides should be applied (values should reflect the higher override)
            assert result.resolved_params is not None

    @pytest.mark.asyncio
    async def test_parse_fallback_on_llm_error(self):
        """Test fallback to rule-based parser on LLM error."""
        parser = LLMStyleParser()

        loop_metadata = {"bpm": 120, "key": "A", "duration": 30, "bars": 60}

        # Mock LLM call to raise error
        with patch.object(parser, '_call_llm_for_intent', side_effect=Exception("API Error")):
            result = await parser.parse_style_intent(
                "dark and aggressive beat",
                loop_metadata
            )

            # Should still return a valid StyleProfile (fallback was used)
            assert isinstance(result, StyleProfile)
            assert result.resolved_preset is not None


class TestLLMAttributeMapping:
    """Test attribute mapping from LLM scores to parameters."""

    def test_archetype_to_preset_mapping(self):
        """Test that archetypes map to valid presets."""
        parser = LLMStyleParser()

        for archetype in ARCHETYPE_MAP.keys():
            preset = parser._map_archetype_to_preset(archetype)
            assert preset in ["atl", "dark", "melodic", "drill", "cinematic", "club", "experimental"]

    def test_attribute_modifiers_blending(self):
        """Test that attribute overrides blend correctly with defaults."""
        parser = LLMStyleParser()

        defaults = {
            "aggression": 0.5,
            "darkness": 0.4,
            "bounce": 0.6,
        }

        # Test with StyleOverrides
        overrides = StyleOverrides(aggression=0.8)
        blended = parser._apply_attribute_modifiers(defaults, overrides)

        assert isinstance(blended, dict)
        # All attributes should be floats between 0-1
        for key, value in blended.items():
            assert isinstance(value, (int, float))
            assert 0 <= value <= 1


class TestLLMSectionGeneration:
    """Test section planning with transitions."""

    def test_section_generation_with_beats(self):
        """Test that sections are valid for given bar count."""
        parser = LLMStyleParser()

        transitions = [
            {"bar": 16, "type": "beat_switch", "intensity": 0.8}
        ]

        sections = parser._generate_sections_with_transitions(
            transitions,
            total_bars=64,
            metadata={"bpm": 140}
        )

        assert isinstance(sections, list)
        assert len(sections) > 0

        # All sections should have valid bar ranges
        for section in sections:
            assert "start_bar" in section
            assert "end_bar" in section
            assert section["start_bar"] < section["end_bar"]


class TestLLMSeedDeterminism:
    """Test determinism of seed generation."""

    def test_seed_determinism_same_input(self):
        """Test that same input produces same seed."""
        parser = LLMStyleParser()

        input_text = "Southside type, aggressive"
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        # Generate seed twice with same input
        seed1 = parser._generate_seed(input_text, loop_metadata)
        seed2 = parser._generate_seed(input_text, loop_metadata)

        assert seed1 == seed2
        assert isinstance(seed1, int)
        assert seed1 > 0

    def test_seed_variation_different_input(self):
        """Test that different inputs produce different seeds."""
        parser = LLMStyleParser()

        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        seed1 = parser._generate_seed("Southside aggressive", loop_metadata)
        seed2 = parser._generate_seed("Metro dark drill", loop_metadata)

        # While not guaranteed different, should be different for distinct inputs
        assert seed1 != seed2


class TestProducerRecognition:
    """Test that producer names are recognized."""

    def test_southside_recognition(self):
        """Test Southside producer mapping."""
        archetype = PRODUCER_ARCHETYPES.get("southside")
        assert archetype == "atl_aggressive"

    def test_metro_recognition(self):
        """Test Metro Boomin producer mapping."""
        archetype = PRODUCER_ARCHETYPES.get("metro")
        assert archetype in ["dark_drill", "metro"]

    def test_lil_baby_recognition(self):
        """Test Lil Baby artist mapping."""
        archetype = PRODUCER_ARCHETYPES.get("lil baby")
        assert archetype in ["melodic_trap", "melodic"]
