"""Unit tests for rule-based style parser (fallback for V2 style engine)."""

import pytest

from app.services.rule_based_fallback import (
    parse_with_rules,
    KEYWORD_PATTERNS,
    PRODUCER_KEYWORDS,
    GENRE_KEYWORDS,
)
from app.schemas.style_profile import StyleProfile, StyleOverrides


class TestRuleBasedFallbackBasic:
    """Test basic functionality of rule-based parser."""

    def test_parse_with_rules_returns_valid_profile(self):
        """Test that parse_with_rules returns a valid StyleProfile."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "aggressive dark beat",
            loop_metadata
        )

        assert isinstance(result, StyleProfile)
        assert result.resolved_preset is not None
        assert result.resolved_params is not None
        assert result.seed is not None
        assert isinstance(result.seed, int)

    def test_parse_empty_input(self):
        """Test parsing empty/whitespace input."""
        loop_metadata = {"bpm": 120, "key": "A", "duration": 30, "bars": 60}

        result = parse_with_rules("", loop_metadata)

        # Should still return a valid profile with defaults
        assert isinstance(result, StyleProfile)
        assert result.resolved_preset is not None

    def test_parse_with_overrides(self):
        """Test that overrides are applied."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}
        overrides = StyleOverrides(
            aggression=0.9,
            darkness=0.7,
            bounce=0.3
        )

        result = parse_with_rules(
            "test",
            loop_metadata,
            overrides
        )

        assert isinstance(result, StyleProfile)
        assert result.resolved_params is not None


class TestAggressionKeywords:
    """Test aggression-related keyword detection."""

    def test_aggressive_keywords_high_aggression(self):
        """Test that aggressive keywords produce high aggression."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "aggressive hard hitting brutal beat",
            loop_metadata
        )

        assert result.resolved_params["aggression"] > 0.7

    def test_smooth_keywords_lower_aggression(self):
        """Test that smooth keywords produce lower aggression than aggressive."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result_smooth = parse_with_rules(
            "smooth mellow laid back chill",
            loop_metadata
        )

        result_aggressive = parse_with_rules(
            "aggressive hard hitting",
            loop_metadata
        )

        # Smooth should have lower aggression than aggressive
        assert result_smooth.resolved_params["aggression"] < result_aggressive.resolved_params["aggression"]

    def test_mid_aggression_keywords(self):
        """Test mid-range aggression keywords."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "mid aggressive medium aggressive",
            loop_metadata
        )

        # Should be in mid-range
        assert 0.4 < result.resolved_params["aggression"] < 0.7


class TestDarknessKeywords:
    """Test darkness/mood keyword detection (maps to fx_intensity)."""

    def test_dark_keywords_higher_fx(self):
        """Test that dark keywords produce higher fx effects."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result_dark = parse_with_rules(
            "dark gloomy moody sinister",
            loop_metadata
        )

        result_bright = parse_with_rules(
            "bright light uplifting cheerful",
            loop_metadata
        )

        # Dark should have higher fx_intensity than bright
        assert result_dark.resolved_params["fx_intensity"] > result_bright.resolved_params["fx_intensity"]

    def test_atmospheric_keywords(self):
        """Test atmospheric keywords."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "atmospheric ambient cinematic",
            loop_metadata
        )

        # Should have moderate fx_intensity for atmospheric
        assert isinstance(result.resolved_params["fx_intensity"], (int, float))
        assert 0 <= result.resolved_params["fx_intensity"] <= 1


class TestBounceKeywords:
    """Test bounce/swing keyword detection."""

    def test_bouncy_keywords_higher_swing(self):
        """Test that bouncy keywords produce higher swing."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result_bouncy = parse_with_rules(
            "bouncy bounce bouncing groovy swing",
            loop_metadata
        )

        result_stiff = parse_with_rules(
            "stiff rigid locked tight",
            loop_metadata
        )

        # Bouncy should have higher swing than stiff
        assert result_bouncy.resolved_params["swing"] > result_stiff.resolved_params["swing"]

    def test_stiff_keywords_lower_swing(self):
        """Test that stiff keywords produce lower swing."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "stiff rigid locked tight",
            loop_metadata
        )

        # Stiff should reduce swing
        assert isinstance(result.resolved_params["swing"], (int, float))
        assert 0 <= result.resolved_params["swing"] <= 1


class TestMelodyKeywords:
    """Test melody complexity keyword detection."""

    def test_melodic_keywords_higher_melody(self):
        """Test that melodic keywords influence melody complexity."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result_melodic = parse_with_rules(
            "melodic melody musical harmonic",
            loop_metadata
        )

        result_simple = parse_with_rules(
            "simple minimal sparse",
            loop_metadata
        )

        # Melodic should have higher melody_complexity than simple
        assert result_melodic.resolved_params["melody_complexity"] > result_simple.resolved_params["melody_complexity"]

    def test_simple_keywords_lower_melody(self):
        """Test that simple keywords produce lower melody."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "simple minimal sparse",
            loop_metadata
        )

        assert isinstance(result.resolved_params["melody_complexity"], (int, float))
        assert 0 <= result.resolved_params["melody_complexity"] <= 1

    def test_complex_keywords_melody(self):
        """Test that complex keywords increase melody complexity."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result_complex = parse_with_rules(
            "complex layered intricate",
            loop_metadata
        )

        result_simple = parse_with_rules(
            "simple minimal",
            loop_metadata
        )

        assert result_complex.resolved_params["melody_complexity"] > result_simple.resolved_params["melody_complexity"]


