"""
Audio synthesis for generated patterns.
Converts abstract pattern data structures into pydub AudioSegments.
"""
from __future__ import annotations

import array
import math
import struct
from pydub import AudioSegment
from pydub.generators import Sine

from app.style_engine.drums import DrumPattern
from app.style_engine.bass import BassEvent
from app.style_engine.melody import MelodyEvent

# ---------------------------------------------------------------------------
# Deterministic noise generation
# ---------------------------------------------------------------------------

# Pre-computed noise tables generated once at import time with fixed seeds.
# Using a fixed seed guarantees that `_generate_snare` and `_generate_hat`
# produce byte-identical output on every call, making `synthesize_drums`
# fully deterministic.  The length (8192 samples) covers all realistic
# drum-hit durations at 44100 Hz (≤ 185 ms).
_NOISE_TABLE_SIZE = 8192


def _build_noise_table(seed: int) -> bytes:
    """Return a table of signed 16-bit PCM noise samples using *seed*."""
    import random
    rng = random.Random(seed)
    samples = array.array("h", (rng.randint(-32768, 32767) for _ in range(_NOISE_TABLE_SIZE)))
    return samples.tobytes()


_SNARE_NOISE_PCM: bytes = _build_noise_table(seed=1337)
_HAT_NOISE_PCM: bytes = _build_noise_table(seed=9001)


def _noise_segment(pcm_table: bytes, duration_ms: int, sample_rate: int = 44100) -> AudioSegment:
    """Build an ``AudioSegment`` from *pcm_table* trimmed/looped to *duration_ms*."""
    n_samples = int(sample_rate * duration_ms / 1000)
    bytes_needed = n_samples * 2  # 16-bit mono
    if bytes_needed <= len(pcm_table):
        data = pcm_table[:bytes_needed]
    else:
        repeats, remainder = divmod(bytes_needed, len(pcm_table))
        data = pcm_table * repeats + pcm_table[:remainder]
    return AudioSegment(data, frame_rate=sample_rate, sample_width=2, channels=1)


def _generate_kick(duration_ms: int, sample_rate: int = 44100) -> AudioSegment:
    """Generate a kick drum sound using a short sine sweep."""
    chunk = Sine(60, sample_rate=sample_rate).to_audio_segment(duration=min(duration_ms, 150))
    fade = Sine(40, sample_rate=sample_rate).to_audio_segment(duration=min(duration_ms, 80))
    kick = chunk.overlay(fade)
    kick = kick.fade_out(min(duration_ms, 100))
    return kick - 6  # Reduce volume


def _generate_snare(duration_ms: int, sample_rate: int = 44100) -> AudioSegment:
    """Generate a deterministic snare drum sound using filtered noise."""
    noise = _noise_segment(_SNARE_NOISE_PCM, min(duration_ms, 120), sample_rate)
    tone = Sine(180, sample_rate=sample_rate).to_audio_segment(duration=min(duration_ms, 80))
    snare = noise.overlay(tone)
    snare = snare.fade_out(min(duration_ms, 80))
    return snare - 9


def _generate_hat(duration_ms: int, sample_rate: int = 44100) -> AudioSegment:
    """Generate a deterministic hi-hat sound using short noise burst."""
    hat = _noise_segment(_HAT_NOISE_PCM, min(duration_ms, 50), sample_rate)
    hat = hat.high_pass_filter(8000)
    hat = hat.fade_out(30)
    return hat - 12


def _generate_perc(duration_ms: int, sample_rate: int = 44100) -> AudioSegment:
    """Generate a percussion sound using short tone."""
    perc = Sine(800, sample_rate=sample_rate).to_audio_segment(duration=min(duration_ms, 60))
    perc = perc.fade_out(40)
    return perc - 15


