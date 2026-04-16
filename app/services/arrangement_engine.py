"""
Audio arrangement generation engine.

Handles loading loops, applying effects, and generating full-length arrangements.
"""

import json
import logging
import os
import random
from pathlib import Path
from typing import Tuple, List, Dict, Optional

import numpy as np
from pydub import AudioSegment

from app.config import settings
from app.style_engine.seed import create_rng
from app.style_engine.drums import generate_drum_pattern
from app.style_engine.bass import generate_bassline
from app.style_engine.melody import generate_melody
from app.style_engine.audio_synthesis import (
    synthesize_drums,
    synthesize_bass,
    synthesize_melody,
)

logger = logging.getLogger(__name__)


def _resolve_genre_from_style(style_params: Optional[Dict]) -> str:
    """Resolve high-level genre from style params and LLM style metadata."""
    if not style_params:
        return "generic"

    explicit_genre = str(style_params.get("genre") or style_params.get("__genre_hint") or "").lower().strip()
    archetype = str(style_params.get("__archetype") or "").lower().strip()
    raw_input = str(style_params.get("__raw_input") or "").lower().strip()
    signal = " ".join(part for part in (explicit_genre, archetype, raw_input) if part)

    if any(token in signal for token in ("trap", "drill", "atl")):
        return "trap"
    if any(token in signal for token in ("r&b", "rnb", "soul", "neo soul", "melodic")):
        return "rnb"
    if any(token in signal for token in ("pop", "dance pop", "radio pop")):
        return "pop"
    if any(token in signal for token in ("cinematic", "film", "score")):
        return "cinematic"
    return "generic"


def _genre_section_adjustments(genre: str, section_name: str) -> Dict[str, float]:
    """Return genre-aware processing targets for each section."""
    section_lower = section_name.lower()

    base = {
        "low_pass": 12000.0,
        "high_pass": 80.0,
        "gain_db": 0.0,
        "alt_bar_duck_db": 0.0,
        "fade_in_ratio": 0.0,
        "fade_out_ratio": 0.0,
    }

    if "intro" in section_lower:
        base.update({"low_pass": 8000.0, "high_pass": 60.0, "gain_db": -2.5, "fade_in_ratio": 0.32})
    elif "verse" in section_lower:
        base.update({"low_pass": 12000.0, "high_pass": 100.0, "gain_db": -0.5})
    elif "hook" in section_lower:
        base.update({"low_pass": 13200.0, "high_pass": 150.0, "gain_db": 2.0})
    elif "bridge" in section_lower:
        base.update({"low_pass": 6500.0, "high_pass": 180.0, "gain_db": -1.5, "alt_bar_duck_db": 1.0})
    elif "chorus" in section_lower:
        base.update({"low_pass": 14200.0, "high_pass": 120.0, "gain_db": 2.8})
    elif "outro" in section_lower:
        base.update({"low_pass": 6000.0, "high_pass": 60.0, "gain_db": -3.5, "fade_out_ratio": 0.42})

    if genre == "trap":
        if "hook" in section_lower or "chorus" in section_lower:
            base["high_pass"] += 20.0
            base["gain_db"] += 0.7
        if "bridge" in section_lower:
            base["low_pass"] -= 700.0
            base["alt_bar_duck_db"] += 0.6
    elif genre == "rnb":
        # RNB: warm low-pass with -1200 Hz shift; floor at 5000 Hz so intro (8000→6800 Hz)
        # and outro (6000→5000 Hz) stay audible even after the genre modifier is applied.
        base["low_pass"] = max(5000.0, base["low_pass"] - 1200.0)
        base["high_pass"] = max(45.0, base["high_pass"] - 25.0)
        if "hook" in section_lower or "chorus" in section_lower:
            base["gain_db"] -= 0.5
        if "intro" in section_lower or "outro" in section_lower:
            base["fade_in_ratio"] = max(base["fade_in_ratio"], 0.38)
            base["fade_out_ratio"] = max(base["fade_out_ratio"], 0.46)
    elif genre == "pop":
        base["high_pass"] += 10.0
        base["low_pass"] += 800.0
        if "hook" in section_lower or "chorus" in section_lower:
            base["gain_db"] += 0.4
        if "bridge" in section_lower:
            base["alt_bar_duck_db"] = max(0.6, base["alt_bar_duck_db"] - 0.2)
    elif genre == "cinematic":
        base["high_pass"] = max(50.0, base["high_pass"] - 20.0)
        # Cinematic: -1700 Hz shift for a dark, film-like feel; floor at 5000 Hz so no
        # section falls below a clearly audible frequency range (e.g. intro: 8000→6300 Hz).
        base["low_pass"] = max(5000.0, base["low_pass"] - 1700.0)
        if "hook" in section_lower or "chorus" in section_lower:
            base["gain_db"] -= 0.8
        if "bridge" in section_lower:
            base["alt_bar_duck_db"] += 0.8

    return base


