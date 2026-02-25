# Phase B: Audio Arrangement Generation - Implementation Complete

## Overview

Phase B Audio Arrangement Generation is a complete system for generating full-length instrumental audio arrangements from uploaded loops. The system uses asynchronous background jobs to process arrangements and provides downloadable WAV files.

## Architecture

### Components

1. **Database Model** (`app/models/arrangement.py`):
   - Arrangement table with 13 columns
   - Tracks arrangement job status (queued, processing, complete, failed)
   - Stores arrangement metadata and generated timeline JSON
   - Foreign key relationship to Loop model

2. **API Routes** (`app/routes/arrangements.py`):
   - `POST /api/v1/arrangements/generate` - Submit arrangement generation request
   - `GET /api/v1/arrangements/{id}` - Get arrangement status
   - `GET /api/v1/arrangements/{id}/download` - Download generated audio file

3. **Audio Engine** (`app/services/arrangement_engine.py`):
   - `generate_arrangement()` - Main function for audio generation
   - Loads loop, repeats to target duration, applies section-based effects
   - Returns output file URL and timeline JSON

4. **Background Job** (`app/services/arrangement_jobs.py`):
   - `run_arrangement_job()` - Async background task processor
   - Handles database session management
   - Error handling and status updates

5. **Pydantic Schemas** (`app/schemas/arrangement.py`):
   - Audio arrangement request/response models
   - Status tracking and download response models

## API Endpoints

### 1. Generate Arrangement

```http
POST /api/v1/arrangements/generate HTTP/1.1

{
  "loop_id": 1,
  "target_seconds": 60,
  "genre": "electronic",
  "intensity": "medium",
  "include_stems": false
}
```

**Response (202 Accepted):**
```json
{
  "arrangement_id": 123,
  "loop_id": 1,
  "status": "queued",
  "created_at": "2024-01-15T10:30:00Z"
}
```

### 2. Get Arrangement Status

```http
GET /api/v1/arrangements/123 HTTP/1.1
```

**Response (200):**
```json
{
  "id": 123,
  "loop_id": 1,
  "status": "processing",
  "target_seconds": 60,
  "genre": "electronic",
  "intensity": "medium",
  "include_stems": false,
  "output_file_url": null,
  "error_message": null,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:30:05Z"
}
```

### 3. Download Arrangement

```http
GET /api/v1/arrangements/123/download HTTP/1.1
```

**Responses:**
- `200 OK` - Returns WAV file (when status=complete)
- `409 Conflict` - Still processing (when status=queued or processing)
- `400 Bad Request` - Generation failed (when status=failed)
- `404 Not Found` - Arrangement doesn't exist

## Arrangement Structure & Effects

The generated arrangement uses a standard 5-section structure:
- **Intro** (10%): Fade-in effect
- **Verse 1** (30%): Full volume
- **Hook** (30%): Full volume  
- **Verse 2** (20%): Full volume
- **Outro** (10%): Fade-out effect

### Effects Applied by Intensity

**Low Intensity:**
- Intro fade-in, outro fade-out
- No dropouts
- Gain variations (±1-2dB at bar intervals)

**Medium Intensity:**
- Intro fade-in, outro fade-out
- Periodic dropouts every 8 beats (0.25 beat duration)
- Gain variations (±1-2dB at bar intervals)

**High Intensity:**
- Intro fade-in, outro fade-out
- Periodic dropouts every 4 beats (0.5 beat duration)
- Gain variations (±1-2dB at bar intervals)

## Database Schema

### Arrangements Table

```sql
CREATE TABLE arrangements (
  id INTEGER PRIMARY KEY,
  loop_id INTEGER NOT NULL FOREIGN KEY REFERENCES loops(id),
  status VARCHAR NOT NULL DEFAULT 'queued',
  target_seconds INTEGER NOT NULL,
  genre VARCHAR,
  intensity VARCHAR,
  include_stems BOOLEAN DEFAULT FALSE,
  output_file_url VARCHAR,
  stems_zip_url VARCHAR,
  arrangement_json TEXT,
  error_message TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_arrangement_loop_id ON arrangements(loop_id);
CREATE INDEX idx_arrangement_loop_status ON arrangements(loop_id, status);
```

## File Storage

- **Input**: `/uploads/{filename}` (from Loop model)
- **Output**: `/renders/arrangements/{uuid}.wav` (generated WAV file)
- **Access**:
  - Input files: Served as static files via `/uploads` mount
  - Output files: Downloaded via `/api/v1/arrangements/{id}/download` endpoint

## Status Workflow

```
[queued] → [processing] → [complete]
                       ↓
                    [failed]
```

## Error Handling

The system handles multiple error scenarios:

1. **Loop Not Found** (404)
   - Returned if specified loop_id doesn't exist

2. **Invalid Parameters** (422)
   - target_seconds outside 10-3600 range
   - Missing required fields

3. **Processing Errors** (400/500)
   - Audio file not found
   - Audio processing failed
   - Database errors

4. **Download Errors** (409)
   - Arrangement still processing or queued
   - File not found on disk after completion

## Testing

### Unit Tests

