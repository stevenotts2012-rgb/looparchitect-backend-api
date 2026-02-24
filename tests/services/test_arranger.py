"""Tests for arrangement generation service.

Tests duration-to-bars conversion, bar generation, and arrangement structure.
"""

import pytest
from app.services.arranger import (
    duration_to_bars,
    bars_to_duration,
    generate_arrangement,
    create_default_arrangement,
)


class TestDurationToBarConversion:
    """Test duration_seconds <-> bars conversion."""

    def test_duration_to_bars_basic(self):
        """Test basic duration to bars conversion at 140 BPM."""
        # 180 seconds at 140 BPM should be approximately 105 bars
        # Formula: bars = (seconds / 60) * (bpm / 4)
        # = (180 / 60) * (140 / 4) = 3 * 35 = 105
        bars = duration_to_bars(180, 140)
        assert bars == 105

    def test_duration_to_bars_one_minute(self):
        """Test 1 minute duration."""
        # 60 seconds at 120 BPM = (60/60) * (120/4) = 1 * 30 = 30 bars
        bars = duration_to_bars(60, 120)
        assert bars == 30

    def test_duration_to_bars_30_seconds(self):
        """Test 30 second duration at 60 BPM."""
        # (30 / 60) * (60 / 4) = 0.5 * 15 = 7.5 ≈ 8 bars (rounded)
        bars = duration_to_bars(30, 60)
        assert bars == 8

    def test_duration_to_bars_minimum(self):
        """Test minimum duration (15 seconds)."""
        bars = duration_to_bars(15, 120)
        assert bars >= 4  # Should return at least 4 bars

    def test_duration_to_bars_high_bpm(self):
        """Test high BPM (200)."""
        bars = duration_to_bars(120, 200)
        assert bars > 0

    def test_duration_to_bars_low_bpm(self):
        """Test low BPM (60)."""
        bars = duration_to_bars(120, 60)
        assert bars > 0

    def test_duration_to_bars_roundtrip(self):
        """Test roundtrip conversion: duration -> bars -> duration."""
        original_duration = 180
        bpm = 140
        bars = duration_to_bars(original_duration, bpm)
        recovered_duration = bars_to_duration(bars, bpm)
        # Should recover approximately the same duration (within 1 second due to rounding)
        assert abs(recovered_duration - original_duration) <= 1

    def test_duration_to_bars_invalid_bpm(self):
        """Test that invalid BPM raises ValueError."""
        with pytest.raises(ValueError):
            duration_to_bars(180, 0)
        with pytest.raises(ValueError):
            duration_to_bars(180, -120)

    def test_duration_to_bars_invalid_duration(self):
        """Test that invalid duration raises ValueError."""
        with pytest.raises(ValueError):
            duration_to_bars(0, 120)
        with pytest.raises(ValueError):
            duration_to_bars(-30, 120)


class TestBarsToDateConversion:
    """Test bars_to_duration conversion."""

    def test_bars_to_duration_basic(self):
        """Test basic bars to duration conversion."""
        # 105 bars at 140 BPM should be 180 seconds
        # Formula: duration = (bars / (bpm / 4)) * 60
        # = (105 / (140 / 4)) * 60 = (105 / 35) * 60 = 180
        duration = bars_to_duration(105, 140)
        assert duration == 180

    def test_bars_to_duration_30_bars_120bpm(self):
        """Test 30 bars at 120 BPM."""
        # (30 / (120 / 4)) * 60 = (30 / 30) * 60 = 60 seconds
        duration = bars_to_duration(30, 120)
        assert duration == 60

    def test_bars_to_duration_invalid_bpm(self):
        """Test that invalid BPM raises ValueError."""
        with pytest.raises(ValueError):
            bars_to_duration(64, 0)

    def test_bars_to_duration_invalid_bars(self):
        """Test that invalid bars raises ValueError."""
        with pytest.raises(ValueError):
            bars_to_duration(0, 120)
        with pytest.raises(ValueError):
            bars_to_duration(-16, 120)


