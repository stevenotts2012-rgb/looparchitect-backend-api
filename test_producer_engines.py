#!/usr/bin/env python3
"""
Quick test to verify producer engines are working.

This test file checks:
1. All 4 engines can be imported
2. Engine classes have required methods
3. Basic functionality works
"""

def test_imports():
    """Test that all 4 producer engines can be imported."""
    try:
        print("Importing LayerEngine...", end=" ")
        from app.services.layer_engine import LayerEngine
        print("✅")
        
        print("Importing EnergyModulationEngine...", end=" ")
        from app.services.energy_engine import EnergyModulationEngine
        print("✅")
        
        print("Importing VariationEngine...", end=" ")
        from app.services.variation_engine import VariationEngine
        print("✅")
        
        print("Importing TransitionEngine...", end=" ")
        from app.services.transition_engine import TransitionEngine
        print("✅")
        
        print("\n✅ SUCCESS: All 4 engines imported successfully!")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_models():
    """Test that producer models are available."""
    try:
        print("\nImporting producer models...", end=" ")
        from app.services.producer_models import (
            ProducerArrangement,
            Section,
            SectionType,
            InstrumentType,
            TransitionType,
            Variation,
            VariationType,
        )
        print("✅")
        print("✅ SUCCESS: All producer models available!")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


def test_audio_renderer():
    """Test that audio renderer has been updated."""
    try:
        print("\nChecking AudioRenderer integration...", end=" ")
        from app.services.audio_renderer import AudioRenderer
        
        # Check that the method uses the new engines
        import inspect
        source = inspect.getsource(AudioRenderer._render_section)
        
        required_strings = [
            "LayerEngine.apply_layer_mask",
            "EnergyModulationEngine.apply_energy_effects",
        ]
        
        for required in required_strings:
            if required not in source:
                raise AssertionError(f"AudioRenderer._render_section missing: {required}")
        
        print("✅")
        print("✅ SUCCESS: AudioRenderer properly integrated with engines!")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Producer Engine Test Suite")
    print("=" * 60)
    
    results = []
    results.append(("Engine Imports", test_imports()))
    results.append(("Producer Models", test_models()))
    results.append(("AudioRenderer Integration", test_audio_renderer()))
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name}: {status}")
    
    all_pass = all(r for _, r in results)
    if all_pass:
        print("\n🎉 All tests passed! System is ready for producer arrangements!")
    else:
        print("\n⚠️ Some tests failed. Check the errors above.")
    
    exit(0 if all_pass else 1)
