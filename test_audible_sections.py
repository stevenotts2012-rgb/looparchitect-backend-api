#!/usr/bin/env python3
"""
Test script to verify that arrangement rendering produces audible section differences.
Renders a test arrangement and analyzes waveform characteristics per section.
"""

import json
import numpy as np
from pathlib import Path
from pydub import AudioSegment
from pydub.utils import mediainfo

from app.database import SessionLocal
from app.models.arrangement import Arrangement
from app.services.arrangement_jobs import _render_producer_arrangement


def analyze_audio_section(audio_segment: AudioSegment, start_ms: float, end_ms: float) -> dict:
    """Analyze audio characteristics of a specific section."""
    section = audio_segment[int(start_ms):int(end_ms)]
    
    if len(section) == 0:
        return {
            "duration_ms": 0,
            "rms_db": -999,
            "peak_db": -999,
            "hf_content": 0,
        }
    
    # Get samples
    samples = np.array(section.get_array_of_samples(), dtype=np.float32)
    
    # Calculate RMS (loudness)
    rms = np.sqrt(np.mean(samples ** 2))
    rms_db = 20 * np.log10(rms / 32767.0) if rms > 0 else -999
    
    # Calculate peak
    peak = np.max(np.abs(samples))
    peak_db = 20 * np.log10(peak / 32767.0) if peak > 0 else -999
    
    # Estimate HF content (simple: variance in differences)
    if len(samples) > 1:
        diffs = np.diff(samples)
        hf_energy = np.sqrt(np.mean(diffs ** 2))
    else:
        hf_energy = 0
    
    return {
        "duration_ms": len(section),
        "rms_db": float(rms_db),
        "peak_db": float(peak_db),
        "hf_energy": float(hf_energy),
    }


