# Async Render Pipeline - Local Development Guide

## Overview

The async render pipeline allows clients to submit render jobs and poll for status without blocking the API. Jobs are queued in Redis and processed by background workers.

## Architecture

```
Client Request
    ↓
POST /api/v1/loops/{loop_id}/render-async
    ↓
Routes Handler → Job Service (enqueue with dedup)
    ↓
Redis Queue (RQ)
    ↓
Background Worker (render_loop_worker)
    ↓
Download audio → Render → Upload to S3
    ↓
GET /api/v1/jobs/{job_id} (poll for status)
    ↓
Return status + presigned URLs
```

## Setup - Local Development

### Prerequisites

- Python 3.9+
- Redis (local or Docker)
- PostgreSQL (or SQLite for dev)
- AWS S3 credentials

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Key additions for async:
- `redis==5.0.0` - Redis client
- `rq==1.15.0` - Job queue library
- `tenacity==8.2.0` - Retry decorator
- `python-json-logger==2.0.0` - Structured logging

### 2. Start Redis

**Option A: Local Redis Server**
```bash
# macOS/Linux
brew install redis
redis-server

# Windows (requires WSL or native install)
redis-server
```

**Option B: Docker**
```bash
docker run -d -p 6379:6379 redis:7-alpine
```

**Option C: Verify Redis Connection**
```bash
redis-cli ping
# Should respond: PONG
```

### 3. Set Environment Variables

```bash
# Required for async pipeline
export REDIS_URL="redis://localhost:6379/0"

# Required for audio storage
export AWS_S3_BUCKET="your-bucket"
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
export AWS_REGION="us-east-1"

# Optional: override defaults
export DATABASE_URL="sqlite:///./test.db"  # Dev only
```

On Windows PowerShell:
```powershell
$env:REDIS_URL = "redis://localhost:6379/0"
$env:AWS_S3_BUCKET = "your-bucket"
# ... etc
```

### 4. Run Database Migration

```bash
alembic upgrade head
```

This creates the `render_jobs` table with proper indexes.

### 5. Start Services (3 Terminal Windows)

**Terminal 1: API Server**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# Output: INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Terminal 2: Async Worker**
```bash
python -m app.workers
# Output: 
#   Worker started listening to render queue...
#   Waiting for jobs...
```

**Terminal 3: Test/Monitoring**
```bash
redis-cli monitor  # See Redis commands in real-time
# Or:
watch 'redis-cli INFO stats'  # Monitor stats every 2 seconds
```

## Usage - API Examples

### 1. Submit Render Job (Non-blocking)

```bash
# POST request with async flag
curl -X POST "http://localhost:8000/api/v1/loops/1/render-async" \
  -H "Content-Type: application/json" \
  -d '{
    "genre": "pop",
    "length_seconds": 30,
    "variations": ["Commercial", "Creative"],
    "intensity": "medium"
  }'
```

**Response (202 Accepted):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "loop_id": 1,
  "status": "queued",
  "created_at": "2025-01-15T14:23:00Z",
  "poll_url": "/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000",
  "deduplicated": false
}
```

### 2. Poll Job Status

```bash
curl -X GET "http://localhost:8000/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000"
```

**Response (While Processing):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "loop_id": 1,
  "status": "processing",
  "progress": 45,
  "progress_message": "Rendering Creative variation (2/3)",
  "started_at": "2025-01-15T14:23:05Z",
  "finished_at": null,
  "outputs": []
}
```

