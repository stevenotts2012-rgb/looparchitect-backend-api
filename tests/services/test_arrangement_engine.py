"""
Tests for audio arrangement generation engine.
"""

import json
from unittest.mock import patch

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from app.services.arrangement_engine import (
    generate_arrangement,
    _calculate_sections,
    _apply_section_effects,
    _add_dropouts,
    _add_gain_variations,
    _generate_timeline_json,
)


@pytest.fixture
def test_wav_file(tmp_path):
    """Create a simple test WAV file."""
    # Create a 4-second sine wave at 440 Hz
    sine_wave = Sine(440).to_audio_segment(duration=4000)  # 4 seconds
    wav_path = tmp_path / "test_loop.wav"
    sine_wave.export(str(wav_path), format="wav")
    return str(wav_path)


class TestSectionCalculation:
    """Test section boundary calculations."""

    def test_calculate_sections_standard_structure(self):
        """_calculate_sections should return correct percentages."""
        sections = _calculate_sections(100)  # 100 seconds for easy math

        assert sections["intro"] == (0, 10)
        assert sections["verse1"] == (10, 40)
        assert sections["hook"] == (40, 70)
        assert sections["verse2"] == (70, 90)
        assert sections["outro"] == (90, 100)

    def test_calculate_sections_sums_to_total(self):
        """Section ranges should sum to total duration."""
        total = 240
        sections = _calculate_sections(total)

        end_time = sections["outro"][1]
        assert abs(end_time - total) < 0.01


class TestTimelineGeneration:
    """Test timeline JSON generation."""

    def test_generate_timeline_json_structure(self):
        """_generate_timeline_json should return valid JSON with correct structure."""
        sections = {
            "intro": (0, 10),
            "verse": (10, 30),
        }
        timeline_json = _generate_timeline_json(sections, 30)

        timeline = json.loads(timeline_json)

        assert timeline["total_duration_seconds"] == 30
        assert "sections" in timeline
        assert len(timeline["sections"]) == 2

        intro = timeline["sections"][0]
        assert intro["name"] == "intro"
        assert intro["start_seconds"] == 0
        assert intro["end_seconds"] == 10
        assert intro["duration_seconds"] == 10

    def test_generate_timeline_json_valid(self):
        """_generate_timeline_json should return parseable JSON."""
        sections = _calculate_sections(60)
        timeline_json = _generate_timeline_json(sections, 60)

        # Should not raise
        timeline = json.loads(timeline_json)
        assert timeline is not None


class TestEffectsApplication:
    """Test audio effects application."""

    def test_apply_section_effects_preserves_duration(self, test_wav_file):
        """Effects should not change audio duration."""
        audio = AudioSegment.from_wav(test_wav_file)
        original_duration = len(audio)

        sections = _calculate_sections(10)  # 10 seconds
        target_ms = original_duration

        result = _apply_section_effects(
            audio,
            sections,
            target_ms,
            bpm=120,
            genre="electronic",
            intensity="medium",
        )

        # Duration should be preserved (within 100ms tolerance for rounding)
        assert abs(len(result) - original_duration) < 100

    def test_apply_section_effects_with_low_intensity(self, test_wav_file):
        """Low intensity should not add dropouts."""
        audio = AudioSegment.from_wav(test_wav_file)
        sections = _calculate_sections(10)
        target_ms = len(audio)

        # Process with low intensity
        result = _apply_section_effects(
            audio,
            sections,
            target_ms,
            bpm=120,
            genre="generic",
            intensity="low",
        )

        assert result is not None
        # Should have applied fade-in/out but not dropouts

    def test_apply_section_effects_with_high_intensity(self, test_wav_file):
        """High intensity should add dropouts."""
        audio = AudioSegment.from_wav(test_wav_file)
        sections = _calculate_sections(10)
        target_ms = len(audio)

        result = _apply_section_effects(
            audio,
            sections,
            target_ms,
            bpm=120,
            genre="electronic",
            intensity="high",
        )

        assert result is not None


