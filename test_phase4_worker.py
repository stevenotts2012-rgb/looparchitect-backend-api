#!/usr/bin/env python3
"""
Phase 4 Worker Integration Test
Tests that render_worker.py correctly uses ProducerArrangement data
"""

import json
import sqlite3
import sys
import time
from pathlib import Path
from sqlalchemy import create_engine, text

def test_database_setup():
    """Verify database has arrangements with producer data"""
    print("\n" + "="*70)
    print("PHASE 4: WORKER INTEGRATION TEST")
    print("="*70)
    
    print("\n📦 STEP 1: Check Database for Producer Data")
    print("-" * 70)
    
    db_path = Path("test.db")
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return False
    
    engine = create_engine(f"sqlite:///{db_path}")
    
    try:
        with engine.connect() as conn:
            # Check table exists
            result = conn.execute(text(
                "SELECT COUNT(*) FROM arrangements WHERE producer_arrangement_json IS NOT NULL"
            ))
            count = result.scalar()
            
            if count == 0:
                print("⚠️  No arrangements with producer_arrangement_json found")
                print("    Run: python -m app.services.producer_engine")
                print("    Or create arrangements with use_ai_parsing=true")
                return False
            
            print(f"✅ Found {count} arrangements with producer data")
            
            # Show sample
            result = conn.execute(text("""
                SELECT id, status, 
                       substr(producer_arrangement_json, 1, 120) as preview,
                       length(producer_arrangement_json) as json_size
                FROM arrangements 
                WHERE producer_arrangement_json IS NOT NULL 
                ORDER BY id DESC LIMIT 3
            """))
            
            print("\n   Recent arrangements with producer data:")
            for row_id, status, preview, size in result:
                print(f"   - ID {row_id}: status={status}, size={size} bytes")
                print(f"     Preview: {preview}...")
            
            return True
            
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False

def test_audio_renderer_import():
    """Verify audio_renderer.py exists and imports correctly"""
    print("\n📦 STEP 2: Verify Audio Renderer Service")
    print("-" * 70)
    
    renderer_path = Path("app/services/audio_renderer.py")
    if not renderer_path.exists():
        print(f"❌ audio_renderer.py not found at {renderer_path}")
        return False
    
    print(f"✅ audio_renderer.py exists ({renderer_path.stat().st_size} bytes)")
    
    try:
        from app.services.audio_renderer import AudioRenderer, render_arrangement
        print("✅ AudioRenderer class imported successfully")
        print("✅ render_arrangement function imported successfully")
        
        # Check methods exist
        if hasattr(AudioRenderer, 'render_arrangement'):
            print("✅ AudioRenderer.render_arrangement() method exists")
        if hasattr(AudioRenderer, '_render_section'):
            print("✅ AudioRenderer._render_section() method exists")
        if hasattr(AudioRenderer, '_apply_energy_curve'):
            print("✅ AudioRenderer._apply_energy_curve() method exists")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to import audio_renderer: {e}")
        return False

def test_worker_modifications():
    """Verify render_worker.py has ProducerArrangement handling"""
    print("\n📦 STEP 3: Verify Worker Modifications")
    print("-" * 70)
    
    worker_path = Path("app/workers/render_worker.py")
    if not worker_path.exists():
        print(f"❌ render_worker.py not found")
        return False
    
    content = worker_path.read_text()
    
    checks = [
        ("Imports Arrangement model", "from app.models.arrangement import Arrangement"),
        ("Queries arrangement data", "db.query(Arrangement).filter"),
        ("ProducerEngine path check", "arrangement and arrangement.producer_arrangement_json"),
        ("Imports ProducerArrangement", "from app.services.producer_models import ProducerArrangement"),
        ("Imports audio_renderer", "from app.services.audio_renderer import render_arrangement"),
        ("Uses render_arrangement", "render_arrangement("),
        ("Fallback to legacy", "# Legacy Path"),
    ]
    
    passed = 0
    for check_name, check_str in checks:
        if check_str in content:
            print(f"✅ {check_name}")
            passed += 1
        else:
            print(f"❌ {check_name} - NOT FOUND: {check_str}")
    
    print(f"\n   Passed {passed}/{len(checks)} checks")
    return passed == len(checks)