def synthesize_drums(pattern: DrumPattern, bpm: float, bars: int = 1) -> AudioSegment:
    """
    Synthesize drum pattern to audio.
    
    Args:
        pattern: DrumPattern with step positions (0-15 per bar)
        bpm: Tempo
        bars: Number of bars to generate
    
    Returns:
        AudioSegment with synthesized drums
    """
    steps_per_bar = 16
    step_duration_ms = int((60_000 / bpm) / 4)  # 16th note duration
    total_duration_ms = step_duration_ms * steps_per_bar * bars
    
    base = AudioSegment.silent(duration=total_duration_ms)
    
    for bar_idx in range(bars):
        offset_ms = bar_idx * step_duration_ms * steps_per_bar
        
        # Kick
        for step in pattern.kick_steps:
            if step < steps_per_bar:  # Guard against invalid step indices
                pos = offset_ms + step * step_duration_ms
                kick = _generate_kick(step_duration_ms)
                base = base.overlay(kick, position=pos)
        
        # Snare
        for step in pattern.snare_steps:
            if step < steps_per_bar:
                pos = offset_ms + step * step_duration_ms
                snare = _generate_snare(step_duration_ms)
                base = base.overlay(snare, position=pos)
        
        # Hat
        for step in pattern.hat_steps:
            if step < steps_per_bar:
                pos = offset_ms + step * step_duration_ms
                hat = _generate_hat(step_duration_ms)
                base = base.overlay(hat, position=pos)
        
        # Perc
        for step in pattern.perc_steps:
            if step < steps_per_bar:
                pos = offset_ms + step * step_duration_ms
                perc = _generate_perc(step_duration_ms)
                base = base.overlay(perc, position=pos)
    
    return base


def _midi_to_frequency(midi_note: int) -> float:
    """Convert MIDI note number to frequency in Hz."""
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def synthesize_bass(events: tuple[BassEvent, ...], bpm: float, bars: int = 1) -> AudioSegment:
    """
    Synthesize bassline to audio.
    
    Args:
        events: Tuple of BassEvent with step/note/glide
        bpm: Tempo
        bars: Number of bars to generate
    
    Returns:
        AudioSegment with synthesized bass
    """
    steps_per_bar = 16
    step_duration_ms = int((60_000 / bpm) / 4)
    total_duration_ms = step_duration_ms * steps_per_bar * bars
    
    base = AudioSegment.silent(duration=total_duration_ms)
    
    for bar_idx in range(bars):
        offset_ms = bar_idx * step_duration_ms * steps_per_bar
        
        for event in events:
            pos = offset_ms + event.step * step_duration_ms
            freq = _midi_to_frequency(event.note)
            
            # Generate bass tone with some harmonics
            duration = step_duration_ms * 2  # Sustain 2 steps
            fundamental = Sine(freq).to_audio_segment(duration=duration)
            harmonic = Sine(freq * 2).to_audio_segment(duration=duration) - 12
            bass_note = fundamental.overlay(harmonic)
            bass_note = bass_note.fade_out(int(duration * 0.3))
            bass_note = bass_note - 6
            
            base = base.overlay(bass_note, position=pos)
    
    return base


def synthesize_melody(events: tuple[MelodyEvent, ...], bpm: float, bars: int = 1) -> AudioSegment:
    """
    Synthesize melody to audio.
    
    Args:
        events: Tuple of MelodyEvent with step/note/length
        bpm: Tempo
        bars: Number of bars to generate
    
    Returns:
        AudioSegment with synthesized melody
    """
    steps_per_bar = 16
    step_duration_ms = int((60_000 / bpm) / 4)
    total_duration_ms = step_duration_ms * steps_per_bar * bars
    
    base = AudioSegment.silent(duration=total_duration_ms)
    
    for bar_idx in range(bars):
        offset_ms = bar_idx * step_duration_ms * steps_per_bar
        
        for event in events:
            pos = offset_ms + event.step * step_duration_ms
            freq = _midi_to_frequency(event.note)
            
            duration = step_duration_ms * event.length_steps
            note = Sine(freq).to_audio_segment(duration=duration)
            note = note.fade_in(10).fade_out(int(duration * 0.2))
            note = note - 9
            
            base = base.overlay(note, position=pos)
    
    return base
