"""Tests for LoopMetadataAnalyzer: Rule-based genre, mood, and energy detection.

Tests cover:
- Genre detection: trap, dark_trap, melodic_trap, drill, rage
- Mood detection: dark, aggressive, emotional, cinematic, energetic
- Energy calculation from BPM, genre, mood
- Confidence scoring
- Template recommendations
- Instrument suggestions
- Fallback behavior
"""

import pytest
from app.services.loop_metadata_analyzer import LoopMetadataAnalyzer


class TestGenreDetection:
    """Test genre detection from BPM, tags, filename, and hints."""
    
    def test_dark_trap_detection_from_tags(self):
        """Test dark trap detection from genre-specific tags."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["dark", "trap", "evil"],
            filename="loop.wav",
        )
        
        assert result["detected_genre"] == "dark_trap"
        assert result["confidence"] >= 0.5
        assert len(result["suggested_instruments"]) > 0  # Should recommend trap instruments
    
    def test_dark_trap_detection_from_filename(self):
        """Test dark trap detection from filename patterns."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=150.0,
            tags=[],
            filename="dark_trap_loop_150bpm.wav",
        )
        
        assert result["detected_genre"] == "dark_trap"
        assert result["recommended_template"] == "progressive"
    
    def test_melodic_trap_detection_from_keywords(self):
        """Test melodic trap detection from melodic keywords."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=135.0,
            tags=["melodic", "trap", "emotional", "piano"],
            filename="melodic_trap.wav",
        )
        
        assert result["detected_genre"] == "melodic_trap"
        assert "piano" in result["suggested_instruments"] or "melody" in result["suggested_instruments"]
    
    def test_drill_detection_from_bpm_and_tags(self):
        """Test drill detection from BPM range and keywords."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=140.0,
            tags=["drill", "uk drill"],
            filename="drill_loop.wav",
        )
        
        assert result["detected_genre"] == "drill"
        assert result["recommended_template"] == "looped"
        assert "sliding_808" in result["suggested_instruments"] or "808" in result["suggested_instruments"]
    
    def test_rage_detection_from_high_bpm(self):
        """Test rage detection from high BPM and rage keywords."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=165.0,
            tags=["rage", "hyper", "distorted"],
            filename="rage_beat.wav",
        )
        
        assert result["detected_genre"] == "rage"
        assert result["energy_level"] >= 0.7
        assert "distorted_bass" in result["suggested_instruments"] or "synth" in result["suggested_instruments"]
    
    def test_generic_trap_fallback(self):
        """Test fallback to generic trap when no strong genre match."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["beat"],
            filename="loop.wav",
        )
        
        assert result["detected_genre"] == "trap"
        assert result["confidence"] <= 0.5  # Low confidence fallback
    
    def test_genre_hint_overrides(self):
        """Test that explicit genre hint takes priority."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["melodic"],
            filename="melodic_loop.wav",
            genre_hint="dark_trap",
        )
        
        assert result["detected_genre"] == "dark_trap"
        assert result["confidence"] >= 0.9  # High confidence from explicit hint


class TestMoodDetection:
    """Test mood detection from keywords, tags, and genre associations."""
    
    def test_dark_mood_from_keywords(self):
        """Test dark mood detection from keywords."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["dark", "sinister"],
            filename="dark_loop.wav",
            mood_keywords=["dark", "evil"],
        )
        
        assert result["detected_mood"] == "dark"
    
    def test_aggressive_mood_from_tags(self):
        """Test aggressive mood detection from tags."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=150.0,
            tags=["aggressive", "hard", "intense"],
            filename="hard_drill.wav",
        )
        
        assert result["detected_mood"] == "aggressive"
    
    def test_emotional_mood_from_melodic_trap(self):
        """Test emotional mood boost for melodic trap genre."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=130.0,
            tags=["melodic", "trap", "sad"],
            filename="melodic_trap_emotional.wav",
            mood_keywords=["emotional"],
        )
        
        assert result["detected_genre"] == "melodic_trap"
        assert result["detected_mood"] == "emotional"
    
    def test_energetic_mood_from_rage(self):
        """Test energetic mood association with rage genre."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=165.0,
            tags=["rage", "hyper"],
            filename="rage_beat.wav",
        )
        
        # Rage genre should boost aggressive and energetic moods
        assert result["detected_mood"] in ["aggressive", "energetic", "dark"]
    
    def test_mood_fallback_to_dark(self):
        """Test fallback to dark mood when no strong mood match."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["trap"],
            filename="loop.wav",
        )
        
        assert result["detected_mood"] == "dark"  # Default fallback


