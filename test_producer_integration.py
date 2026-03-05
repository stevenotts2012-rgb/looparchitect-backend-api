#!/usr/bin/env python3
"""
Quick integration test for ProducerEngine + BeatGenomeLoader.
"""

import sys
import json

# Test imports
try:
    from app.services.producer_engine import ProducerEngine
    from app.services.beat_genome_loader import BeatGenomeLoader
    from app.services.producer_models import StyleProfile
    print("✓ All imports successful")
except Exception as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test BeatGenomeLoader
try:
    available = BeatGenomeLoader.list_available()
    print(f"✓ BeatGenomeLoader found {len(available)} genomes: {available}")
except Exception as e:
    print(f"✗ BeatGenomeLoader failed: {e}")
    sys.exit(1)

# Test loading a specific genome
try:
    genome = BeatGenomeLoader.load("trap", "dark")
    assert "instrument_layers" in genome
    assert "energy_curve" in genome
    print(f"✓ Loaded trap_dark genome successfully")
except Exception as e:
    print(f"✗ Genome loading failed: {e}")
    sys.exit(1)

# Test ProducerEngine.generate()
try:
    arrangement = ProducerEngine.generate(
        target_seconds=120,
        tempo=100.0,
        genre="trap",
        style_profile=None,
        structure_template="standard",
    )
    assert arrangement is not None
    assert len(arrangement.sections) > 0
    assert len(arrangement.energy_curve) > 0
    print(f"✓ ProducerEngine generated arrangement with {len(arrangement.sections)} sections")
except Exception as e:
    print(f"✗ ProducerEngine generation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test serialization
try:
    from dataclasses import asdict
    
    arrangement_dict = asdict(arrangement)
    json_str = json.dumps(arrangement_dict, default=str)
    assert len(json_str) > 100
    print(f"✓ Serialized arrangement to JSON ({len(json_str)} bytes)")
except Exception as e:
    print(f"✗ Serialization failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✓ All tests passed! Integration is ready.")
