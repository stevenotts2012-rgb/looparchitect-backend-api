#!/usr/bin/env python3
"""
Direct test of the _render_producer_arrangement function 
to verify dramatic effects are being applied to audio.
"""
import json
from pydub import AudioSegment
from pydub.generators import Sine
from app.services.arrangement_jobs import _render_producer_arrangement

# Create a simple test loop (1-second sine wave at 440Hz)
sine_gen = Sine(440, sample_rate=44100)
sine = sine_gen.to_audio_segment(duration=1000)  # 1 second = ~1 bar at 120 BPM * 4
print(f"Created test audio: duration={len(sine)}ms, channels={sine.channels}")

# Create a minimal producer arrangement
producer_arrangement = {
    "sections": [
        {
            "name": "TestIntro",
            "section_type": "Intro",  # Will be converted to lowercase "intro"
            "bar_start": 0,
            "bars": 1,
            "energy_level": 0.5,
            "variations": [],
        },
        {
            "name": "TestDrop",
            "section_type": "Drop",  # Will be converted to lowercase "drop"
            "bar_start": 1,
            "bars": 1,
            "energy_level": 0.7,
            "variations": [],
        }
    ],
    "tracks": [{"name": "test"}],
    "transitions": [],
    "total_bars": 2,
    "genre": "test",
}

# Call the renderer
print("\nCalling _render_producer_arrangement...")
try:
    arranged_audio, timeline_json = _render_producer_arrangement(
        loop_audio=sine,
        producer_arrangement=producer_arrangement,
        bpm=120.0,
    )
    
    print(f"✓ Renderer executed successfully")
    print(f"  Output audio duration: {len(arranged_audio)}ms")
    print(f"  Input audio duration:  {len(sine)}ms")
    print(f"  Ratio: {len(arranged_audio) / len(sine):.1f}x")
    
    # Parse and display timeline
    timeline = json.loads(timeline_json)
    print(f"\nTimeline sections:")
    for section in timeline.get("sections", []):
        print(f"  - {section['name']:15} type={section['type']:10} bars={section['bars']}")
    
    print(f"\nRender profile:")
    for k, v in timeline.get("render_profile", {}).items():
        print(f"  {k}: {v}")
        
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