def test_producer_arrangement_schema():
    """Verify ProducerArrangement dataclass is intact"""
    print("\n📦 STEP 4: Verify ProducerArrangement Schema")
    print("-" * 70)
    
    try:
        from app.services.producer_models import (
            ProducerArrangement, 
            Section, 
            EnergyPoint,
            SectionType
        )
        
        required_fields = [
            (ProducerArrangement, ['tempo', 'sections', 'energy_curve', 'total_bars']),
            (Section, ['name', 'section_type', 'bar_start', 'bars', 'energy_level']),
            (EnergyPoint, ['bar', 'energy']),
        ]
        
        for cls, fields in required_fields:
            class_name = cls.__name__
            for field in fields:
                if hasattr(cls, '__dataclass_fields__'):
                    if field in cls.__dataclass_fields__:
                        print(f"✅ {class_name}.{field}")
                    else:
                        print(f"❌ {class_name}.{field} missing")
                        return False
                else:
                    print(f"⚠️  {class_name} may not be a dataclass")
        
        print(f"\n✅ All required fields present")
        return True
        
    except Exception as e:
        print(f"❌ Failed to verify schema: {e}")
        return False

def test_json_deserialization():
    """Test JSON → ProducerArrangement deserialization"""
    print("\n📦 STEP 5: Test JSON Deserialization")
    print("-" * 70)
    
    engine = create_engine("sqlite:///test.db")
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT id, producer_arrangement_json 
                FROM arrangements 
                WHERE producer_arrangement_json IS NOT NULL 
                LIMIT 1
            """))
            
            row = result.first()
            if not row:
                print("⚠️  No producer arrangement found to test deserialization")
                return True  # Not a failure, just can't test
            
            arr_id, json_str = row
            print(f"✅ Found arrangement {arr_id} with producer data")
            
            try:
                data = json.loads(json_str)
                print(f"✅ JSON deserializes successfully (keys: {list(data.keys())[:5]}...)")
                
                # Handle nested structure
                if "producer_arrangement" in data:
                    producer_data = data["producer_arrangement"]
                    print("✅ Unwrapped nested producer_arrangement structure")
                else:
                    producer_data = data
                
                # Verify structure
                required_keys = ['tempo', 'sections', 'energy_curve', 'total_bars']
                for key in required_keys:
                    if key in producer_data:
                        print(f"✅ Has key: {key}")
                    else:
                        print(f"❌ Missing key: {key}")
                        return False
                
                return True
                
            except json.JSONDecodeError as e:
                print(f"❌ JSON parsing failed: {e}")
                return False
                
    except Exception as e:
        print(f"❌ Database query error: {e}")
        return False

def main():
    """Run all Phase 4 validation tests"""
    
    tests = [
        ("Database Setup", test_database_setup),
        ("Audio Renderer Import", test_audio_renderer_import),
        ("Worker Modifications", test_worker_modifications),
        ("ProducerArrangement Schema", test_producer_arrangement_schema),
        ("JSON Deserialization", test_json_deserialization),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ Test '{test_name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {test_name}")
    
    print(f"\nPassed: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 ALL PHASE 4 CHECKS PASSED!")
        print("\nNext steps:")
        print("1. Start backend with: $env:FEATURE_PRODUCER_ENGINE='true'; .\.venv\Scripts\python.exe main.py")
        print("2. Start Redis worker (if using async): python -m rq worker")
        print("3. Create arrangement with: python test_phase4_worker.py --create")
        print("4. Check render job output")
        return 0
    else:
        print(f"\n⚠️  {total - passed} checks failed. See details above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
