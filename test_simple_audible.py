#!/usr/bin/env python3
"""Simple test of section audio rendering without DB dependency."""

import json
import sys
import numpy as np
from pathlib import Path

print("Starting audible sections test...", flush=True)

try:
    from pydub import AudioSegment
    print("✓ Pydub imported", flush=True)
except Exception as e:
    print(f"✗ Error importing pydub: {e}", flush=True)
    sys.exit(1)

try:
    # Import the render function
    from app.services.arrangement_jobs import _render_producer_arrangement
    print("✓ arrangement_jobs imported", flush=True)
except Exception as e:
    print(f"✗ Error importing arrangement_jobs: {e}", flush=True)
    sys.exit(1)

def analyze_audio_section(audio_segment, start_ms, end_ms):
    """Analyze audio characteristics of a specific section."""
    section = audio_segment[int(start_ms):int(end_ms)]
    
    if len(section) == 0:
        return {"duration_ms": 0, "rms_db": -999, "peak_db": -999}
    
    samples = np.array(section.get_array_of_samples(), dtype=np.float32)
    rms = np.sqrt(np.mean(samples ** 2))
    rms_db = 20 * np.log10(rms / 32767.0) if rms > 0 else -999
    
    peak = np.max(np.abs(samples))
    peak_db = 20 * np.log10(peak / 32767.0) if peak > 0 else -999
    
    return {
        "duration_ms": len(section),
        "rms_db": float(rms_db),
        "peak_db": float(peak_db),
    }

# Create test arrangement
test_arrangement = {
    "sections": [
        {"name": "Intro", "section_type": "intro", "bars": 4, "bar_start": 0, "energy_level": 0.35},
        {"name": "Verse 1", "section_type": "verse", "bars": 8, "bar_start": 4, "energy_level": 0.58},
        {"name": "Hook 1", "section_type": "hook", "bars": 8, "bar_start": 12, "energy_level": 0.86},
        {"name": "Final Hook", "section_type": "hook", "bars": 8, "bar_start": 20, "energy_level": 0.95},
    ],
    "total_bars": 28,
}

print("\nGenerating test loop...", flush=True)

# Generate test loop
bpm = 120
bar_duration_ms = int((60.0 / bpm) * 4.0 * 1000)
sample_rate = 44100
bar_samples = int(bar_duration_ms * sample_rate / 1000)
t = np.linspace(0, 1, bar_samples)

loop_samples = (32760 * 0.7 * np.sin(2 * np.pi * 440 * t) + 32760 * 0.3 * np.sin(2 * np.pi * 880 * t)) / 2.0
loop_audio = AudioSegment(
    loop_samples.astype(np.int16).tobytes(),
    frame_rate=sample_rate,
    sample_width=2,
    channels=1,
)

print(f"✓ Test loop created: {len(loop_audio)}ms", flush=True)
print("\nRendering arrangement with effects...", flush=True)

try:
    rendered_audio, timeline_json = _render_producer_arrangement(
        loop_audio=loop_audio,
        producer_arrangement=test_arrangement,
        bpm=bpm,
    )
    print(f"✓ Rendering successful: {len(rendered_audio)}ms produced", flush=True)
except Exception as e:
    print(f"✗ Rendering failed: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Analyze sections
timeline = json.loads(timeline_json)

print("\n" + "-"*70)
print(f"{'Section':<15} {'Duration':<12} {'RMS (dB)':<10} {'Peak (dB)':<10}")
print("-"*70)

analyses = {}
for section in timeline.get("sections", []):
    name = section["name"]
    start_ms = section["start_seconds"] * 1000
    end_ms = section["end_seconds"] * 1000
    
    analysis = analyze_audio_section(rendered_audio, start_ms, end_ms)
    analyses[name] = analysis
    
    print(f"{name:<15} {analysis['duration_ms']:<12.0f} {analysis['rms_db']:<10.1f} {analysis['peak_db']:<10.1f}")

print("-"*70)

# Comparisons
verse_rms = analyses.get("Verse 1", {}).get("rms_db", -999)
hook_rms = np.mean([analyses[s].get("rms_db", -999) for s in analyses if "Hook" in s])
intro_rms = analyses.get("Intro", {}).get("rms_db", -999)

print(f"\nIntro:  {intro_rms:+.1f} dB")
print(f"Verse:  {verse_rms:+.1f} dB")
print(f"Hook:   {hook_rms:+.1f} dB")
print(f"Hook-Verse diff: {hook_rms - verse_rms:+.1f} dB")

if hook_rms - verse_rms >= 3:
    print("✓ GOOD - Audible difference between hook and verse")
elif hook_rms - verse_rms >= 1:
    print("⚠ Some difference, but could be louder")
else:
    print("⚠ Minimal difference detected")

# Save for inspection
output_path = Path("test_arrangement_output.wav")
rendered_audio.export(str(output_path), format="wav")
print(f"\n✓ Audio saved to: {output_path}")
print("✓ TEST COMPLETE\n")