**Response (Completed):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "loop_id": 1,
  "status": "succeeded",
  "progress": 100,
  "started_at": "2025-01-15T14:23:05Z",
  "finished_at": "2025-01-15T14:23:35Z",
  "outputs": [
    {
      "name": "Commercial.wav",
      "s3_key": "renders/550e8400-e29b-41d4-a716-446655440000/Commercial.wav",
      "content_type": "audio/wav",
      "signed_url": "https://bucket.s3.amazonaws.com/renders/... (valid 1 hour)"
    },
    {
      "name": "Creative.wav",
      "s3_key": "renders/550e8400-e29b-41d4-a716-446655440000/Creative.wav",
      "content_type": "audio/wav",
      "signed_url": "https://bucket.s3.amazonaws.com/renders/... (valid 1 hour)"
    },
    {
      "name": "Experimental.wav",
      "s3_key": "renders/550e8400-e29b-41d4-a716-446655440000/Experimental.wav",
      "content_type": "audio/wav",
      "signed_url": "https://bucket.s3.amazonaws.com/renders/... (valid 1 hour)"
    }
  ]
}
```

### 3. List Jobs for a Loop

```bash
curl -X GET "http://localhost:8000/api/v1/loops/1/jobs?limit=10"
```

**Response:**
```json
{
  "loop_id": 1,
  "total": 5,
  "jobs": [
    {
      "job_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "succeeded",
      "progress": 100,
      "created_at": "2025-01-15T14:23:00Z",
      "outputs": [...]
    },
    {
      "job_id": "660f9511-f30c-52e5-b827-557766551111",
      "status": "processing",
      "progress": 60,
      "created_at": "2025-01-15T14:22:00Z",
      "outputs": []
    }
  ]
}
```

## Key Features

### 1. Idempotent Job Submission (Deduplication)

If you submit the same job twice within 5 minutes, you get back the **same job_id**:

```bash
# First request
curl -X POST "http://localhost:8000/api/v1/loops/1/render-async" \
  -d '{"genre": "pop", "length_seconds": 30}'
# Returns: job_id = "abc123", deduplicated = false

# Same request 2 seconds later
curl -X POST "http://localhost:8000/api/v1/loops/1/render-async" \
  -d '{"genre": "pop", "length_seconds": 30}'
# Returns: job_id = "abc123", deduplicated = true (same job!)
```

**How it works:**
- Dedup hash = SHA256(loop_id + render params)
- Checks if any job with same hash exists within 5-minute window
- Returns existing job if found, avoiding duplicate work

### 2. Progress Polling

Job progress is updated in real-time:

```
queued (0%)
  ↓
processing (1-99%)
  ├─ Downloaded audio (10%)
  ├─ Loaded loop (20%)
  ├─ Rendering Commercial (40%)
  ├─ Rendering Creative (65%)
  ├─ Rendering Experimental (90%)
  └─ Uploading to S3 (95%)
  ↓
succeeded (100%) OR failed (with error_message)
```

### 3. Presigned URLs (S3 Access)

- Generated on-demand when polling status (not pre-generated)
- Valid for 1 hour from generation time
- Never expire in HTML responses (regenerated each request)
- Includes all necessary S3 permissions

### 4. Error Handling & Retries

Worker automatically retries transient failures:

```
download_loop_audio()  // 3 attempts with exponential backoff
  ↓ (if fails: S3 timeout, network error)
  Retry after 2s
  Retry after 4s
  ↓ (if still fails: mark job failed)

upload_render_output()  // Same retry strategy
```

Permanent failures stored in job:
```json
{
  "status": "failed",
  "error_message": "Loop audio file not found at s3://bucket/loops/1/audio.wav",
  "retry_count": 3
}
```

## Debugging

### 1. Check Worker is Running

```bash
# In Terminal 3, check worker logs
python -m app.workers
# Look for: "Worker started listening to render queue"
```

### 2. Monitor Redis Queue

```bash
# Terminal 3: Watch Redis activity
redis-cli monitor

# Output shows:
#   1) "rpush" "rq:queue:render" "{...job data...}"  # Job enqueued
#   2) "lpop" "rq:queue:render"                      # Job dequeued by worker
#   3) "hset" "rq:job:xyz" "status" "started"        # Status update
```

### 3. Check Database

```bash
# View jobs in database
sqlite3 test.db "SELECT id, loop_id, status, progress FROM render_jobs ORDER BY created_at DESC LIMIT 10;"

# Or with PostgreSQL:
psql -c "SELECT id, loop_id, status, progress FROM render_jobs ORDER BY created_at DESC LIMIT 10;"
```

### 4. Test Worker Processing

```bash
# Enqueue job
curl -X POST "http://localhost:8000/api/v1/loops/1/render-async" \
  -d '{"genre": "pop", "length_seconds": 30}'

