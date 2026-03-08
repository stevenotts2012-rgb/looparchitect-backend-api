"""Analyze the latest generated audio files to check if effects are applied."""
import os
from pydub import AudioSegment
from pathlib import Path
import numpy as np

def get_rms_db(segment):
    """Calculate RMS level in dB."""
    if len(segment) == 0:
        return -999
    samples = np.array(segment.get_array_of_samples(), dtype=np.float64)
    rms = np.sqrt(np.mean(samples ** 2))
    db = 20 * np.log10(rms / 32768) if rms > 0 else -999
    return db

def analyze_audio_file(file_path):
    """Analyze audio file and print section RMS levels."""
    print(f"\n{'='*70}")
    print(f"Analyzing: {os.path.basename(file_path)}")
    print(f"{'='*70}")
    
    audio = AudioSegment.from_wav(file_path)
    duration_sec = len(audio) / 1000
    
    print(f"Duration: {duration_sec:.2f} seconds")
    print(f"Channels: {audio.channels}")
    print(f"Sample rate: {audio.frame_rate} Hz")
    
    # Expected section boundaries (assuming ~11.4 sec per section for 8-bar sections at typical BPM)
    # For 3 sections of roughly equal length
    section_duration_ms = len(audio) // 3
    
    print(f"\nExpected section boundaries:")
    print(f"  Intro:  0 - {section_duration_ms}ms")
    print(f"  Hook:   {section_duration_ms} - {section_duration_ms*2}ms")
    print(f"  Verse:  {section_duration_ms*2} - {len(audio)}ms")
    
    # Measure RMS at the middle of each section
    sections = [
        ("Intro", 0, section_duration_ms),
        ("Hook", section_duration_ms, section_duration_ms * 2),
        ("Verse", section_duration_ms * 2, len(audio))
    ]
    
    print(f"\nRMS levels at section MIDPOINTS:")
    for section_name, start_ms, end_ms in sections:
        mid_ms = (start_ms + end_ms) // 2
        measurement_window = 1000  # 1 second window
        window_start = max(0, mid_ms - measurement_window // 2)
        window_end = min(len(audio), mid_ms + measurement_window // 2)
        
        segment = audio[window_start:window_end]
        rms_db = get_rms_db(segment)
        
        print(f"  {section_name:10} @ {int(mid_ms/1000):.2f}s: {rms_db:+.1f} dB")
    
    # Also check overall RMS
    overall_rms = get_rms_db(audio)
    print(f"\nOverall RMS: {overall_rms:+.1f} dB")
    
    return audio, sections

# Analyze the latest files
uploads_dir = Path("uploads")
# Get only numbered WAV files (arrangements), not UUID-named ones
audio_files = []
for f in uploads_dir.glob("*.wav"):
    try:
        # Try to extract arrangement ID from filename
        arr_id = int(f.stem)
        audio_files.append((arr_id, f))
    except ValueError:
        # Not a numbered file, skip it
        pass

audio_files = sorted(audio_files, key=lambda x: x[0], reverse=True)
audio_files = [f for _, f in audio_files]

print("Available audio files (newest first):")
for f in audio_files[:5]:
    print(f"  {f.name}")

if audio_files:
    latest_file = audio_files[0]
    analyze_audio_file(str(latest_file))