def build_phase_b_sections(target_seconds: int, bpm: float) -> List[Dict[str, int]]:
    """
    Build a standard arrangement timeline using bar counts.

    Structure (bars):
    - Intro: 8
    - Hook: 16
    - Verse: 16
    - Hook: 16
    - Bridge: 8
    - Hook: 16
    - Outro: 8

    If target duration doesn't match, the last section is trimmed to fit.
    """
    if bpm <= 0:
        raise ValueError("BPM must be positive")
    if target_seconds <= 0:
        raise ValueError("target_seconds must be positive")

    bar_duration_seconds = (60.0 / bpm) * 4.0
    target_bars = max(4, int(round(target_seconds / bar_duration_seconds)))

    sections_template = [
        ("Intro", 8),
        ("Hook", 16),
        ("Verse", 16),
        ("Hook", 16),
        ("Bridge", 8),
        ("Hook", 16),
        ("Outro", 8),
    ]

    sections: List[Dict[str, int]] = []
    current_bar = 0

    for name, bars in sections_template:
        if current_bar >= target_bars:
            break

        remaining = target_bars - current_bar
        section_bars = bars if remaining >= bars else remaining
        sections.append(
            {
                "name": name,
                "bars": section_bars,
                "start_bar": current_bar,
                "end_bar": current_bar + section_bars - 1,
            }
        )
        current_bar += section_bars

    return sections


def render_phase_b_arrangement(
    loop_audio: AudioSegment,
    bpm: float,
    target_seconds: int,
    sections_override: Optional[List[Dict]] = None,
    seed: Optional[int] = None,
    root_note: int = 48,
    style_params: Optional[Dict] = None,
) -> Tuple[AudioSegment, str]:
    """
    Render the Phase B arrangement by repeating the loop per section.
    
    Args:
        loop_audio: Source loop audio
        bpm: Tempo
        target_seconds: Target duration
        sections_override: Optional section structure override
        seed: Optional seed for deterministic pattern generation
        root_note: Root MIDI note for bass/melody patterns
        style_params: V2 - Optional resolved style parameters dict (aggression, melody_complexity, etc.)
    
    Returns:
        Tuple of (audio_segment, timeline_json)
    """
    # V2: Store style params for arrangement rendering and genre-aware processing
    genre_profile = _resolve_genre_from_style(style_params)
    if style_params:
        logger.info(
            "Arrangement using V2 style parameters: aggression=%.2f, melody_complexity=%.2f, genre_profile=%s",
            style_params.get("aggression", 0.5),
            style_params.get("melody_complexity", 0.5),
            genre_profile,
        )
    else:
        logger.info("Arrangement rendering with default genre profile: %s", genre_profile)
    
    sections = sections_override or build_phase_b_sections(target_seconds, bpm)
    bar_duration_ms = int((60.0 / bpm) * 4.0 * 1000)
    
    # Create RNG for pattern generation if seed provided
    rng = None
    if seed is not None:
        _, rng = create_rng(seed)  # Unpack tuple (normalized_seed, rng)

    arranged = AudioSegment.silent(duration=0)
    total_sections = len(sections)
    section_crossfade_ms = 60  # Short crossfade to smooth level/EQ transitions between sections
    for section_index, section in enumerate(sections):
        section_ms = section["bars"] * bar_duration_ms
        section_audio = _repeat_audio_to_duration(loop_audio, section_ms)
        
        # Generate and mix patterns if feature enabled
        if rng is not None and settings.feature_pattern_generation:
            section_audio = _generate_and_mix_patterns(
                section_audio,
                section_name=section["name"],
                section_bars=section["bars"],
                bpm=bpm,
                rng=rng,
                root_note=root_note,
            )
        
        # Apply intelligent section-specific processing for arrangement variation
        section_energy = float(section.get("energy", 0.6))
        section_audio = _apply_section_processing(
            section_audio,
            section_name=section["name"],
            bar_duration_ms=bar_duration_ms,
            energy=section_energy,
            section_index=section_index,
            total_sections=total_sections,
            genre=genre_profile,
            style_params=style_params,
        )
        # Use a short crossfade between sections to prevent abrupt level/EQ jumps
        if len(arranged) == 0:
            arranged = section_audio
        else:
            arranged = arranged.append(section_audio, crossfade=section_crossfade_ms)

    timeline_json = _generate_phase_b_timeline_json(
        sections,
        bpm,
        genre_profile=genre_profile,
        style_params=style_params,
    )
    return arranged, timeline_json