class TestEnergyCalculation:
    """Test energy level calculation from BPM, genre, and mood."""
    
    def test_energy_increases_with_bpm(self):
        """Test that energy increases with higher BPM."""
        result_low = LoopMetadataAnalyzer.analyze(bpm=100.0, tags=["trap"])
        result_high = LoopMetadataAnalyzer.analyze(bpm=170.0, tags=["trap"])
        
        assert result_high["energy_level"] > result_low["energy_level"]
    
    def test_rage_genre_boosts_energy(self):
        """Test that rage genre increases energy level."""
        result_trap = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["trap"],
        )
        result_rage = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["rage", "hyper"],
        )
        
        assert result_rage["energy_level"] > result_trap["energy_level"]
    
    def test_melodic_trap_reduces_energy(self):
        """Test that melodic trap has lower energy than standard trap."""
        result_trap = LoopMetadataAnalyzer.analyze(
            bpm=140.0,
            tags=["trap"],
        )
        result_melodic = LoopMetadataAnalyzer.analyze(
            bpm=140.0,
            tags=["melodic", "trap", "piano"],
        )
        
        assert result_melodic["energy_level"] < result_trap["energy_level"]
    
    def test_energy_bounds(self):
        """Test that energy level is clamped between 0.0 and 1.0."""
        result_extreme_low = LoopMetadataAnalyzer.analyze(bpm=60.0)
        result_extreme_high = LoopMetadataAnalyzer.analyze(bpm=200.0)
        
        assert 0.0 <= result_extreme_low["energy_level"] <= 1.0
        assert 0.0 <= result_extreme_high["energy_level"] <= 1.0
    
    def test_aggressive_mood_boosts_energy(self):
        """Test that aggressive mood increases energy."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["trap", "aggressive", "hard"],
            mood_keywords=["aggressive"],
        )
        
        assert result["energy_level"] >= 0.65


class TestTemplateRecommendations:
    """Test template recommendations based on genre."""
    
    def test_dark_trap_progressive_template(self):
        """Test that dark trap gets progressive template."""
        result = LoopMetadataAnalyzer.analyze(
            tags=["dark", "trap"],
            genre_hint="dark_trap",
        )
        
        assert result["recommended_template"] == "progressive"
    
    def test_drill_looped_template(self):
        """Test that drill gets looped template."""
        result = LoopMetadataAnalyzer.analyze(
            tags=["drill"],
            genre_hint="drill",
        )
        
        assert result["recommended_template"] == "looped"
    
    def test_trap_standard_template(self):
        """Test that standard trap gets standard template."""
        result = LoopMetadataAnalyzer.analyze(
            tags=["trap"],
            genre_hint="trap",
        )
        
        assert result["recommended_template"] == "standard"


class TestInstrumentRecommendations:
    """Test instrument recommendations based on genre and mood."""
    
    def test_trap_instruments(self):
        """Test basic trap instrument recommendations."""
        result = LoopMetadataAnalyzer.analyze(
            tags=["trap"],
            genre_hint="trap",
        )
        
        instruments = result["suggested_instruments"]
        assert "kick" in instruments
        assert "snare" in instruments
        assert "hats" in instruments
        assert "808_bass" in instruments or "bass" in instruments
    
    def test_melodic_trap_includes_melodic_instruments(self):
        """Test that melodic trap includes piano, strings, etc."""
        result = LoopMetadataAnalyzer.analyze(
            tags=["melodic", "trap"],
            genre_hint="melodic_trap",
        )
        
        instruments = result["suggested_instruments"]
        melodic_instruments = ["piano", "pad", "strings", "melody"]
        assert any(instr in instruments for instr in melodic_instruments)
    
    def test_rage_includes_distorted_instruments(self):
        """Test that rage includes distorted/glitch instruments."""
        result = LoopMetadataAnalyzer.analyze(
            tags=["rage", "hyper"],
            genre_hint="rage",
        )
        
        instruments = result["suggested_instruments"]
        assert "distorted_bass" in instruments or "synth" in instruments
        assert "glitch_fx" in instruments or "fx" in instruments


class TestConfidenceScoring:
    """Test confidence scoring based on signal strength."""
    
    def test_high_confidence_with_multiple_signals(self):
        """Test high confidence when multiple signals match."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["dark", "trap", "evil", "sinister"],
            filename="dark_trap_145bpm.wav",
            mood_keywords=["dark", "aggressive"],
        )
        
        assert result["confidence"] >= 0.7
    
    def test_low_confidence_with_weak_signals(self):
        """Test low confidence with minimal or weak signals."""
        result = LoopMetadataAnalyzer.analyze(
            tags=["beat"],
            filename="loop.wav",
        )
        
        assert result["confidence"] <= 0.5
    
    def test_genre_hint_provides_high_confidence(self):
        """Test that explicit genre hint gives high confidence."""
        result = LoopMetadataAnalyzer.analyze(
            genre_hint="dark_trap",
        )
        
        # Genre confidence from hint is 0.95, overall should be high
        assert result["confidence"] >= 0.6


