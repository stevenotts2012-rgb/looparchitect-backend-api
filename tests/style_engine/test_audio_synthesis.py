"""Tests for audio synthesis module."""
import random
from pydub import AudioSegment

from app.style_engine.drums import generate_drum_pattern
from app.style_engine.bass import generate_bassline
from app.style_engine.melody import generate_melody
from app.style_engine.audio_synthesis import (
    synthesize_drums,
    synthesize_bass,
    synthesize_melody,
)


def test_synthesize_drums():
    """Test drum pattern synthesis produces non-silent audio."""
    rng = random.Random(42)
    pattern = generate_drum_pattern(rng, density=0.7, hat_roll_probability=0.3)
    
    audio = synthesize_drums(pattern, bpm=120.0, bars=1)
    
    assert isinstance(audio, AudioSegment)
    assert len(audio) > 0
    assert len(audio) <= 2000  # ~2 seconds at 120 BPM for 1 bar
    # Check it's not completely silent
    assert audio.dBFS > -60


def test_synthesize_drums_multiple_bars():
    """Test drum synthesis with multiple bars."""
    rng = random.Random(99)
    pattern = generate_drum_pattern(rng, density=0.5, hat_roll_probability=0.2)
    
    audio = synthesize_drums(pattern, bpm=140.0, bars=4)
    
    assert isinstance(audio, AudioSegment)
    # 4 bars: (60000 / 140) * 4 beats/bar * 4 bars
    expected_duration = int((60_000 / 140.0) * 4 * 4)
    assert abs(len(audio) - expected_duration) < 50  # Allow 50ms tolerance


def test_synthesize_bass():
    """Test bassline synthesis produces audio."""
    rng = random.Random(123)
    bass_events = generate_bassline(rng, root_note=48, glide_probability=0.3)
    
    audio = synthesize_bass(bass_events, bpm=120.0, bars=1)
    
    assert isinstance(audio, AudioSegment)
    assert len(audio) > 0
    # Bass should be audible
    assert audio.dBFS > -60


def test_synthesize_bass_different_root():
    """Test bassline with different root note."""
    rng = random.Random(456)
    bass_events = generate_bassline(rng, root_note=36, glide_probability=0.5)
    
    audio_2bars = synthesize_bass(bass_events, bpm=100.0, bars=2)
    
    assert isinstance(audio_2bars, AudioSegment)
    # 2 bars: (60000 / 100) * 4 beats/bar * 2 bars
    expected = int((60_000 / 100.0) * 4 * 2)
    assert abs(len(audio_2bars) - expected) < 50


def test_synthesize_melody():
    """Test melody synthesis produces audio."""
    rng = random.Random(789)
    melody_events = generate_melody(rng, root_note=60, complexity=0.6)
    
    audio = synthesize_melody(melody_events, bpm=120.0, bars=1)
    
    assert isinstance(audio, AudioSegment)
    assert len(audio) > 0
    # Melody should be audible
    assert audio.dBFS > -60


def test_synthesize_melody_high_complexity():
    """Test melody with high complexity."""
    rng = random.Random(321)
    melody_events = generate_melody(rng, root_note=72, complexity=0.9)
    
    audio = synthesize_melody(melody_events, bpm=140.0, bars=2)
    
    assert isinstance(audio, AudioSegment)
    assert len(audio) > 0
    # 2 bars: (60000 / 140) * 4 beats/bar * 2 bars
    expected = int((60_000 / 140.0) * 4 * 2)
    assert abs(len(audio) - expected) < 50


def test_synthesis_determinism():
    """Test that synthesis is deterministic with same seed."""
    seed = 555
    
    # Generate first set
    rng1 = random.Random(seed)
    pattern1 = generate_drum_pattern(rng1, density=0.6, hat_roll_probability=0.2)
    audio1 = synthesize_drums(pattern1, bpm=120.0, bars=2)
    
    # Generate second set with same seed
    rng2 = random.Random(seed)
    pattern2 = generate_drum_pattern(rng2, density=0.6, hat_roll_probability=0.2)
    audio2 = synthesize_drums(pattern2, bpm=120.0, bars=2)
    
    # Patterns should be identical
    assert pattern1 == pattern2
    # Audio should have same length and similar properties
    assert len(audio1) == len(audio2)
    assert abs(audio1.dBFS - audio2.dBFS) < 0.01


def test_all_patterns_together():
    """Test generating all patterns and ensuring they're compatible."""
    rng = random.Random(999)
    
    drums = generate_drum_pattern(rng, density=0.7, hat_roll_probability=0.3)
    bass_events = generate_bassline(rng, root_note=48, glide_probability=0.4)
    melody_events = generate_melody(rng, root_note=60, complexity=0.5)
    
    bpm = 120.0
    bars = 2
    
    drums_audio = synthesize_drums(drums, bpm=bpm, bars=bars)
    bass_audio = synthesize_bass(bass_events, bpm=bpm, bars=bars)
    melody_audio = synthesize_melody(melody_events, bpm=bpm, bars=bars)
    
    # All should have similar durations
    # bars * 4 beats/bar * ms_per_beat
    expected = int((60_000 / bpm) * 4 * bars)
    assert abs(len(drums_audio) - expected) < 100
    assert abs(len(bass_audio) - expected) < 100
    assert abs(len(melody_audio) - expected) < 100
    
    # Should be able to mix them
    mixed = drums_audio.overlay(bass_audio).overlay(melody_audio)
    assert len(mixed) > 0