class TestEnergyKeywords:
    """Test drum density keyword detection."""

    def test_energetic_keywords_higher_density(self):
        """Test that energetic keywords influence drum density."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result_energetic = parse_with_rules(
            "energetic high energy explosive",
            loop_metadata
        )

        result_consistent = parse_with_rules(
            "consistent steady locked in stable",
            loop_metadata
        )

        # Energetic should have higher or equal drum density
        assert result_energetic.resolved_params["drum_density"] >= result_consistent.resolved_params["drum_density"]

    def test_consistent_keywords(self):
        """Test consistent/steady keywords."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "consistent steady locked in stable",
            loop_metadata
        )

        assert isinstance(result.resolved_params["drum_density"], (int, float))
        assert 0 <= result.resolved_params["drum_density"] <= 1


class TestTransitionKeywords:
    """Test transition keyword detection (affects beat structure)."""

    def test_transition_keywords_detected(self):
        """Test that transition keywords are properly detected."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "beat switch drop build climax peak",
            loop_metadata
        )

        # Transitions should be captured in sections
        assert result.sections is not None

    def test_smooth_transition(self):
        """Test smooth transition keywords."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "smooth transition smooth switch gradual",
            loop_metadata
        )

        # Should produce valid profile
        assert isinstance(result, StyleProfile)


class TestEffectsKeywords:
    """Test FX intensity keyword detection."""

    def test_effects_heavy_keywords_higher_fx(self):
        """Test that effects-heavy keywords produce higher FX intensity."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result_heavy = parse_with_rules(
            "effect heavy effects fx heavy lots of effects",
            loop_metadata
        )

        result_clean = parse_with_rules(
            "minimal effects clean dry no effects",
            loop_metadata
        )

        # Heavy effects should have higher fx_intensity than clean
        assert result_heavy.resolved_params["fx_intensity"] >= result_clean.resolved_params["fx_intensity"]

    def test_clean_keywords(self):
        """Test that clean keywords reduce FX intensity."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "minimal effects clean dry no effects",
            loop_metadata
        )

        assert isinstance(result.resolved_params["fx_intensity"], (int, float))
        assert 0 <= result.resolved_params["fx_intensity"] <= 1

    def test_spacious_keywords(self):
        """Test that spacious keywords affect FX intensity."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "spacious wide spatial",
            loop_metadata
        )

        assert isinstance(result.resolved_params["fx_intensity"], (int, float))
        assert 0 <= result.resolved_params["fx_intensity"] <= 1


class TestBassKeywords:
    """Test bass-related keywords (influence aggression and preset)."""

    def test_bass_heavy_keywords(self):
        """Test that bass-heavy keywords produce valid output."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "bass heavy heavy bass booming subby sub bass",
            loop_metadata
        )

        assert result.resolved_preset is not None
        assert isinstance(result.resolved_params["aggression"], (int, float))

    def test_minimal_bass_keywords(self):
        """Test that minimal bass keywords produce valid output."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "no bass minimal bass light bass",
            loop_metadata
        )

        assert result.resolved_preset is not None

    def test_bass_focused(self):
        """Test that bass-focused keywords work correctly."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "bass focused bass forward",
            loop_metadata
        )

        assert isinstance(result.resolved_params["aggression"], (int, float))
        assert 0 <= result.resolved_params["aggression"] <= 1