class TestReasoningGeneration:
    """Test reasoning string generation for explainability."""
    
    def test_reasoning_includes_detected_genre(self):
        """Test that reasoning explains genre detection."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["dark", "trap"],
            genre_hint="dark_trap",
        )
        
        reasoning = result["reasoning"]
        assert reasoning is not None
        assert "dark_trap" in reasoning
    
    def test_reasoning_includes_bpm_range(self):
        """Test that reasoning mentions BPM range matching."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["dark", "trap"],
            filename="dark_trap.wav",
        )
        
        reasoning = result["reasoning"]
        assert "BPM" in reasoning or "bpm" in reasoning
    
    def test_reasoning_includes_mood_keywords(self):
        """Test that reasoning mentions mood keywords."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["trap"],
            mood_keywords=["dark", "aggressive"],
        )
        
        reasoning = result["reasoning"]
        assert "mood" in reasoning.lower()


class TestSourceSignals:
    """Test source signals tracking for debugging."""
    
    def test_source_signals_tracks_bpm(self):
        """Test that source signals capture BPM data."""
        result = LoopMetadataAnalyzer.analyze(bpm=145.0)
        
        signals = result["source_signals"]
        assert signals["bpm_provided"] is True
        assert signals["bpm_value"] == 145.0
    
    def test_source_signals_tracks_tags(self):
        """Test that source signals capture tag data."""
        result = LoopMetadataAnalyzer.analyze(tags=["dark", "trap"])
        
        signals = result["source_signals"]
        assert signals["tag_count"] == 2
        assert "dark" in signals["tags"]
        assert "trap" in signals["tags"]
    
    def test_source_signals_tracks_genre_match(self):
        """Test that source signals track successful genre matches."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["dark", "trap"],
        )
        
        signals = result["source_signals"]
        assert "genre_bpm_match" in signals
        assert "genre_tag_matches" in signals