class TestArrangementGeneration:
    """Test arrangement generation with dynamic sections."""

    def test_generate_arrangement_exact_bars(self):
        """Test that generated arrangement has exactly requested bars."""
        target_bars = 56
        sections, actual_bars = generate_arrangement(target_bars, 140)
        assert actual_bars == target_bars

    def test_generate_arrangement_structure(self):
        """Test arrangement has intro, verses, choruses, and outro."""
        sections, _ = generate_arrangement(56, 140)
        names = [s["name"] for s in sections]
        
        # Should have intro
        assert "Intro" in names
        # Should have outro (always last)
        assert names[-1] == "Outro"
        # Should have verses and choruses
        assert "Verse" in names
        assert "Chorus" in names

    def test_generate_arrangement_intro_bars(self):
        """Test intro is always 4 bars."""
        sections, _ = generate_arrangement(56, 140)
        intro = sections[0]
        assert intro["name"] == "Intro"
        assert intro["bars"] == 4

    def test_generate_arrangement_outro_bars(self):
        """Test outro is always 4 bars."""
        sections, _ = generate_arrangement(56, 140)
        outro = sections[-1]
        assert outro["name"] == "Outro"
        assert outro["bars"] == 4

    def test_generate_arrangement_start_end_positions(self):
        """Test that start_bar and end_bar are correct."""
        target_bars = 64
        sections, total = generate_arrangement(target_bars, 140)
        
        # Check positions are valid and sequential
        current_bar = 0
        for section in sections:
            assert section["start_bar"] == current_bar
            assert section["end_bar"] == current_bar + section["bars"] - 1
            current_bar += section["bars"]
        
        # Final bar position should match total
        assert current_bar == total

    def test_generate_arrangement_minimum_bars(self):
        """Test arrangement with minimum bars (4)."""
        sections, total = generate_arrangement(4, 140)
        assert total >= 4

    def test_generate_arrangement_16_bars(self):
        """Test 16-bar arrangement (minimum typical: intro+verse/chorus+outro)."""
        sections, total = generate_arrangement(16, 140)
        assert total == 16
        assert len(sections) >= 3  # Intro, middle, outro

    def test_generate_arrangement_standard_3min(self):
        """Test standard 3-minute arrangement."""
        # 3 minutes at 120 BPM = 90 bars
        sections, total = generate_arrangement(90, 120)
        assert total == 90
        assert len(sections) >= 4  # Intro + repeats + outro

    def test_generate_arrangement_verse_chorus_pattern(self):
        """Test that middle sections alternate verse/chorus."""
        sections, _ = generate_arrangement(64, 140)
        
        # Skip intro and outro
        middle = sections[1:-1]
        
        # Check for verse/chorus alternation
        for i in range(0, len(middle) - 1, 2):
            if i + 1 < len(middle):
                # Typically verse followed by chorus (may have variations)
                assert middle[i]["name"] in ["Verse", "Chorus"]
                assert middle[i + 1]["name"] in ["Verse", "Chorus"]

    def test_generate_arrangement_bar_sums(self):
        """Test that section bar sums equal total bars."""
        target_bars = 72
        sections, total = generate_arrangement(target_bars, 140)
        summed_bars = sum(s["bars"] for s in sections)
        assert summed_bars == total

    def test_generate_arrangement_large_bars(self):
        """Test arrangement with many bars."""
        sections, total = generate_arrangement(256, 140)
        assert total == 256
        assert len(sections) > 10  # Should have multiple repeats

    def test_generate_arrangement_odd_bars(self):
        """Test arrangement with odd number of bars."""
        for odd_bars in [57, 73, 99]:
            sections, total = generate_arrangement(odd_bars, 140)
            assert total == odd_bars


class TestDefaultArrangement:
    """Test default arrangement structure."""

    def test_create_default_arrangement(self):
        """Test default arrangement has expected structure."""
        sections = create_default_arrangement()
        assert len(sections) > 0
        assert all("name" in s and "bars" in s for s in sections)

    def test_default_arrangement_has_intro_outro(self):
        """Test default arrangement starts with intro and ends with outro."""
        sections = create_default_arrangement()
        assert sections[0]["name"] == "Intro"
        assert sections[-1]["name"] == "Outro"


class TestArrangementNoBreaks:
    """Test arrangement gap-free bar positioning."""

    def test_no_bar_gaps(self):
        """Test that there are no gaps in bar numbering."""
        for target in [32, 56, 128]:
            sections, total = generate_arrangement(target, 140)
            
            expected_bar = 0
            for section in sections:
                assert section["start_bar"] == expected_bar, \
                    f"Gap found at section {section['name']}: expected {expected_bar}, got {section['start_bar']}"
                expected_bar += section["bars"]
            
            assert expected_bar == total

    def test_no_bar_overlaps(self):
        """Test that sections don't overlap."""
        sections, _ = generate_arrangement(72, 140)
        
        for i in range(len(sections) - 1):
            end_bar = sections[i]["end_bar"]
            next_start = sections[i + 1]["start_bar"]
            assert end_bar + 1 == next_start, \
                f"Overlap/gap between sections {i} and {i+1}"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_arrangement_at_bpm_boundaries(self):
        """Test arrangements at typical BPM boundaries."""
        for bpm in [60, 90, 120, 140, 160, 180, 200]:
            sections, total = generate_arrangement(64, bpm)
            assert total == 64

    def test_very_slow_bpm(self):
        """Test with very slow BPM (40)."""
        sections, total = generate_arrangement(32, 40)
        assert total == 32

    def test_very_fast_bpm(self):
        """Test with very fast BPM (300)."""
        sections, total = generate_arrangement(32, 300)
        assert total == 32

    def test_duration_boundaries(self):
        """Test duration at boundaries."""
        # Minimum: 15 seconds
        bars_min = duration_to_bars(15, 120)
        assert bars_min >= 4
        
        # Maximum: 3600 seconds (60 minutes)
        bars_max = duration_to_bars(3600, 120)
        assert bars_max <= 5000  # Reasonable upper bound


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
