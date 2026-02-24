#!/usr/bin/env python
"""
Direct database schema fix without Alembic (for development).
This script directly adds missing columns to the loops table.
"""

import sys
import os
from pathlib import Path

# Set UTF-8 encoding for output
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import inspect, text
from app.db import engine, SessionLocal
from app.models.test_model import Base

def get_current_columns():
    """Get columns in loops table."""
    inspector = inspect(engine)
    if "loops" not in inspector.get_table_names():
        return set()
    return {col['name'] for col in inspector.get_columns('loops')}

def add_missing_columns():
    """Add missing columns to loops table."""
    current_cols = get_current_columns()
    required_cols = {
        'filename', 'title', 'bpm', 'musical_key', 'duration_seconds'
    }
    
    missing_cols = required_cols - current_cols
    if not missing_cols:
        print("[OK] All required columns already exist")
        return True
    
    print(f"[ERROR] Missing columns: {', '.join(sorted(missing_cols))}")
    
    # Map columns to their SQL definitions
    col_definitions = {
        'filename': "VARCHAR",
        'title': "VARCHAR",
        'bpm': "INTEGER",
        'musical_key': "VARCHAR",
        'duration_seconds': "FLOAT"
    }
    
    db = SessionLocal()
    try:
        for col_name in sorted(missing_cols):
            col_type = col_definitions[col_name]
            
            # Use dialect-specific SQL
            if "sqlite" in engine.url.drivername:
                sql = f"ALTER TABLE loops ADD COLUMN {col_name} {col_type} DEFAULT NULL"
            elif "postgresql" in engine.url.drivername:
                sql = f"ALTER TABLE loops ADD COLUMN {col_name} {col_type} DEFAULT NULL"
            elif "mysql" in engine.url.drivername:
                sql = f"ALTER TABLE loops ADD COLUMN {col_name} {col_type} DEFAULT NULL"
            else:
                sql = f"ALTER TABLE loops ADD COLUMN {col_name} {col_type} DEFAULT NULL"
            
            try:
                print(f"   + Adding column: {col_name}...", end=" ")
                db.execute(text(sql))
                print("✅")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    print("(already exists)")
                else:
                    print(f"❌ Error: {e}")
                    return False
        
        db.commit()
        print("\n✅ All missing columns added successfully")
        return True
        
    except Exception as e:
        print(f"\n❌ Failed to add columns: {e}")
        db.rollback()
        return False
    finally:
        db.close()

def verify_schema():
    """Verify the schema is complete."""
    print("\n" + "="*60)
    print("[OK] VERIFICATION")
    print("="*60)
    
    inspector = inspect(engine)
    if "loops" not in inspector.get_table_names():
        print("[ERROR] loops table does not exist")
        return False
    
    current_cols = get_current_columns()
    required_cols = {
        'id', 'name', 'tempo', 'key', 'filename', 'file_url', 'title',
        'bpm', 'musical_key', 'genre', 'duration_seconds', 'created_at'
    }
    
    missing = required_cols - current_cols
    if missing:
        print(f"[ERROR] Still missing: {', '.join(sorted(missing))}")
        return False
    
    print("[OK] All required columns present in loops table:")
    for col in sorted(current_cols):
        print(f"   - {col}")
    return True

def main():
    """Main schema fix workflow."""
    print("\n" + "="*60)
    print("LoopArchitect Database Schema Direct Fix")
    print("="*60)
    
    current_cols = get_current_columns()
    print(f"\nCurrent columns in loops table: {', '.join(sorted(current_cols))}")
    
    if not add_missing_columns():
        return False
    
    return verify_schema()

if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\n[OK] Database schema update complete!")
        else:
            print("\n[WARN] Database schema update failed")
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        sys.exit(1)
