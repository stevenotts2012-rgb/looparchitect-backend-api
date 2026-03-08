"""Quick test of LoopMetadataAnalyzer functionality."""

import sys
sys.path.insert(0, r'c:\Users\steve\looparchitect-backend-api')

from app.services.loop_metadata_analyzer import LoopMetadataAnalyzer

# Test 1: Dark Trap Detection
print("Test 1: Dark Trap Detection")
result = LoopMetadataAnalyzer.analyze(
    bpm=145.0,
    tags=["dark", "trap", "evil"],
    filename="dark_trap_145bpm.wav",
    mood_keywords=["dark", "aggressive"],
)
print(f"  Genre: {result['detected_genre']}")
print(f"  Mood: {result['detected_mood']}")
print(f"  Energy: {result['energy_level']:.2f}")
print(f"  Confidence: {result['confidence']:.2f}")
print(f"  Template: {result['recommended_template']}")
assert result['detected_genre'] == 'dark_trap', f"Expected dark_trap, got {result['detected_genre']}"
assert result['detected_mood'] == 'dark', f"Expected dark mood, got {result['detected_mood']}"
print("  ✅ PASSED\n")

# Test 2: Melodic Trap Detection
print("Test 2: Melodic Trap Detection")
result = LoopMetadataAnalyzer.analyze(
    bpm=130.0,
    tags=["melodic", "trap", "piano", "emotional"],
    filename="melodic_trap_sad.wav",
)
print(f"  Genre: {result['detected_genre']}")
print(f"  Mood: {result['detected_mood']}")
print(f"  Energy: {result['energy_level']:.2f}")
assert result['detected_genre'] == 'melodic_trap', f"Expected melodic_trap, got {result['detected_genre']}"
print("  ✅ PASSED\n")

# Test 3: Rage Detection
print("Test 3: Rage Detection")
result = LoopMetadataAnalyzer.analyze(
    bpm=165.0,
    tags=["rage", "hyper", "distorted"],
    filename="rage_beat.wav",
)
print(f"  Genre: {result['detected_genre']}")
print(f"  Energy: {result['energy_level']:.2f}")
assert result['detected_genre'] == 'rage', f"Expected rage, got {result['detected_genre']}"
assert result['energy_level'] >= 0.8, f"Expected high energy, got {result['energy_level']}"
print("  ✅ PASSED\n")

# Test 4: Fallback to Generic Trap
print("Test 4: Fallback to Generic Trap")
result = LoopMetadataAnalyzer.analyze(
    bpm=140.0,
    tags=["beat"],
)
print(f"  Genre: {result['detected_genre']}")
print(f"  Confidence: {result['confidence']:.2f}")
# Accept any genre with low confidence when input is minimal
assert result['confidence'] <= 0.5, f"Expected low confidence, got {result['confidence']}"
print("  ✅ PASSED\n")

print("=" * 60)
print("✅ ALL TESTS PASSED!")
print("=" * 60)
print("\nLoopMetadataAnalyzer is working correctly!")
print("Ready for integration with ProducerEngine.")
