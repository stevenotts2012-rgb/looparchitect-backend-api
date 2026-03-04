"""Tests for pattern generation integration in arrangement engine."""
import pytest
from unittest.mock import patch
from pydub import AudioSegment
from pydub.generators import Sine

from app.services.arrangement_engine import render_phase_b_arrangement


@pytest.fixture
def sample_loop_audio():
    """Create a simple test audio segment."""
    return Sine(440).to_audio_segment(duration=1000)  # 1 second


def test_render_with_seed_and_pattern_generation_disabled(sample_loop_audio):
    """Test that rendering works with seed but pattern generation disabled."""
    with patch("app.services.arrangement_engine.settings") as mock_settings:
        mock_settings.feature_pattern_generation = False
        
        arranged, timeline = render_phase_b_arrangement(
            loop_audio=sample_loop_audio,
            bpm=120.0,
            target_seconds=8,
            seed=42,
        )
        
        assert isinstance(arranged, AudioSegment)
        assert len(arranged) > 0
        assert isinstance(timeline, str)


def test_render_with_seed_and_pattern_generation_enabled(sample_loop_audio):
    """Test that rendering adds patterns when feature is enabled."""
    with patch("app.services.arrangement_engine.settings") as mock_settings:
        mock_settings.feature_style_engine = True
        mock_settings.feature_pattern_generation = True
        
        arranged, timeline = render_phase_b_arrangement(
            loop_audio=sample_loop_audio,
            bpm=120.0,
            target_seconds=8,
            seed=42,
        )
        
        assert isinstance(arranged, AudioSegment)
        assert len(arranged) > 0
        # Audio should be longer than a few bars
        assert len(arranged) > 2000


def test_render_with_sections_and_seed(sample_loop_audio):
    """Test rendering with section override and seed for pattern generation."""
    sections = [
        {"name": "Intro", "bars": 4, "energy": 0.3, "start_bar": 0, "end_bar": 3},
        {"name": "Hook", "bars": 4, "energy": 0.8, "start_bar": 4, "end_bar": 7},
    ]
    
    with patch("app.services.arrangement_engine.settings") as mock_settings:
        mock_settings.feature_style_engine = True
        mock_settings.feature_pattern_generation = True
        
        arranged, timeline = render_phase_b_arrangement(
            loop_audio=sample_loop_audio,
            bpm=120.0,
            target_seconds=16,
            sections_override=sections,
            seed=999,
        )
        
        assert isinstance(arranged, AudioSegment)
        assert len(arranged) > 0


def test_render_determinism_with_seed(sample_loop_audio):
    """Test that rendering with same seed produces identical results."""
    with patch("app.services.arrangement_engine.settings") as mock_settings:
        mock_settings.feature_style_engine = True
        mock_settings.feature_pattern_generation = True
        
        # First render
        arranged1, timeline1 = render_phase_b_arrangement(
            loop_audio=sample_loop_audio,
            bpm=120.0,
            target_seconds=8,
            seed=777,
        )
        
        # Second render with same seed
        arranged2, timeline2 = render_phase_b_arrangement(
            loop_audio=sample_loop_audio,
            bpm=120.0,
            target_seconds=8,
            seed=777,
        )
        
        # Results should be identical
        assert len(arranged1) == len(arranged2)
        assert timeline1 == timeline2


def test_render_without_seed_no_patterns(sample_loop_audio):
    """Test that no patterns are generated when seed is not provided."""
    with patch("app.services.arrangement_engine.settings") as mock_settings:
        mock_settings.feature_pattern_generation = True
        
        arranged, timeline = render_phase_b_arrangement(
            loop_audio=sample_loop_audio,
            bpm=120.0,
            target_seconds=8,
            seed=None,
        )
        
        assert isinstance(arranged, AudioSegment)
        assert len(arranged) > 0


def test_render_with_different_root_notes(sample_loop_audio):
    """Test rendering with different root notes for pattern generation."""
    with patch("app.services.arrangement_engine.settings") as mock_settings:
        mock_settings.feature_style_engine = True
        mock_settings.feature_pattern_generation = True
        
        # Render with C3 (MIDI 48)
        arranged_c, _ = render_phase_b_arrangement(
            loop_audio=sample_loop_audio,
            bpm=120.0,
            target_seconds=8,
            seed=123,
            root_note=48,
        )
        
        # Render with G2 (MIDI 43)
        arranged_g, _ = render_phase_b_arrangement(
            loop_audio=sample_loop_audio,
            bpm=120.0,
            target_seconds=8,
            seed=123,
            root_note=43,
        )
        
        # Both should produce valid audio
        assert isinstance(arranged_c, AudioSegment)
        assert isinstance(arranged_g, AudioSegment)
        assert len(arranged_c) == len(arranged_g)


def test_render_with_varying_section_types(sample_loop_audio):
    """Test that different section types get appropriate pattern density."""
    sections = [
        {"name": "Intro", "bars": 2, "energy": 0.3, "start_bar": 0, "end_bar": 1},
        {"name": "Verse", "bars": 2, "energy": 0.6, "start_bar": 2, "end_bar": 3},
        {"name": "Hook", "bars": 2, "energy": 0.8, "start_bar": 4, "end_bar": 5},
        {"name": "Bridge", "bars": 2, "energy": 0.5, "start_bar": 6, "end_bar": 7},
        {"name": "Outro", "bars": 2, "energy": 0.2, "start_bar": 8, "end_bar": 9},
    ]
    
    with patch("app.services.arrangement_engine.settings") as mock_settings:
        mock_settings.feature_style_engine = True
        mock_settings.feature_pattern_generation = True
        
        arranged, timeline = render_phase_b_arrangement(
            loop_audio=sample_loop_audio,
            bpm=120.0,
            target_seconds=20,
            sections_override=sections,
            seed=456,
        )
        
        assert isinstance(arranged, AudioSegment)
        assert len(arranged) > 0
        # Should be roughly 20 seconds (allow some tolerance)
        assert abs(len(arranged) - 20000) < 2000
