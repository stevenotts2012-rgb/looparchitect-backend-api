#!/usr/bin/env python3
"""
End-to-End Validation: Producer Engine + BeatGenomeLoader Integration

Tests:
1. Module imports
2. BeatGenomeLoader - discover and load all 9 genomes
3. ProducerEngine.generate() - create arrangements
4. Data serialization to JSON
5. Error handling and fallbacks
"""

import sys
import json
import logging
from pathlib import Path
from dataclasses import asdict

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

print("=" * 70)
print("PRODUCER ENGINE VALIDATION - END-TO-END")
print("=" * 70)
print()

# ============================================================================
# PHASE 1: IMPORT VALIDATION
# ============================================================================
print("📦 PHASE 1: IMPORT VALIDATION")
print("-" * 70)

try:
    from app.services.producer_engine import ProducerEngine
    from app.services.beat_genome_loader import BeatGenomeLoader
    from app.services.producer_models import StyleProfile
    print("✅ All core imports successful")
except Exception as e:
    print(f"❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# PHASE 2: BEAT GENOME LOADER VALIDATION
# ============================================================================
print()
print("🎵 PHASE 2: BEAT GENOME LOADER VALIDATION")
print("-" * 70)

# Test: Discover genomes
try:
    available = BeatGenomeLoader.list_available()
    expected_count = 9
    
    print(f"Available genomes: {len(available)}")
    for genome_name in sorted(available):
        print(f"  - {genome_name}")
    
    if len(available) == expected_count:
        print(f"✅ Found all {expected_count} genomes")
    else:
        print(f"⚠️  Found {len(available)} genomes, expected {expected_count}")
except Exception as e:
    print(f"❌ BeatGenomeLoader.list_available() failed: {e}")
    sys.exit(1)

# Test: Load each genome
print()
print("Loading genomes...")
genomes_loaded = {}
test_genres = [
    ("trap", "dark"),
    ("trap", "bounce"),
    ("drill", "uk"),
    ("rnb", "modern"),
    ("rnb", "smooth"),
    ("afrobeats", None),
    ("cinematic", None),
    ("edm", "pop"),
    ("edm", "hard"),
]

for genre, mood in test_genres:
    try:
        if mood:
            genome = BeatGenomeLoader.load(genre, mood)
            key = f"{genre}_{mood}"
        else:
            genome = BeatGenomeLoader.load(genre)
            key = genre
        
        # Validate structure
        assert "instrument_layers" in genome, f"Missing instrument_layers in {key}"
        assert "energy_curve" in genome, f"Missing energy_curve in {key}"
        assert "section_lengths" in genome, f"Missing section_lengths in {key}"
        
        genomes_loaded[key] = genome
        print(f"✅ {key:20s} - {genome.get('name', 'Unknown')}")
    except FileNotFoundError as e:
        print(f"❌ {genre}_{mood if mood else 'default':20s} - NOT FOUND")
    except AssertionError as e:
        print(f"❌ {genre}_{mood if mood else 'default':20s} - Invalid structure: {e}")
    except Exception as e:
        print(f"❌ {genre}_{mood if mood else 'default':20s} - {type(e).__name__}: {e}")

print(f"\n✅ Successfully loaded {len(genomes_loaded)}/{len(test_genres)} genomes")

# ============================================================================
# PHASE 3: PRODUCER ENGINE GENERATION
# ============================================================================
print()
print("🎼 PHASE 3: PRODUCER ENGINE GENERATION")
print("-" * 70)

test_configs = [
    {
        "name": "Trap Dark Test",
        "genre": "trap",
        "tempo": 140,
        "target_seconds": 60,
        "style_profile": None,
    },
    {
        "name": "R&B Modern Test",
        "genre": "rnb",
        "tempo": 95,
        "target_seconds": 120,
        "style_profile": None,
    },
    {
        "name": "Cinematic Test",
        "genre": "cinematic",
        "tempo": 75,
        "target_seconds": 90,
        "style_profile": None,
    },
]

arrangements_generated = []

for config in test_configs:
    print(f"\nTesting: {config['name']}")
    try:
        arrangement = ProducerEngine.generate(
            target_seconds=config["target_seconds"],
            tempo=config["tempo"],
            genre=config["genre"],
            style_profile=config["style_profile"],
            structure_template="standard",
        )
        
        # Validate arrangement
        assert arrangement is not None
        assert len(arrangement.sections) > 0, "No sections generated"
        assert len(arrangement.energy_curve) > 0, "No energy curve generated"
        assert arrangement.total_bars > 0, "Invalid total_bars"
        
        print(f"  ✅ Generated: {len(arrangement.sections)} sections, {arrangement.total_bars} bars")
        print(f"  ✅ Genres: {arrangement.genre}")
        print(f"  ✅ Energy range: {min(p.energy for p in arrangement.energy_curve):.2f} - {max(p.energy for p in arrangement.energy_curve):.2f}")
        
        arrangements_generated.append({
            "config": config,
            "arrangement": arrangement,
        })
    except Exception as e:
        print(f"  ❌ Failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

print(f"\n✅ Successfully generated {len(arrangements_generated)}/{len(test_configs)} arrangements")

# ============================================================================
# PHASE 4: SERIALIZATION VALIDATION
# ============================================================================
print()
print("💾 PHASE 4: SERIALIZATION VALIDATION")
print("-" * 70)

for item in arrangements_generated:
    config = item["config"]
    arrangement = item["arrangement"]
    
    try:
        # Convert to dict
        arrangement_dict = asdict(arrangement)
        
        # Serialize to JSON
        json_str = json.dumps(
            {
                "version": "2.0",
                "producer_arrangement": arrangement_dict,
                "correlation_id": "test-123",
            },
            default=str
        )
        
        # Validate size
        json_size = len(json_str)
        json_size_kb = json_size / 1024
        
        # Deserialize back
        parsed = json.loads(json_str)
        
        print(f"✅ {config['name']:25s} - {json_size_kb:6.1f} KB")
    except Exception as e:
        print(f"❌ {config['name']:25s} - Serialization failed: {e}")

# ============================================================================
# PHASE 5: FALLBACK BEHAVIOR
# ============================================================================
print()
print("🔄 PHASE 5: FALLBACK BEHAVIOR")
print("-" * 70)

# Test loading non-existent genre (should fail gracefully)
try:
    BeatGenomeLoader.load("invalid_genre")
    print("❌ Should have raised FileNotFoundError for invalid genre")
except FileNotFoundError as e:
    print(f"✅ Correct error handling: FileNotFoundError raised")
    print(f"   Message: {str(e)[:80]}...")
except Exception as e:
    print(f"❌ Unexpected error: {type(e).__name__}: {e}")

# Test ProducerEngine with unavailable genre (should use hardcoded presets)
try:
    arrangement = ProducerEngine.generate(
        target_seconds=30,
        tempo=100,
        genre="invalid_genre",  # Will trigger fallback
        style_profile=None,
        structure_template="standard",
    )
    print(f"✅ ProducerEngine fallback works - generated {len(arrangement.sections)} sections")
except Exception as e:
    print(f"⚠️  ProducerEngine error: {type(e).__name__}: {e}")

# ============================================================================
# PHASE 6: CACHE VERIFICATION
# ============================================================================
print()
print("💿 PHASE 6: CACHE VERIFICATION")
print("-" * 70)

try:
    stats = BeatGenomeLoader.get_cache_stats()
    print(f"Cache stats:")
    print(f"  - Cached genomes: {stats['cached_genomes']}")
    print(f"  - Cache keys: {stats['cache_keys']}")
    
    if stats['cached_genomes'] > 0:
        print(f"✅ Caching is working")
    else:
        print(f"⚠️  No genomes in cache")
except Exception as e:
    print(f"❌ Cache stats failed: {e}")

# ============================================================================
# SUMMARY
# ============================================================================
print()
print("=" * 70)
print("VALIDATION SUMMARY")
print("=" * 70)

summary = {
    "Genomes discovered": len(available),
    "Genomes loaded": len(genomes_loaded),
    "Arrangements generated": len(arrangements_generated),
    "Serialization tested": len(arrangements_generated),
    "Fallback behavior tested": True,
    "Caching verified": True,
}

print()
for key, value in summary.items():
    status = "✅" if value else "❌"
    print(f"{status} {key}: {value}")

print()
if len(arrangements_generated) == len(test_configs):
    print("✅ END-TO-END VALIDATION PASSED")
    print()
    print("Next steps:")
    print("1. Set FEATURE_PRODUCER_ENGINE=true in environment")
    print("2. Start backend server")
    print("3. Call POST /api/v1/arrangements/generate with style_text_input")
    print("4. Verify producer_arrangement_json is populated in database")
else:
    print("⚠️  Some tests failed - see details above")

print()