# Watch worker terminal for processing logs
# Should see:
#   [Job xyz] Starting render for loop 1
#   [Job xyz] Downloaded audio (5.2 MB)
#   [Job xyz] Rendering Commercial variation
#   [Job xyz] Uploaded output to S3
#   [Job xyz] Succeeded

# Poll status
curl http://localhost:8000/api/v1/jobs/xyz
```

## Troubleshooting

### "Redis connection refused"
```
Problem: Worker fails to connect to Redis
Solution:
  1. Verify Redis is running: redis-cli ping
  2. Check REDIS_URL env var is correct
  3. Start with: redis-server
```

### "No such loop"
```
Problem: Render request returns 404
Solution:
  1. Verify loop_id exists: GET /api/v1/loops/{loop_id}
  2. Ensure loop has audio: Check file_key or file_url is set
```

### "S3 access denied"
```
Problem: Worker fails to upload renders
Solution:
  1. Verify AWS credentials are valid
  2. Check bucket exists and is accessible
  3. Ensure IAM policy allows s3:PutObject on bucket
  4. Check AWS_S3_BUCKET env var matches actual bucket name
```

### "Job stuck in processing"
```
Problem: Job status never changes from "processing"
Solution:
  1. Check worker is actually running: "python -m app.workers" output
  2. Check for exceptions in worker logs
  3. Restart worker: Kill process and restart
  4. Check database size: Worker may be overwhelmed
```

## Implementation Details

### Job Lifecycle States

```
QUEUED
  ↓ (Worker picks up job)
PROCESSING (progress 0-99%)
  ↓
  ├→ SUCCEEDED (progress 100%, outputs have files)
  └→ FAILED (error_message set, retry_count updated)
```

### Database Schema

```sql
CREATE TABLE render_jobs (
  id VARCHAR(36) PRIMARY KEY,           -- UUID
  loop_id INTEGER NOT NULL,             -- FK to loops
  job_type VARCHAR(50),                 -- "render"
  status VARCHAR(20),                   -- queued/processing/succeeded/failed
  progress INTEGER DEFAULT 0,           -- 0-100%
  progress_message VARCHAR(255),        -- Human-readable update
  params_json TEXT,                     -- Stored RenderConfig as JSON
  output_files_json TEXT,               -- Array of {name, s3_key, content_type}
  error_message TEXT,                   -- If failed
  retry_count INTEGER DEFAULT 0,        -- Failed attempts
  dedupe_hash VARCHAR(64),              -- SHA256 for deduplication
  created_at DATETIME,                  -- When job was created
  started_at DATETIME,                  -- When processing began
  finished_at DATETIME,                 -- When completed
  expires_at DATETIME,                  -- For cleanup/retention
  
  FOREIGN KEY (loop_id) REFERENCES loops(id),
  INDEX (loop_id, dedupe_hash, created_at),  -- For dedup search
  INDEX (status)                              -- For job queries
);
```

### File Structure

```
app/
├── models/
│   └── job.py                    # RenderJob SQLAlchemy model
├── schemas/
│   └── job.py                    # Pydantic request/response schemas
├── services/
│   └── job_service.py            # Job lifecycle (create, list, status, update)
├── routes/
│   └── render_jobs.py            # 3 endpoints (enqueue, get status, list)
├── workers/
│   ├── __init__.py               # Package marker
│   ├── __main__.py               # CLI entry point
│   └── render_worker.py          # Worker function (calls models, audio, S3)
└── queue.py                      # Redis connection factory
```

## Performance Notes

- **Queue latency**: ~100ms from enqueue to worker pickup
- **Render time**: 15-30 seconds per loop (depends on variations)
- **S3 upload**: 2-5 seconds (parallel for 3 variations)
- **Polling overhead**: <10ms per status check

## Next Steps

1. **Run locally** following setup above
2. **Test endpoints** using curl examples
3. **Monitor worker** in Terminal 2
4. **Deploy to Railway** using updated deployment docs
5. **Review logs** for any issues

See `DEPLOYMENT.md` for production setup.
