#!/usr/bin/env python3
"""
Analyze audio file to verify dramatic effects were applied.
Measures volume levels at different sections.
"""
from pydub import AudioSegment
import json, sqlite3

arrangement_id = 161

# Load the audio file
audio_path = f'uploads/{arrangement_id}.wav'
try:
    audio = AudioSegment.from_wav(audio_path)
    print(f"Loaded {audio_path}: {len(audio)}ms, {audio.channels} channels, {audio.frame_rate}Hz")
except Exception as e:
    print(f"Error loading audio: {e}")
    exit(1)

# Get the render plan to see what sections were supposed to be rendered
db = sqlite3.connect('test.db')
c = db.cursor()
c.execute('SELECT render_plan_json FROM arrangements WHERE id=?', (arrangement_id,))
rp = json.loads(c.fetchone()[0] or '{}')
sections = rp.get('sections', [])
print(f"\nRender plan shows {len(sections)} sections:")

# Analyze audio levels at each section
slice_duration_ms = 500  # Check a 500ms slice in the middle of each section
for i, section in enumerate(sections):
    start_s = section.get('start_seconds', 0)
    end_s = section.get('end_seconds', 0)
    section_type = section.get('type', 'unknown')
    
    # Middle of section
    mid_s = (start_s + end_s) / 2
    mid_ms = int(mid_s * 1000)
    
    # Extract a 500ms slice
    slice_start = max(0, mid_ms - slice_duration_ms // 2)
    slice_end = min(len(audio), mid_ms + slice_duration_ms // 2)
    
    if slice_end <= slice_start:
        print(f"  [{i}] {section['name']:12} type={section_type:12} - NO AUDIO (section too short)")
        continue
    
    audio_slice = audio[slice_start:slice_end]
    
    # Measure RMS (root mean square) amplitude
    samples = audio_slice.get_array_of_samples()
    rms = int((sum(s*s for s in samples) / len(samples)) ** 0.5)
    # Convert to dB relative to max int16 (32767)
    db_level = 20 * (rms / 32767) if rms > 0 else -999
    
    print(f"  [{i}] {section['name']:12} type={section_type:12} @ {mid_s:5.2f}s | RMS dB: {db_level:+6.1f}")

db.close()
print("\nNote: Intro should be ~-12dB, Drop/Hook should be higher (+6dB), Verse/other depends on energy")