def _repeat_audio_to_duration(audio: AudioSegment, target_ms: int) -> AudioSegment:
    """Repeat and trim audio to exactly target_ms."""
    if target_ms <= 0:
        return AudioSegment.silent(duration=0)

    repeats = (target_ms // len(audio)) + 1
    extended = audio * repeats
    return extended[:target_ms]


def _generate_and_mix_patterns(
    audio: AudioSegment,
    section_name: str,
    section_bars: int,
    bpm: float,
    rng: random.Random,
    root_note: int = 48,  # C3
    mix_level: float = 0.3,
) -> AudioSegment:
    """
    Generate and mix drum/bass/melody patterns with the loop audio.
    
    Args:
        audio: Source loop audio
        section_name: Section name for pattern variation
        section_bars: Number of bars in section
        bpm: Tempo
        rng: Seeded random number generator
        root_note: Root MIDI note for bass/melody
        mix_level: Volume level for generated patterns (0.0 to 1.0)
    
    Returns:
        AudioSegment with mixed patterns
    """
    if not settings.feature_pattern_generation:
        return audio
    
    # Determine pattern density based on section
    section_lower = section_name.lower()
    if "intro" in section_lower or "outro" in section_lower:
        density = 0.3
        complexity = 0.2
    elif "verse" in section_lower:
        density = 0.6
        complexity = 0.5
    elif "bridge" in section_lower:
        density = 0.4
        complexity = 0.7
    else:  # hook/chorus
        density = 0.8
        complexity = 0.6
    
    # Generate patterns
    drum_pattern = generate_drum_pattern(rng, density=density, hat_roll_probability=0.2)
    bass_events = generate_bassline(rng, root_note=root_note, glide_probability=0.3)
    melody_events = generate_melody(rng, root_note=root_note + 12, complexity=complexity)
    
    # Synthesize to audio
    drums_audio = synthesize_drums(drum_pattern, bpm, bars=section_bars)
    bass_audio = synthesize_bass(bass_events, bpm, bars=section_bars)
    melody_audio = synthesize_melody(melody_events, bpm, bars=section_bars)
    
    # Trim/extend to match source audio length
    target_len = len(audio)
    drums_audio = drums_audio[:target_len] if len(drums_audio) > target_len else drums_audio + AudioSegment.silent(target_len - len(drums_audio))
    bass_audio = bass_audio[:target_len] if len(bass_audio) > target_len else bass_audio + AudioSegment.silent(target_len - len(bass_audio))
    melody_audio = melody_audio[:target_len] if len(melody_audio) > target_len else melody_audio + AudioSegment.silent(target_len - len(melody_audio))
    
    # Apply mix level (convert to dB reduction)
    mix_db = int(-10 * (1.0 - mix_level))
    drums_audio = drums_audio + mix_db
    bass_audio = bass_audio + mix_db
    melody_audio = melody_audio + mix_db
    
    # Mix with original audio
    mixed = audio.overlay(drums_audio).overlay(bass_audio).overlay(melody_audio)
    return mixed


def _apply_section_processing(
    audio: AudioSegment,
    section_name: str,
    bar_duration_ms: int,
    energy: float,
    section_index: int,
    total_sections: int,
    genre: str = "generic",
    style_params: Optional[Dict] = None,
) -> AudioSegment:
    """
    Apply intelligent section-specific processing to create arrangement variation.
    
    Different sections get different effects to build a structured arrangement:
    - Intro: gradual build, low-pass filtering
    - Verse: main groove with presence
    - Hook: bright, punchy, emphasized
    - Bridge: variation, different EQ, increase dynamics
    - Chorus: maximum presence, compression feel
    - Outro: fade out, reverb tail
    
    Args:
        audio: Section audio to process
        section_name: Name of section (Intro, Verse, Hook, Bridge, Chorus, Outro)
        bar_duration_ms: Duration of one bar in ms
        energy: Energy level (0.0-1.0) from arrangement
        section_index: Position in arrangement (for build-up progress)
        total_sections: Total number of sections
    """
    energy = max(0.0, min(1.0, energy))
    shaped = audio
    section_lower = section_name.lower()
    
    # Calculate progression ratio (0=start, 1=end)
    progress = section_index / max(1, total_sections - 1) if total_sections > 1 else 0.5

    # Style-driven intensity controls (when present)
    fx_density = float((style_params or {}).get("fx_density", 0.5))
    aggression = float((style_params or {}).get("aggression", 0.5))

    adjustments = _genre_section_adjustments(genre, section_name)
    low_pass_hz = int(adjustments["low_pass"])
    high_pass_hz = int(adjustments["high_pass"])
    gain_db = adjustments["gain_db"]
    alt_bar_duck_db = adjustments["alt_bar_duck_db"]
    
    # INTRO: Gradual build from silence to presence
    if "intro" in section_lower:
        logger.info("Applying Intro processing: genre=%s", genre)
        # Low-pass for warmth
        shaped = shaped.low_pass_filter(low_pass_hz)
        # Gentle fade-in
        fade_ms = min(int(len(shaped) * max(0.2, adjustments["fade_in_ratio"])), len(shaped) // 2)
        shaped = shaped.fade_in(fade_ms)
        # Slight reduction to let it build
        shaped = shaped - (2 + (1 - fx_density))
        shaped = shaped.high_pass_filter(high_pass_hz)
    
    # VERSE: Balanced, groovy, presence
    elif "verse" in section_lower:
        logger.info("Applying Verse processing: genre=%s", genre)
        # Add some presence with gentle high-pass
        shaped = shaped.high_pass_filter(high_pass_hz)
        # Subtle compression feel - reduce peaks slightly
        shaped = shaped - 1 if energy < 0.6 else shaped
        # Balanced EQ
        shaped = shaped.low_pass_filter(low_pass_hz)
        if gain_db != 0:
            shaped = shaped + gain_db
    
    # HOOK: Bright, punchy, emphasized
    elif "hook" in section_lower:
        logger.info("Applying Hook processing: genre=%s", genre)
        # Bright high-pass for punch
        shaped = shaped.high_pass_filter(high_pass_hz)
        # Add presence in upper midrange
        shaped = shaped.low_pass_filter(low_pass_hz)
        # Compression-like effect by slightly boosting
        shaped = shaped + (gain_db + aggression)
    
    # BRIDGE: Variation and contrast
    elif "bridge" in section_lower:
        logger.info("Applying Bridge processing: genre=%s", genre)
        # Different filtering for variation
        shaped = shaped.low_pass_filter(low_pass_hz)  # More filtered for variation
        shaped = shaped.high_pass_filter(high_pass_hz)
        # Slightly reducing energy to create contrast
        shaped = shaped + gain_db
        # Add dynamic feel with subtle level variation
        pieces: List[AudioSegment] = []
        total_bars = max(1, len(shaped) // max(1, bar_duration_ms))
        for bar_idx in range(total_bars):
            start = bar_idx * bar_duration_ms
            end = min(len(shaped), start + bar_duration_ms)
            bar_audio = shaped[start:end]
            # Alternate bar dynamics
            if bar_idx % 2 == 0:
                bar_audio = bar_audio - alt_bar_duck_db
            pieces.append(bar_audio)
        shaped = AudioSegment.silent(duration=0)
        for piece in pieces:
            shaped += piece
    
    # CHORUS: Maximum impact and presence
    elif "chorus" in section_lower:
        logger.info("Applying Chorus processing: genre=%s", genre)
        # Very bright high-pass for clarity
        shaped = shaped.high_pass_filter(high_pass_hz)
        # Presence boost
        shaped = shaped.low_pass_filter(low_pass_hz)
        # Gain boost for impact
        shaped = shaped + (gain_db + aggression)
    
    # OUTRO: Fade out, tail effect
    elif "outro" in section_lower:
        logger.info("Applying Outro processing: genre=%s", genre)
        # Dark filtering for fadeout feel
        shaped = shaped.low_pass_filter(low_pass_hz)
        # Fade out effect
        fade_ms = min(int(len(shaped) * max(0.25, adjustments["fade_out_ratio"])), len(shaped) // 2)
        shaped = shaped.fade_out(fade_ms)
        # Reduce level for natural tail
        shaped = shaped + gain_db
    
    # DEFAULT: Energy-based shaping
    else:
        if energy < 0.45:
            # Low energy: sparse, filtered
            shaped = shaped.low_pass_filter(max(3500, low_pass_hz - 1200))
            shaped = shaped - 2
        elif energy > 0.8:
            # High energy: bright, punchy
            shaped = shaped.high_pass_filter(high_pass_hz)
            shaped = shaped.low_pass_filter(low_pass_hz)
            shaped = shaped + (2 + aggression)
        else:
            # Mid energy: balanced
            shaped = shaped.high_pass_filter(max(70, high_pass_hz - 10))
            shaped = shaped.low_pass_filter(low_pass_hz)
    
    return shaped


def _shape_section_audio(audio: AudioSegment, bar_duration_ms: int, energy: float) -> AudioSegment:
    """Legacy shaping - now calls enhanced processing. Kept for backward compatibility."""
    # Call new processing with default section name and indices
    return _apply_section_processing(
        audio,
        section_name="verse",
        bar_duration_ms=bar_duration_ms,
        energy=energy,
        section_index=0,
        total_sections=1,
        genre="generic",
        style_params=None,
    )


def _generate_phase_b_timeline_json(
    sections: List[Dict[str, int]],
    bpm: float,
    genre_profile: str = "generic",
    style_params: Optional[Dict] = None,
) -> str:
    """Generate JSON timeline for Phase B arrangement sections."""
    bar_duration_seconds = (60.0 / bpm) * 4.0
    source_archetype = (style_params or {}).get("__archetype")
    source_genre_hint = (style_params or {}).get("__genre_hint")
    raw_input = (style_params or {}).get("__raw_input")
    style_signature = f"{genre_profile}:{source_archetype or 'none'}:{str(raw_input or '')[:32]}"

    events: List[Dict[str, object]] = []
    timeline = {
        "bpm": bpm,
        "render_profile": {
            "genre_profile": genre_profile,
            "source_archetype": source_archetype,
            "source_genre_hint": source_genre_hint,
            "style_signature": style_signature,
        },
        "events": events,
        "sections": [],
    }

    for section in sections:
        start_seconds = section["start_bar"] * bar_duration_seconds
        end_seconds = (section["end_bar"] + 1) * bar_duration_seconds
        timeline["sections"].append(
            {
                "name": section["name"],
                "bars": section["bars"],
                "energy": round(float(section.get("energy", 0.6)), 3),
                "start_bar": section["start_bar"],
                "end_bar": section["end_bar"],
                "start_seconds": round(start_seconds, 3),
                "end_seconds": round(end_seconds, 3),
            }
        )

        # Build deterministic event list at bar granularity for render plan verification
        section_name = str(section["name"])
        start_bar = int(section["start_bar"])
        bars = int(section["bars"])
        for local_bar in range(max(0, bars)):
            bar_number = start_bar + local_bar
            events.append(
                {
                    "type": "section_bar",
                    "section": section_name,
                    "bar": bar_number,
                    "time_seconds": round(bar_number * bar_duration_seconds, 3),
                    "genre_profile": genre_profile,
                }
            )

    return json.dumps(timeline)


def generate_arrangement(
    input_wav_path: str,
    target_seconds: int,
    bpm: float,
    genre: str = "generic",
    intensity: str = "medium",
) -> Tuple[str, str]:
    """
    Generate a full audio arrangement from a loop.

    Loads the input WAV, repeats/slices it to match target duration,
    applies effects based on genre and intensity, and exports to render directory.

    Args:
        input_wav_path: Path to source WAV file
        target_seconds: Target arrangement duration
        bpm: Beats per minute of the loop
        genre: Genre hint for effect selection
        intensity: Intensity level (low/medium/high)

    Returns:
        Tuple of (output_file_url, arrangement_json)
        - output_file_url: Path relative to project (/renders/arrangements/filename.wav)
        - arrangement_json: JSON string with section timeline

    Raises:
        FileNotFoundError: If input file doesn't exist
        Exception: If audio processing fails
    """
    if not os.path.exists(input_wav_path):
        raise FileNotFoundError(f"Input file not found: {input_wav_path}")

    logger.info(
        f"Generating arrangement: {input_wav_path} -> {target_seconds}s, "
        f"{genre}/{intensity}"
    )

    # Load the loop
    audio = AudioSegment.from_wav(str(input_wav_path))
    loop_duration_ms = len(audio)
    loop_duration_seconds = loop_duration_ms / 1000.0

    logger.info(f"Loaded loop: {loop_duration_seconds:.2f}s")

    # Create directory if needed
    renders_dir = os.path.join(os.getcwd(), "renders", "arrangements")
    os.makedirs(renders_dir, exist_ok=True)

    # Calculate section boundaries
    sections = _calculate_sections(target_seconds)
    target_ms = target_seconds * 1000

    # Repeat loop to fill target duration
    repeats_needed = int(np.ceil(target_seconds / loop_duration_seconds))
    audio_extended = audio * repeats_needed
    audio_extended = audio_extended[:target_ms]  # Trim to exact target

    logger.info(f"Extended loop by {repeats_needed}x, trimmed to {target_seconds}s")

    # Apply section-based effects
    audio_arranged = _apply_section_effects(
        audio_extended,
        sections,
        target_ms,
        bpm,
        genre,
        intensity,
    )

    # Export to renders directory
    import uuid

    filename = f"{uuid.uuid4()}.wav"
    output_path = os.path.join(renders_dir, filename)
    audio_arranged.export(output_path, format="wav")
    logger.info(f"Exported to {output_path}")

    # Generate timeline JSON
    arrangement_json = _generate_timeline_json(sections, target_seconds)

    # Return URL-style path (relative to project root, starts with /)
    output_url = f"/renders/arrangements/{filename}"

    return output_url, arrangement_json


def _calculate_sections(target_seconds: int) -> dict:
    """
    Calculate section boundaries based on a standard structure.

    Structure:
    - Intro: 10%
    - Verse1: 30%
    - Hook: 30%
    - Verse2: 20%
    - Outro: 10%

    Args:
        target_seconds: Total duration in seconds

    Returns:
        Dict of section name -> (start_seconds, end_seconds)
    """
    intro_sec = target_seconds * 0.10
    verse1_sec = target_seconds * 0.30
    hook_sec = target_seconds * 0.30
    verse2_sec = target_seconds * 0.20
    outro_sec = target_seconds * 0.10

    sections = {
        "intro": (0, intro_sec),
        "verse1": (intro_sec, intro_sec + verse1_sec),
        "hook": (intro_sec + verse1_sec, intro_sec + verse1_sec + hook_sec),
        "verse2": (
            intro_sec + verse1_sec + hook_sec,
            intro_sec + verse1_sec + hook_sec + verse2_sec,
        ),
        "outro": (
            intro_sec + verse1_sec + hook_sec + verse2_sec,
            target_seconds,
        ),
    }

    return sections


def _apply_section_effects(
    audio: AudioSegment,
    sections: dict,
    target_ms: int,
    bpm: float,
    genre: str,
    intensity: str,
) -> AudioSegment:
    """
    Apply section-specific effects to the audio.

    Effects include:
    - Intro: Low-pass filter for smooth entry
    - Outro: High-pass filter and fade-out for smooth exit
    - Dropouts: Periodic silence for dynamic interest (genre/intensity dependent)
    - Gain variations: ±1-2dB for subtle dynamics

    Args:
        audio: AudioSegment to process
        sections: Section boundaries
        target_ms: Total duration in milliseconds
        bpm: Beats per minute
        genre: Genre for effect decisions
        intensity: Intensity level

    Returns:
        Processed AudioSegment
    """
    logger.info("Applying section effects")

    # Convert to mono for processing
    if audio.channels > 1:
        audio = audio.set_channels(1)

    # Apply intro low-pass filter
    intro_start, intro_end = sections["intro"]
    intro_ms = int(intro_end * 1000)
    if intro_ms > 0:
        # Gradual volume increase (fade in) simulates low-pass
        intro_part = audio[:intro_ms]
        intro_part = intro_part.fade_in(duration=int(intro_ms * 0.5))
        audio = intro_part + audio[intro_ms:]
        logger.info(f"Applied intro fade-in")

    # Apply outro high-pass filter (fade out)
    outro_start, outro_end = sections["outro"]
    outro_start_ms = int(outro_start * 1000)
    if outro_start_ms < target_ms:
        outro_duration_ms = target_ms - outro_start_ms
        outro_part = audio[outro_start_ms:]
        outro_part = outro_part.fade_out(duration=int(outro_duration_ms * 0.5))
        audio = audio[:outro_start_ms] + outro_part
        logger.info(f"Applied outro fade-out")

    # Apply dynamic effects based on intensity
    if intensity in ("medium", "high"):
        # Add periodic dropouts for dynamic interest
        audio = _add_dropouts(audio, target_ms, bpm, intensity)

    # Add subtle gain variations
    audio = _add_gain_variations(audio, target_ms, bpm)

    return audio


def _add_dropouts(
    audio: AudioSegment,
    target_ms: int,
    bpm: float,
    intensity: str,
) -> AudioSegment:
    """
    Add periodic dropouts (silence) for dynamic interest.

    Dropout frequency and duration depend on intensity.

    Args:
        audio: AudioSegment to process
        target_ms: Total duration in milliseconds
        bpm: Beats per minute
        intensity: Intensity level

    Returns:
        AudioSegment with dropouts applied
    """
    if intensity == "low":
        return audio  # No dropouts for low intensity

    # Calculate beat duration in ms
    beat_duration_ms = (60 / bpm) * 1000

    # High intensity: dips every 4 beats, 0.5 beat duration
    # Medium intensity: dips every 8 beats, 0.25 beat duration
    if intensity == "high":
        interval_ms = beat_duration_ms * 4
        dropout_duration_ms = beat_duration_ms * 0.5
    else:  # medium
        interval_ms = beat_duration_ms * 8
        dropout_duration_ms = beat_duration_ms * 0.25

    dropout_duration_ms = int(dropout_duration_ms)

    # Apply smooth volume dips (fade out → attenuate → fade in) instead of hard silence
    result = audio
    position = int(interval_ms)
    dropout_count = 0

    while position < target_ms:
        if position + dropout_duration_ms <= target_ms:
            before = result[:position]
            dip_audio = result[position : position + dropout_duration_ms]
            after = result[position + dropout_duration_ms :]
            # Fade out the first half and fade in the second half, then attenuate
            fade_duration_ms = max(1, len(dip_audio) // 2)
            dip_audio = dip_audio.fade_out(fade_duration_ms).fade_in(fade_duration_ms) - 14
            result = before + dip_audio + after
            dropout_count += 1
            position += int(interval_ms)
        else:
            break

    logger.info(f"Applied {dropout_count} dropouts")
    return result


def _add_gain_variations(
    audio: AudioSegment,
    target_ms: int,
    bpm: float,
) -> AudioSegment:
    """
    Add subtle gain variations (±1-2dB) for dynamics.

    Variations are applied at bar intervals for musical alignment.

    Args:
        audio: AudioSegment to process
        target_ms: Total duration in milliseconds
        bpm: Beats per minute

    Returns:
        AudioSegment with gain variations applied
    """
    # Calculate bar duration in ms (4 beats per bar)
    beat_duration_ms = (60 / bpm) * 1000
    bar_duration_ms = beat_duration_ms * 4

    # Apply gain variations every bar
    result = audio
    position = 0
    variation_count = 0

    np.random.seed(42)  # For reproducibility across runs
    while position < target_ms:
        bar_end = min(int(position + bar_duration_ms), target_ms)

        if bar_end > position:
            # Gentle gain variation ±0.75 dB to maintain dynamics without jarring jumps
            gain_db = np.random.uniform(-0.75, 0.75)
            gain_factor = 10 ** (gain_db / 20)

            before = result[:position]
            middle = result[position:bar_end]
            after = result[bar_end:]

            # Apply gain
            middle = middle.apply_gain(gain_db)

            result = before + middle + after
            variation_count += 1

        position = bar_end

    logger.info(f"Applied {variation_count} gain variations")
    return result


def _generate_timeline_json(sections: dict, target_seconds: int) -> str:
    """
    Generate JSON timeline with section information.

    Args:
        sections: Section boundaries dict
        target_seconds: Total duration

    Returns:
        JSON string with timeline
    """
    timeline = {
        "total_duration_seconds": target_seconds,
        "sections": [
            {
                "name": name,
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": end - start,
            }
            for name, (start, end) in sections.items()
        ],
    }

    return json.dumps(timeline, indent=2)
