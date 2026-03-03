"""
Audio arrangement generation engine.

Handles loading loops, applying effects, and generating full-length arrangements.
"""

import json
import logging
import os
from pathlib import Path
from typing import Tuple, List, Dict

import numpy as np
from pydub import AudioSegment

logger = logging.getLogger(__name__)


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
) -> Tuple[AudioSegment, str]:
    """
    Render the Phase B arrangement by repeating the loop per section.

    Returns:
        Tuple of (audio_segment, timeline_json)
    """
    sections = build_phase_b_sections(target_seconds, bpm)
    bar_duration_ms = int((60.0 / bpm) * 4.0 * 1000)

    arranged = AudioSegment.silent(duration=0)
    for section in sections:
        section_ms = section["bars"] * bar_duration_ms
        section_audio = _repeat_audio_to_duration(loop_audio, section_ms)
        arranged += section_audio

    timeline_json = _generate_phase_b_timeline_json(sections, bpm)
    return arranged, timeline_json


def _repeat_audio_to_duration(audio: AudioSegment, target_ms: int) -> AudioSegment:
    """Repeat and trim audio to exactly target_ms."""
    if target_ms <= 0:
        return AudioSegment.silent(duration=0)

    repeats = (target_ms // len(audio)) + 1
    extended = audio * repeats
    return extended[:target_ms]


def _generate_phase_b_timeline_json(sections: List[Dict[str, int]], bpm: float) -> str:
    """Generate JSON timeline for Phase B arrangement sections."""
    bar_duration_seconds = (60.0 / bpm) * 4.0
    timeline = {
        "bpm": bpm,
        "sections": [],
    }

    for section in sections:
        start_seconds = section["start_bar"] * bar_duration_seconds
        end_seconds = (section["end_bar"] + 1) * bar_duration_seconds
        timeline["sections"].append(
            {
                "name": section["name"],
                "bars": section["bars"],
                "start_bar": section["start_bar"],
                "end_bar": section["end_bar"],
                "start_seconds": round(start_seconds, 3),
                "end_seconds": round(end_seconds, 3),
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

    # High intensity: dropouts every 4 beats, 0.5 beat duration
    # Medium intensity: dropouts every 8 beats, 0.25 beat duration
    if intensity == "high":
        interval_ms = beat_duration_ms * 4
        dropout_duration_ms = beat_duration_ms * 0.5
    else:  # medium
        interval_ms = beat_duration_ms * 8
        dropout_duration_ms = beat_duration_ms * 0.25

    dropout_duration_ms = int(dropout_duration_ms)

    # Build silence for dropouts
    silence = AudioSegment.silent(duration=dropout_duration_ms)

    # Apply dropouts at intervals
    result = audio
    position = int(interval_ms)
    dropout_count = 0

    while position < target_ms:
        if position + dropout_duration_ms <= target_ms:
            before = result[:position]
            after = result[position + dropout_duration_ms :]
            result = before + silence + after
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
            # Random gain between -2dB and +2dB
            gain_db = np.random.uniform(-2, 2)
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
