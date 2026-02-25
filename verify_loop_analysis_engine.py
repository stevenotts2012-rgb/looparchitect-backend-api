"""
Quick Verification Script for Loop Analysis Engine

This script performs basic checks to ensure the Loop Analysis Engine
implementation is complete and properly wired.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


def check_imports():
    """Verify all required modules can be imported."""
    print("=== Checking Imports ===")
    
    try:
        from app.services.loop_analyzer import loop_analyzer
        print("✅ loop_analyzer imported successfully")
    except Exception as e:
        print(f"❌ Failed to import loop_analyzer: {e}")
        return False
    
    try:
        from app.models.loop import Loop
        print("✅ Loop model imported successfully")
    except Exception as e:
        print(f"❌ Failed to import Loop model: {e}")
        return False
    
    try:
        from app.routes.loops import router
        print("✅ loops router imported successfully")
    except Exception as e:
        print(f"❌ Failed to import loops router: {e}")
        return False
    
    return True


def check_loop_model():
    """Verify Loop model has all required analysis fields."""
    print("\n=== Checking Loop Model ===")
    
    try:
        from app.models.loop import Loop
        
        required_fields = ['bpm', 'bars', 'musical_key', 'duration_seconds']
        model_columns = [col.name for col in Loop.__table__.columns]
        
        missing_fields = []
        for field in required_fields:
            if field in model_columns:
                print(f"✅ Loop.{field} exists")
            else:
                print(f"❌ Loop.{field} missing")
                missing_fields.append(field)
        
        return len(missing_fields) == 0
    
    except Exception as e:
        print(f"❌ Error checking Loop model: {e}")
        return False


def check_analyzer_methods():
    """Verify LoopAnalyzer has required methods."""
    print("\n=== Checking LoopAnalyzer Methods ===")
    
    try:
        from app.services.loop_analyzer import loop_analyzer
        
        required_methods = ['analyze_from_s3', 'analyze_from_file', '_analyze_file', '_detect_bpm', '_detect_key']
        
        missing_methods = []
        for method in required_methods:
            if hasattr(loop_analyzer, method):
                print(f"✅ loop_analyzer.{method}() exists")
            else:
                print(f"❌ loop_analyzer.{method}() missing")
                missing_methods.append(method)
        
        return len(missing_methods) == 0
    
    except Exception as e:
        print(f"❌ Error checking LoopAnalyzer: {e}")
        return False


def check_routes_integration():
    """Verify loop_analyzer is imported in routes."""
    print("\n=== Checking Routes Integration ===")
    
    try:
        routes_file = Path(__file__).parent / 'app' / 'routes' / 'loops.py'
        
        if not routes_file.exists():
            print(f"❌ Routes file not found: {routes_file}")
            return False
        
        content = routes_file.read_text()
        
        # Check for import
        if 'from app.services.loop_analyzer import loop_analyzer' in content:
            print("✅ loop_analyzer imported in routes")
        else:
            print("❌ loop_analyzer not imported in routes")
            return False
        
        # Check for usage
        if 'await loop_analyzer.analyze_from_s3' in content:
            print("✅ loop_analyzer.analyze_from_s3() called in routes")
        else:
            print("❌ loop_analyzer.analyze_from_s3() not called in routes")
            return False
        
        # Check for error handling
        if 'Audio analysis failed (non-fatal)' in content:
            print("✅ Graceful error handling present")
        else:
            print("❌ Graceful error handling missing")
            return False
        
        return True
    
    except Exception as e:
        print(f"❌ Error checking routes integration: {e}")
        return False


def check_migrations():
    """Check that required migrations exist."""
    print("\n=== Checking Migrations ===")
    
    migrations_dir = Path(__file__).parent / 'migrations' / 'versions'
    
    if not migrations_dir.exists():
        print(f"❌ Migrations directory not found: {migrations_dir}")
        return False
    
    required_migrations = {
        '001_add_missing_loop_columns.py': ['bpm', 'musical_key', 'duration_seconds'],
        '006_add_bars_column.py': ['bars']
    }
    
    all_found = True
    
    for migration_file, fields in required_migrations.items():
        migration_path = migrations_dir / migration_file
        
        if not migration_path.exists():
            print(f"❌ Migration not found: {migration_file}")
            all_found = False
            continue
        
        content = migration_path.read_text()
        
        missing_fields = []
        for field in fields:
            if field in content:
                print(f"✅ Migration {migration_file} includes '{field}'")
            else:
                print(f"❌ Migration {migration_file} missing '{field}'")
                missing_fields.append(field)
        
        if missing_fields:
            all_found = False
    
    return all_found


def main():
    """Run all verification checks."""
    print("Loop Analysis Engine - Implementation Verification\n")
    print("=" * 60)
    
    checks = [
        ("Imports", check_imports),
        ("Loop Model", check_loop_model),
        ("Analyzer Methods", check_analyzer_methods),
        ("Routes Integration", check_routes_integration),
        ("Migrations", check_migrations),
    ]
    
    results = []
    
    for check_name, check_func in checks:
        try:
            passed = check_func()
            results.append((check_name, passed))
        except Exception as e:
            print(f"\n❌ {check_name} check crashed: {e}")
            results.append((check_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("=== VERIFICATION SUMMARY ===\n")
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for check_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {check_name}")
    
    print(f"\n{passed_count}/{total_count} checks passed")
    
    if passed_count == total_count:
        print("\n🎉 All verification checks passed! Loop Analysis Engine is ready.")
        return 0
    else:
        print(f"\n⚠️ {total_count - passed_count} checks failed. Please review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