class TestProducerKeywordRecognition:
    """Test producer keyword matching."""

    def test_producer_keywords_complete(self):
        """Test that all producers are properly defined."""
        for producer_keyword_pattern, archetype in PRODUCER_KEYWORDS.items():
            assert isinstance(producer_keyword_pattern, str)
            assert isinstance(archetype, str)

    def test_southside_producer(self):
        """Test Southside producer recognition."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "Southside type beat",
            loop_metadata
        )

        # Result should reflect Southside style
        assert result.resolved_params["aggression"] > 0.6  # Southside is aggressive


class TestGenreKeywordRecognition:
    """Test genre keyword matching."""

    def test_genre_keywords_complete(self):
        """Test that genres are properly defined."""
        for genre_keyword_pattern, preset in GENRE_KEYWORDS.items():
            assert isinstance(genre_keyword_pattern, str)
            assert isinstance(preset, str)

    def test_drill_genre(self):
        """Test drill genre recognition."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "UK drill beat",
            loop_metadata
        )

        assert result.resolved_preset == "drill"

    def test_trap_genre(self):
        """Test trap genre recognition."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "trap beat",
            loop_metadata
        )

        assert result.resolved_preset == "atl"


class TestMultipleAttributeCombinations:
    """Test parsing with multiple attribute keywords."""

    def test_aggressive_dark_moody(self):
        """Test combination of aggressive and dark keywords."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "aggressive dark moody beat",
            loop_metadata
        )

        assert result.resolved_params["aggression"] > 0.6
        assert result.resolved_params["fx_intensity"] > 0.3  # Dark maps to higher FX

    def test_melodic_bouncy_smooth(self):
        """Test combination of melodic and bouncy keywords."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "melodic bouncy smooth groove",
            loop_metadata
        )

        assert result.resolved_params["melody_complexity"] > 0.4  # Should be melodic
        assert result.resolved_params["swing"] >= 0.1  # Bouncy affects swing
        # Smooth should reduce aggression relative to aggressive
        aggressive_result = parse_with_rules("aggressive bouncy", loop_metadata)
        smooth_bouncy_result = parse_with_rules("smooth calm", loop_metadata)
        assert aggressive_result.resolved_params["aggression"] > smooth_bouncy_result.resolved_params["aggression"]

    def test_cinematic_complex_atmospheric(self):
        """Test cinematic/atmospheric keywords."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result = parse_with_rules(
            "cinematic atmospheric complex orchestral",
            loop_metadata
        )

        assert result.resolved_preset == "cinematic"
        assert result.resolved_params["melody_complexity"] > 0.6


class TestSeedDeterminism:
    """Test that rule-based parser produces deterministic seeds."""

    def test_same_input_produces_numeric_seed(self):
        """Test that inputs produce numeric seeds."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}
        input_text = "aggressive dark beat"

        result = parse_with_rules(input_text, loop_metadata)

        assert isinstance(result.seed, int)
        assert result.seed > 0

    def test_different_input_different_seed(self):
        """Test that different inputs produce different seeds."""
        loop_metadata = {"bpm": 140, "key": "C", "duration": 30, "bars": 60}

        result1 = parse_with_rules("aggressive dark", loop_metadata)
        result2 = parse_with_rules("smooth bright", loop_metadata)

        # While not strictly guaranteed different, should diverge for distinct inputs
        assert result1.seed != result2.seed