class TestAnalysisVersion:
    """Test analysis version tracking for schema evolution."""
    
    def test_analysis_version_present(self):
        """Test that analysis includes version number."""
        result = LoopMetadataAnalyzer.analyze()
        
        assert "analysis_version" in result
        assert result["analysis_version"] == "1.0.0"


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_inputs(self):
        """Test analyzer handles empty inputs gracefully."""
        result = LoopMetadataAnalyzer.analyze()
        
        # Should fallback to defaults
        assert result["detected_genre"] in ["trap", "generic"]
        assert result["detected_mood"] == "dark"
        assert 0.0 <= result["energy_level"] <= 1.0
    
    def test_none_values(self):
        """Test analyzer handles None values properly."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=None,
            tags=None,
            filename=None,
            mood_keywords=None,
            genre_hint=None,
        )
        
        # Should work without errors
        assert result["detected_genre"] is not None
        assert result["detected_mood"] is not None
    
    def test_extreme_bpm_values(self):
        """Test analyzer handles extreme BPM values."""
        result_low = LoopMetadataAnalyzer.analyze(bpm=60.0)
        result_high = LoopMetadataAnalyzer.analyze(bpm=200.0)
        
        # Both should produce valid results
        assert result_low["energy_level"] >= 0.0
        assert result_high["energy_level"] <= 1.0
    
    def test_mixed_case_tags(self):
        """Test that tags are normalized to lowercase."""
        result = LoopMetadataAnalyzer.analyze(
            tags=["DARK", "Trap", "EVIL"],
            genre_hint="DARK_TRAP",
        )
        
        # Should still match despite case differences
        assert result["detected_genre"] == "dark_trap"
    
    def test_special_characters_in_filename(self):
        """Test filename matching with special characters."""
        result = LoopMetadataAnalyzer.analyze(
            filename="[DARK_TRAP]_Evil_Loop_145BPM_@producer.wav",
            bpm=145.0,
        )
        
        # Should still detect dark_trap from filename
        assert result["detected_genre"] == "dark_trap"


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""
    
    def test_minimal_metadata_trap_beat(self):
        """Test analysis with minimal metadata (just BPM)."""
        result = LoopMetadataAnalyzer.analyze(bpm=140.0)
        
        assert result["detected_genre"] == "trap"
        assert result["energy_level"] > 0.5
        assert len(result["suggested_instruments"]) > 0
    
    def test_rich_metadata_dark_trap(self):
        """Test analysis with rich, complete metadata."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["dark", "trap", "evil", "sinister", "808"],
            filename="dark_trap_evil_145bpm_Am.wav",
            mood_keywords=["dark", "aggressive"],
            bars=4,
            musical_key="Am",
        )
        
        assert result["detected_genre"] == "dark_trap"
        assert result["detected_mood"] == "dark"
        assert result["confidence"] >= 0.7
        assert result["energy_level"] >= 0.6
    
    def test_ambiguous_metadata_fallback(self):
        """Test fallback behavior with ambiguous metadata."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["dark", "melodic"],  # Conflicting signals
            filename="loop.wav",
        )
        
        # Should choose one genre and provide reasoning
        assert result["detected_genre"] in ["dark_trap", "melodic_trap", "trap"]
        assert result["reasoning"] is not None
    
    def test_producer_engine_integration(self):
        """Test output format suitable for ProducerEngine."""
        result = LoopMetadataAnalyzer.analyze(
            bpm=145.0,
            tags=["dark", "trap"],
        )
        
        # Verify all required fields for ProducerEngine
        assert "detected_genre" in result
        assert "detected_mood" in result
        assert "energy_level" in result
        assert "recommended_template" in result
        assert "suggested_instruments" in result
        
        # Verify valid values
        assert result["detected_genre"] in ["trap", "dark_trap", "melodic_trap", "drill", "rage"]
        assert result["recommended_template"] in ["standard", "progressive", "looped", "minimal"]
        assert 0.0 <= result["energy_level"] <= 1.0
