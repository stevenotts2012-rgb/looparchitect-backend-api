# Database Schema Migration Summary

## Issue Fixed
**Error:** `psycopg2.errors.UndefinedColumn: column "filename" of relation "loops" does not exist`

The SQLAlchemy models defined new columns but the database schema hadn't been updated, causing runtime errors on Render's PostgreSQL.

## Solution Implemented

### 1. **Alembic Migration System Setup**
- Initialized Alembic in `/migrations` directory
- Configured `alembic.ini` to use app settings
- Updated `migrations/env.py` to use `app.config.settings` and `app.models.test_model.Base`

### 2. **Schema Corrections**
Added missing columns to `loops` table:
- `filename` (VARCHAR) - Local uploaded file name
- `file_url` (VARCHAR) - Full URL to file endpoint
- `title` (VARCHAR) - Loop title/name
- `bpm` (INTEGER) - Beats per minute
- `musical_key` (VARCHAR) - Musical key (e.g., "C Major")
- `genre` (VARCHAR) - Genre classification
- `duration_seconds` (FLOAT) - Calculated duration
- `created_at` (DATETIME) - Auto-populated timestamp

### 3. **Dual-Mode Migration Strategy**

**For Development (SQLite):**
- `fix_schema.py` - Direct SQL schema fixes (no Alembic dependency)
- Adds missing columns using SQLAlchemy ORM
- Idempotent (safe to run multiple times)

**For Production (PostgreSQL/Render):**
- `migrations/versions/001_add_missing_loop_columns.py` - Alembic migration
- Runs automatically on app startup via `main.py:run_migrations()`
- Handles both online and offline modes

### 4. **Files Created/Modified**

**Created:**
- `alembic.ini` - Alembic configuration
- `migrations/` - Migration directory with `env.py`, `script.py.mako`, `README`
- `migrations/versions/001_add_missing_loop_columns.py` - Schema migration
- `fix_schema.py` - Direct schema fix utility
- `migrate.py` - Migration diagnostic tool

**Modified:**
- `requirements.txt` - Added `alembic>=1.13.0`
- `main.py` - Added `run_migrations()` call on app startup
- `migrations/env.py` - Configured to use app settings and models

### 5. **Schema Verification**

**Before:**
```
loops table columns:
- id, name, tempo, key, genre, file_url, created_at
Missing: filename, title, bpm, musical_key, duration_seconds
```

**After:**
```
loops table columns:
✅ id, name, tempo, key, filename, file_url, title, bpm, 
   musical_key, genre, duration_seconds, created_at
```

## Migration Workflow

### Local Development
Run when schema changes are needed:
```powershell
python fix_schema.py
```

### Production (Render)
Migrations automatically run on app startup:
1. App starts → `lifespan()` → `run_migrations()`
2. Alembic upgrades to latest version
3. Database schema updated
4. App continues normal operation

### Manual Alembic Commands
```bash
# Generate migration from model changes
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

## Backwards Compatibility

All new columns are **nullable** (`nullable=True`):
- Existing loops work without new columns
- New loops can populate all fields
- No data loss on migration

## Testing Endpoints

The following endpoints now work without schema errors:

```
POST /api/v1/loops/upload       - Upload file + create loop record
POST /api/v1/upload             - Upload file only (file storage)
POST /api/v1/loops/{id}/render  - Render loop with new fields
PATCH /api/v1/loops/{id}        - Update loop with new fields
GET /api/v1/loops               - List all loops with new data
```

## Related Database Files

- `app/models/loop.py` - SQLAlchemy model with all columns
- `app/models/schemas.py` - Pydantic schemas for API responses
- `app/db.py` - Database session factory and initialization
- `app/config.py` - Database URL configuration with Render support

## Notes

- Migrations are idempotent (can be run multiple times safely)
- Error handling prevents migration failure on missing columns
- SQLite (dev) and PostgreSQL (prod) both supported
- No manual migration steps needed - automatic on app startup
