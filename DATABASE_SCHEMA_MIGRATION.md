# Database Schema Migration

## Required Changes for Stem Producer Engine

### Overview
The stem producer engine requires 6 new columns across 2 existing tables. All columns are **nullable** to maintain backward compatibility with existing data.

## Migration Script

### PostgreSQL Migration

```sql
-- ============================================================================
-- PHASE 9: Database Schema Extensions for Stem Producer Engine
-- ============================================================================
-- Created: [CURRENT_DATE]
-- Purpose: Add stem metadata storage to Loop and Arrangement tables
-- Compatibility: Backward compatible (all nullable, no default changes)
-- Rollback: See ROLLBACK section below

BEGIN;

-- ============================================================================
-- Table: loops
-- ============================================================================
-- New columns for stem pack metadata

ALTER TABLE loops ADD COLUMN IF NOT EXISTS is_stem_pack VARCHAR(10) NULL;
-- Values: "true" or "false", NULL if not yet analyzed

ALTER TABLE loops ADD COLUMN IF NOT EXISTS stem_roles_json TEXT NULL;
-- Example: '{"detected_roles": ["drums", "bass", "melody"], "confidence": 0.95}'

ALTER TABLE loops ADD COLUMN IF NOT EXISTS stem_files_json TEXT NULL;
-- Example: '{"drums": {"filename": "drums.wav", "url": "s3://...", "duration_ms": 45360}, ...}'

ALTER TABLE loops ADD COLUMN IF NOT EXISTS stem_validation_json TEXT NULL;
-- Example: '{"is_valid": true, "errors": [], "sample_rate": 44100, "channels": 2}'

-- Add indexes for common queries
CREATE INDEX IF NOT EXISTS idx_loops_is_stem_pack ON loops(is_stem_pack);

-- ============================================================================
-- Table: arrangements
-- ============================================================================
-- New columns for stem rendering metadata

ALTER TABLE arrangements ADD COLUMN IF NOT EXISTS stem_arrangement_json TEXT NULL;
-- Example: '{"sections": [...], "total_bars": 32, "hook_count": 3}'

ALTER TABLE arrangements ADD COLUMN IF NOT EXISTS stem_render_path VARCHAR(50) NULL;
-- Values: "stem" (used stems) or "loop" (fell back to single loop)

ALTER TABLE arrangements ADD COLUMN IF NOT EXISTS rendered_from_stems BOOLEAN NULL;
-- Values: true (stem path used) or false (loop fallback used)

-- Add indexes for common queries
CREATE INDEX IF NOT EXISTS idx_arrangements_stem_render_path ON arrangements(stem_render_path);
CREATE INDEX IF NOT EXISTS idx_arrangements_rendered_from_stems ON arrangements(rendered_from_stems);

-- ============================================================================
-- Verification
-- ============================================================================

-- List new columns to verify
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name IN ('loops', 'arrangements')
  AND column_name IN (
    'is_stem_pack', 'stem_roles_json', 'stem_files_json', 'stem_validation_json',
    'stem_arrangement_json', 'stem_render_path', 'rendered_from_stems'
  )
ORDER BY table_name, column_name;

COMMIT;
```

### Alembic Migration (Recommended for Railway)

Create migration file: `alembic/versions/[timestamp]_add_stem_producer_columns.py`