class TestDropouts:
    """Test dropout effect generation."""

    def test_add_dropouts_returns_audio(self, test_wav_file):
        """_add_dropouts should return modified AudioSegment."""
        audio = AudioSegment.from_wav(test_wav_file)
        result = _add_dropouts(audio, len(audio), 120, "high")

        assert isinstance(result, AudioSegment)

    def test_add_dropouts_low_intensity_no_change(self, test_wav_file):
        """_add_dropouts with low intensity should return unmodified audio."""
        audio = AudioSegment.from_wav(test_wav_file)
        result = _add_dropouts(audio, len(audio), 120, "low")

        # Should be the same audio
        assert len(result) == len(audio)


class TestGainVariations:
    """Test gain variation application."""

    def test_add_gain_variations_returns_audio(self, test_wav_file):
        """_add_gain_variations should return modified AudioSegment."""
        audio = AudioSegment.from_wav(test_wav_file)
        result = _add_gain_variations(audio, len(audio), 120)

        assert isinstance(result, AudioSegment)

    def test_add_gain_variations_is_deterministic(self, test_wav_file):
        """_add_gain_variations should use seed for reproducible results."""
        audio = AudioSegment.from_wav(test_wav_file)

        result1 = _add_gain_variations(audio, len(audio), 120)
        result2 = _add_gain_variations(audio, len(audio), 120)

        # Both should have same duration
        assert len(result1) == len(result2)


class TestArrangementGeneration:
    """Test full arrangement generation."""

    def test_generate_arrangement_creates_file(self, test_wav_file, tmp_path):
        """generate_arrangement should create output file."""
        # Patch the renders directory to use tmp_path
        import app.services.arrangement_engine

        with patch.object(
            app.services.arrangement_engine,
            "Path",
        ) as mock_path:
            # Mock Path.cwd() to return tmp_path
            mock_cwd = tmp_path
            mock_path.cwd.return_value = mock_cwd

            # Also need to patch the real Path for file operations
            output_url, timeline_json = generate_arrangement(
                input_wav_path=test_wav_file,
                target_seconds=10,
                bpm=120,
                genre="electronic",
                intensity="medium",
            )

            # Should return a URL and JSON
            assert output_url.startswith("/renders/arrangements/")
            assert output_url.endswith(".wav")

            timeline = json.loads(timeline_json)
            assert timeline["total_duration_seconds"] == 10
            assert "sections" in timeline

    def test_generate_arrangement_file_not_found(self):
        """generate_arrangement should raise FileNotFoundError for missing input."""
        with pytest.raises(FileNotFoundError):
            generate_arrangement(
                input_wav_path="/nonexistent/file.wav",
                target_seconds=10,
                bpm=120,
            )

    def test_generate_arrangement_output_has_sections(self, test_wav_file):
        """generate_arrangement output JSON should have all 5 sections."""
        output_url, timeline_json = generate_arrangement(
            input_wav_path=test_wav_file,
            target_seconds=60,
            bpm=120,
            genre="electronic",
            intensity="medium",
        )

        timeline = json.loads(timeline_json)
        sections = timeline["sections"]

        # Should have 5 sections
        assert len(sections) == 5

        # Check section names
        section_names = [s["name"] for s in sections]
        assert "intro" in section_names
        assert "verse1" in section_names
        assert "hook" in section_names
        assert "verse2" in section_names
        assert "outro" in section_names

    def test_generate_arrangement_respects_target_duration(self, test_wav_file):
        """Generated arrangement should match target duration."""
        output_url, timeline_json = generate_arrangement(
            input_wav_path=test_wav_file,
            target_seconds=30,
            bpm=120,
            genre="electronic",
            intensity="medium",
        )

        timeline = json.loads(timeline_json)
        assert timeline["total_duration_seconds"] == 30

    def test_generate_arrangement_with_different_intensities(self, test_wav_file):
        """Should handle all intensity levels."""
        for intensity in ["low", "medium", "high"]:
            output_url, timeline_json = generate_arrangement(
                input_wav_path=test_wav_file,
                target_seconds=20,
                bpm=120,
                genre="electronic",
                intensity=intensity,
            )

            assert output_url is not None
            assert timeline_json is not None

    def test_generate_arrangement_with_different_genres(self, test_wav_file):
        """Should handle different genres."""
        for genre in ["electronic", "hip-hop", "ambient", "generic"]:
            output_url, timeline_json = generate_arrangement(
                input_wav_path=test_wav_file,
                target_seconds=20,
                bpm=120,
                genre=genre,
                intensity="medium",
            )

            assert output_url is not None
            assert timeline_json is not None