**Route Tests** (`tests/routes/test_arrangements.py`):
- Generate arrangement creation
- Loop validation
- Duration range validation
- Status retrieval
- Download access control
- Full workflow integration

**Service Tests** (`tests/services/test_arrangement_engine.py`):
- Section calculation
- Timeline JSON generation
- Audio effects application
- Dropout generation
- Gain variations
- Different intensity levels
- Different genres

### Running Tests

```bash
# All arrangement tests
pytest tests/routes/test_arrangements.py tests/services/test_arrangement_engine.py -v

# Specific test
pytest tests/routes/test_arrangements.py::TestArrangementGeneration -v

# With coverage
pytest tests/routes/test_arrangements.py --cov=app.routes.arrangements
```

## Example Workflow

### 1. Upload a Loop
```bash
# Upload via POST /api/v1/loops (returns loop_id=42)
```

### 2. Request Arrangement Generation
```bash
curl -X POST http://localhost:8000/api/v1/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 42,
    "target_seconds": 120,
    "genre": "electronic",
    "intensity": "high"
  }'

# Returns: {"arrangement_id": 101, "status": "queued", ...}
```

### 3. Poll Status
```bash
curl http://localhost:8000/api/v1/arrangements/101

# Poll until status changes to "complete"
for i in {1..30}; do
  curl http://localhost:8000/api/v1/arrangements/101 | jq .status
  sleep 2
done
```

### 4. Download Audio
```bash
curl http://localhost:8000/api/v1/arrangements/101/download \
  -o arrangement_101.wav
```

## Configuration

### Environment Variables

No special configuration required beyond existing database setup. The system uses:
- `DATABASE_URL` - Existing database configuration
- Local file system for `/uploads` and `/renders` directories

### Optional Tuning

Via `app/services/arrangement_engine.py`:
- `_calculate_sections()` - Adjust section percentages (default: 10/30/30/20/10)
- `_add_dropouts()` - Adjust dropout intervals and durations
- `_add_gain_variations()` - Adjust gain variation ranges (-2 to +2 dB)

## Performance Considerations

### CPU Usage
- Audio processing is CPU-intensive
- Uses numpy and pydub libraries
- FFmpeg dependency for codec handling

### Scalability
- Each arrangement job runs in a separate background task
- No blocking in request handlers
- Multiple concurrent arrangements supported
- Consider adding queue depth monitoring for production

### File Storage
- WAV files can be large (1MB+ for 5+ minute arrangements)
- Monitor disk space in `/renders/arrangements`
- Consider implementing file cleanup/archival strategy

## Dependencies

### New Dependencies
```
pydub==0.25.1      # Audio manipulation
ffmpeg-python==0.2.0  # FFmpeg wrapper
```

### Existing Dependencies Used
```
fastapi           # Web framework
sqlalchemy        # ORM
alembic           # Database migrations
librosa>=0.10.0  # BPM detection (already present)
numpy>=1.24.0    # Numerical operations (already present)
```

## Database Migration

Migrations are applied automatically on startup, but can be run manually:

```bash
# Apply all pending migrations
alembic upgrade head

# Revert to previous migration
alembic downgrade -1

# Check migration status
alembic current
alembic history
```

## Deployment

### Render.com Deployment
The feature is compatible with Render.com deployment:
- Database migrations run automatically on startup
- FFmpeg available in default Render environment
- WAV files stored in app directory (not persistent across deploys)

### Persistent Storage Recommendation
For production, consider:
1. AWS S3 for output files
2. CloudFlare R2 for cost-effective storage
3. Database for metadata (already implemented)

## Monitoring & Debugging

### Check Arrangement Status
```bash
sqlite3 test.db
SELECT id, loop_id, status, error_message FROM arrangements;
```

### View Recent Errors
```bash
sqlite3 test.db
SELECT id, created_at, error_message FROM arrangements WHERE status='failed';
```

### Monitor Disk Usage
```bash
du -sh renders/arrangements/
ls -lh renders/arrangements/ | head -20
```

## Future Enhancements

1. **Stems Generation**: Generate separate audio tracks for mixing
2. **Advanced Effects**: EQ, compression, reverb per section
3. **Machine Learning**: Automatic intensity/structure suggestions
4. **Real-time Streaming**: WebSocket updates during generation
5. **Audio Presets**: Pre-defined effect chains by genre
6. **Batch Processing**: Generate multiple arrangements simultaneously
7. **File Caching**: Reuse arrangements with identical parameters

## Troubleshooting

### FFmpeg Not Found
```bash
# Install FFmpeg
# Windows: choco install ffmpeg
# macOS: brew install ffmpeg
# Linux: sudo apt install ffmpeg
```

### Arrangement Stuck in "Processing"
- Check logs for errors
- Verify /uploads file exists
- Check disk space
- Restart application to reprocess

### Download Returns 500
- Verify file exists: `ls -l renders/arrangements/{uuid}.wav`
- Check file permissions
- Check disk space

### Database Lock
- Ensure only single FastAPI instance is running
- SQLite has limited concurrency
- Consider PostgreSQL for production

---

**Version**: 1.0.0  
**Last Updated**: 2024
**Status**: Production Ready