```python
"""Add stem producer engine columns

Revision ID: add_stem_producer_columns
Revises: [PREVIOUS_REVISION]
Create Date: 2024-01-15 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_stem_producer_columns'
down_revision = None  # Set to previous migration revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Loops table - stem metadata
    op.add_column('loops', sa.Column('is_stem_pack', sa.String(10), nullable=True))
    op.add_column('loops', sa.Column('stem_roles_json', sa.Text(), nullable=True))
    op.add_column('loops', sa.Column('stem_files_json', sa.Text(), nullable=True))
    op.add_column('loops', sa.Column('stem_validation_json', sa.Text(), nullable=True))
    
    # Create index
    op.create_index('idx_loops_is_stem_pack', 'loops', ['is_stem_pack'])
    
    # Arrangements table - stem rendering metadata
    op.add_column('arrangements', sa.Column('stem_arrangement_json', sa.Text(), nullable=True))
    op.add_column('arrangements', sa.Column('stem_render_path', sa.String(50), nullable=True))
    op.add_column('arrangements', sa.Column('rendered_from_stems', sa.Boolean(), nullable=True))
    
    # Create indexes
    op.create_index('idx_arrangements_stem_render_path', 'arrangements', ['stem_render_path'])
    op.create_index('idx_arrangements_rendered_from_stems', 'arrangements', ['rendered_from_stems'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_arrangements_rendered_from_stems', 'arrangements')
    op.drop_index('idx_arrangements_stem_render_path', 'arrangements')
    op.drop_index('idx_loops_is_stem_pack', 'loops')
    
    # Drop columns from arrangements
    op.drop_column('arrangements', 'rendered_from_stems')
    op.drop_column('arrangements', 'stem_render_path')
    op.drop_column('arrangements', 'stem_arrangement_json')
    
    # Drop columns from loops
    op.drop_column('loops', 'stem_validation_json')
    op.drop_column('loops', 'stem_files_json')
    op.drop_column('loops', 'stem_roles_json')
    op.drop_column('loops', 'is_stem_pack')
```

## Column Details

### loops table

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `is_stem_pack` | VARCHAR(10) | YES | "true" if upload detected as stem pack, "false" if single loop |
| `stem_roles_json` | TEXT | YES | JSON dict of detected stem roles and confidence |
| `stem_files_json` | TEXT | YES | JSON dict mapping roles to file paths and metadata |
| `stem_validation_json` | TEXT | YES | JSON dict with validation status, errors, sample rate, channels |

### arrangements table

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `stem_arrangement_json` | TEXT | YES | Complete section-by-section arrangement plan as JSON |
| `stem_render_path` | VARCHAR(50) | YES | "stem" or "loop" indicator of which renderer was used |
| `rendered_from_stems` | BOOLEAN | YES | true if stems were used, false if fallback to loop was used |

## Backward Compatibility

✅ **All columns are nullable** so existing data is unaffected
✅ **No column defaults changed** so old rows work as-is  
✅ **New queries check for NULL** so old code continues working
✅ **Fallback logic handles missing data** gracefully

## Migration Execution

### Development/Local

```bash
# Using Alembic
alembic upgrade head

# Or manual SQL
psql -U postgres -d looparchitect < migration.sql
```

### Production (Railway)

```bash
# Railway recommends:
railway run alembic upgrade head

# Or via Railway dashboard:
# 1. Connect to PostgreSQL
# 2. Run migration script
# 3. Verify with SELECT queries
```

### Verification

After migration, verify columns exist:

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name IN ('loops', 'arrangements')
ORDER BY table_name, column_name;
```

Expected count:
- loops table: existing columns + 4 new columns
- arrangements table: existing columns + 3 new columns

## Rollback Procedure

If needed to revert:

```sql
-- For Alembic
alembic downgrade -1

-- Or manual SQL
ALTER TABLE arrangements DROP COLUMN IF EXISTS rendered_from_stems;
ALTER TABLE arrangements DROP COLUMN IF EXISTS stem_render_path;
ALTER TABLE arrangements DROP COLUMN IF EXISTS stem_arrangement_json;

DROP INDEX IF EXISTS idx_loops_is_stem_pack;
ALTER TABLE loops DROP COLUMN IF EXISTS stem_validation_json;
ALTER TABLE loops DROP COLUMN IF EXISTS stem_files_json;
ALTER TABLE loops DROP COLUMN IF EXISTS stem_roles_json;
ALTER TABLE loops DROP COLUMN IF EXISTS is_stem_pack;
```

## Timeline

- **Development**: Run migration before testing new stem features
- **Staging**: Run migration and verify 48 hours before production
- **Production**: Schedule during low-traffic window (e.g., 2 AM UTC)

## Notes

- Migration is **idempotent** (`IF NOT EXISTS` clauses prevent errors on re-run)
- No data loss or transformation needed
- No long-running operations (safe even on large tables)
- Indexes improve query performance on common stems-related filters
- JSON columns provide flexibility for future schema evolution