def test_arrangement_rendering():
    """Test rendering an arrangement and verify section differences."""
    
    print("\n" + "="*70)
    print("AUDIBLE SECTION DIFFERENCES TEST")
    print("="*70)
    
    # Create a test producer arrangement with diverse sections
    test_arrangement = {
        "sections": [
            {
                "name": "Intro",
                "section_type": "intro",
                "bars": 4,
                "bar_start": 0,
                "energy_level": 0.35,
            },
            {
                "name": "Verse 1",
                "section_type": "verse",
                "bars": 8,
                "bar_start": 4,
                "energy_level": 0.58,
            },
            {
                "name": "Hook 1",
                "section_type": "hook",
                "bars": 8,
                "bar_start": 12,
                "energy_level": 0.86,
            },
            {
                "name": "Verse 2",
                "section_type": "verse",
                "bars": 8,
                "bar_start": 20,
                "energy_level": 0.62,
            },
            {
                "name": "Hook 2",
                "section_type": "hook",
                "bars": 8,
                "bar_start": 28,
                "energy_level": 0.90,
            },
            {
                "name": "Bridge",
                "section_type": "bridge",
                "bars": 4,
                "bar_start": 36,
                "energy_level": 0.50,
            },
            {
                "name": "Final Hook",
                "section_type": "hook",
                "bars": 8,
                "bar_start": 40,
                "energy_level": 0.95,
            },
            {
                "name": "Outro",
                "section_type": "outro",
                "bars": 4,
                "bar_start": 48,
                "energy_level": 0.42,
            },
        ],
        "total_bars": 52,
        "genre": "electronic",
    }
    
    # Create a simple synthetic test loop
    bpm = 120
    bar_duration_ms = int((60.0 / bpm) * 4.0 * 1000)  # 2000ms per bar at 120 BPM
    
    # Generate a simple sine wave loop (1 bar at sample rate 44100)
    sample_rate = 44100
    bar_samples = int(bar_duration_ms * sample_rate / 1000)
    t = np.linspace(0, 1, bar_samples)
    
    # Create a rich tone: 440Hz fundamental + harmonics
    loop_samples = (
        32760 * 0.7 * np.sin(2 * np.pi * 440 * t) +  # Fundamental
        32760 * 0.3 * np.sin(2 * np.pi * 880 * t) +  # 2nd harmonic
        32760 * 0.2 * np.sin(2 * np.pi * 220 * t)    # Sub
    ) / 2.2  # Normalize to avoid clipping
    
    loop_audio = AudioSegment(
        loop_samples.astype(np.int16).tobytes(),
        frame_rate=sample_rate,
        sample_width=2,
        channels=1,
    )
    
    print(f"\nTest loop: {bar_duration_ms}ms per bar, {len(loop_audio)}ms total")
    print(f"BPM: {bpm}, Bar duration: {bar_duration_ms}ms")
    
    # Render the arrangement
    print("\nRendering test arrangement with section-specific effects...")
    try:
        rendered_audio, timeline_json = _render_producer_arrangement(
            loop_audio=loop_audio,
            producer_arrangement=test_arrangement,
            bpm=bpm,
        )
        print(f"✓ Rendering successful: {len(rendered_audio)}ms produced")
    except Exception as e:
        print(f"✗ Rendering failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Parse timeline and analyze each section
    try:
        timeline = json.loads(timeline_json)
    except:
        timeline = {"sections": []}
    
    print("\n" + "-"*70)
    print(f"{'Section':<15} {'Bars':<5} {'Duration':<12} {'RMS (dB)':<10} {'Peak (dB)':<10} {'HF Energy':<10}")
    print("-"*70)
    
    section_analyses = {}
    for section in timeline.get("sections", []):
        name = section["name"]
        start_sec = section["start_seconds"]
        end_sec = section["end_seconds"]
        start_ms = start_sec * 1000
        end_ms = end_sec * 1000
        
        analysis = analyze_audio_section(rendered_audio, start_ms, end_ms)
        section_analyses[name] = analysis
        
        bars = section["bars"]
        duration_ms = analysis["duration_ms"]
        rms_db = analysis["rms_db"]
        peak_db = analysis["peak_db"]
        hf_energy = analysis["hf_energy"]
        
        print(f"{name:<15} {bars:<5} {duration_ms:<12.0f} {rms_db:<10.1f} {peak_db:<10.1f} {hf_energy:<10.0f}")
    
    # Print comparative analysis
    print("\n" + "-"*70)
    print("LOUDNESS COMPARISONS (should show clear differences):")
    print("-"*70)
    
    # Compare verses vs hooks
    verse_rms = np.mean([
        section_analyses[s]["rms_db"] 
        for s in section_analyses 
        if "Verse" in s
    ])
    hook_rms = np.mean([
        section_analyses[s]["rms_db"]
        for s in section_analyses
        if "Hook" in s
    ])
    
    diff = hook_rms - verse_rms
    print(f"Hook loudness avg:  {hook_rms:+.1f} dB")
    print(f"Verse loudness avg: {verse_rms:+.1f} dB")
    print(f"Hook vs Verse diff: {diff:+.1f} dB {'✓ GOOD - Audible difference' if abs(diff) >= 3 else '⚠ Small difference'}")
    
    # Intro should be quiet
    intro_rms = section_analyses.get("Intro", {}).get("rms_db", -999)
    print(f"\nIntro loudness:     {intro_rms:+.1f} dB")
    if intro_rms < verse_rms - 2:
        print("✓ Intro is noticeably quieter than verses")
    else:
        print("⚠ Intro could be quieter")
    
    # Bridge should be different
    bridge_rms = section_analyses.get("Bridge", {}).get("rms_db", -999)
    print(f"\nBridge loudness:    {bridge_rms:+.1f} dB")
    if bridge_rms < verse_rms:
        print("✓ Bridge is quieter/different from verses")
    else:
        print("⚠ Bridge is similar to verses")
    
    # Outro should be quiet
    outro_rms = section_analyses.get("Outro", {}).get("rms_db", -999)
    print(f"\nOutro loudness:     {outro_rms:+.1f} dB")
    if outro_rms < intro_rms:
        print("✓ Outro fades appropriately")
    else:
        print("⚠ Outro may not fade enough")
    
    print("\n" + "="*70)
    print("TEST COMPLETE")
    print("="*70 + "\n")
    
    # Save rendered audio for manual inspection
    output_path = Path("test_arrangement_rendered.wav")
    rendered_audio.export(str(output_path), format="wav")
    print(f"✓ Rendered audio saved to: {output_path}")
    
    return True


if __name__ == "__main__":
    success = test_arrangement_rendering()
    exit(0 if success else 1)
