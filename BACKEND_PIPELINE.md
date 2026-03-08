# LoopArchitect Backend Pipeline Documentation

## Overview

The LoopArchitect backend implements a robust, production-ready async render pipeline using Redis/RQ for background job processing. This architecture separates web API requests from CPU-intensive audio rendering tasks.

## Architecture

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   Client    │─────▶│  FastAPI    │─────▶│   Redis     │
│  (Browser)  │      │  Web Server │      │    Queue    │
└─────────────┘      └─────────────┘      └─────────────┘
                            │                     │
                            │                     ▼
                            │              ┌─────────────┐
                            │              │     RQ      │
                            │              │   Worker    │
                            │              └─────────────┘
                            │                     │
                            ▼                     ▼
                     ┌──────────────────────────────┐
                     │       PostgreSQL DB           │
                     │  (Loops, Jobs, Artifacts)     │
                     └──────────────────────────────┘
                                    │
                                    ▼
                            ┌─────────────┐
                            │  S3 Storage │
                            │ (Audio Files)│
                            └─────────────┘
```

## Components

### 1. Web Server (FastAPI)

**Entry point**: `app/main.py`

**Responsibilities**:
- Accept HTTP requests from clients
- Validate input via Pydantic schemas
- Enqueue background jobs to Redis
- Return job status immediately (non-blocking)
- Serve presigned S3 URLs for downloads

**Start command**:
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### 2. Background Worker (RQ)

**Entry point**: `app/workers/main.py`

**Responsibilities**:
- Pull jobs from Redis queue
- Download loop audio from S3
- Process audio transformations (normalize, filters, etc.)
- Upload rendered outputs to S3
- Update job status in database

**Start command**:
```bash
python -m app.workers.main
```

### 3. Redis Queue

**Purpose**: Durable job queue for async processing

**Configuration**: Set `REDIS_URL` environment variable

**Libraries**: `redis`, `rq`

### 4. PostgreSQL Database

**Models**:
- `Loop`: Audio loops with metadata (BPM, key, genre, S3 keys)
- `RenderJob`: Job tracking with status, progress, outputs, errors
- `Arrangement`: (Optional) Song structure definitions

**Migrations**: Alembic (`alembic upgrade head`)

### 5. S3 Storage

**Purpose**: Persistent storage for audio files

**Configuration**:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_S3_BUCKET`
- `AWS_REGION`

**Storage paths**:
- Uploads: `uploads/{uuid}.wav`
- Renders: `renders/{job_id}/{filename}.wav`

## Post-Processing Pipeline (Producer-Grade Runtime)

The runtime path now includes two optional post-processing stages that run in real execution paths (`arrangement_jobs` and `render_worker`) through the shared `render_executor`:

1. **Stem Separation (Loop ingest stage)**
   - Service: `app/services/stem_separation.py`
   - Trigger: loop upload endpoints after source loop is persisted.
   - Result: generated stem artifacts (`bass`, `drums`, `vocals`, `other`) are uploaded to storage and metadata is attached to `Loop.analysis_json.stem_separation`.
   - Fallback: on decode/backend failure, upload flow continues and stores failure metadata instead of blocking loop creation.

2. **Final Mastering/Polish (Render stage)**
   - Service: `app/services/mastering.py`
   - Trigger: after arrangement audio is rendered from `render_plan_json`, before final WAV export.
   - Result: genre-aware profile (`rnb_smooth`, `low_end_focus`, or `transparent`) plus peak-level metadata persisted to `render_plan_json.render_profile.postprocess.mastering`.
   - Fallback: when disabled, render completes unchanged and records `profile=disabled`.

### Runtime Flags

- `FEATURE_STEM_SEPARATION` (default: `false`)
- `STEM_SEPARATION_BACKEND` (default: `builtin`)
- `FEATURE_MASTERING_STAGE` (default: `true`)
- `MASTERING_PROFILE_DEFAULT` (default: `transparent`, `auto` enables genre-driven selection)

## API Endpoints

### Async Render Pipeline

#### `POST /api/v1/loops/{loop_id}/render-async`

Enqueue a render job (non-blocking).

**Request body**:
```json
{
  "genre": "Trap",
  "length_seconds": 180,
  "energy": "high",
  "variations": 3,
  "variation_styles": ["ATL Trap", "Detroit Trap"],
  "custom_style": null
}
```

**Response** (HTTP 202):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "loop_id": 5,
  "status": "queued",
  "created_at": "2026-03-01T14:30:00Z",
  "poll_url": "/api/v1/jobs/550e8400-e29b-41d4-a716-446655440000",
  "deduplicated": false
}
```

**Error responses**:
- `404`: Loop not found
- `400`: Loop has no audio file
- `503`: Redis queue unavailable

#### `GET /api/v1/jobs/{job_id}`

Poll job status.

**Response**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "loop_id": 5,
  "job_type": "render_arrangement",
  "status": "succeeded",
  "progress": 100.0,
  "progress_message": "Render completed",
  "created_at": "2026-03-01T14:30:00Z",
  "started_at": "2026-03-01T14:30:05Z",
  "finished_at": "2026-03-01T14:32:15Z",
  "output_files": [
    {
      "name": "Commercial",
      "s3_key": "renders/550e8400-e29b-41d4-a716-446655440000/Commercial.wav",
      "content_type": "audio/wav",
      "signed_url": "https://s3.amazonaws.com/..."
    }
  ],
  "error_message": null,
  "retry_count": 0
}
```

**Status values**:
- `queued`: Job waiting in queue
- `processing`: Worker actively rendering
- `succeeded`: Complete with outputs
- `failed`: Error occurred (see `error_message`)

#### `GET /api/v1/loops/{loop_id}/jobs`

List all jobs for a loop (recent first).

**Query params**:
- `limit`: Max results (default: 20)

**Response**:
```json
{
  "loop_id": 5,
  "jobs": [
    { /* job status object */ },
    { /* job status object */ }
  ]
}
```

#### `GET /api/v1/renders/s3/{job_id}/{filename}`

Download render output from S3 (redirects to presigned URL).

**Example**: `/api/v1/renders/s3/550e8400.../Commercial.wav`

## Database Schema

### `render_jobs` Table

| Column              | Type         | Description                              |
|---------------------|--------------|------------------------------------------|
| `id`                | VARCHAR(36)  | UUID primary key                         |
| `loop_id`           | INTEGER      | Foreign key to `loops.id`                |
| `job_type`          | VARCHAR(64)  | Job type (e.g., "render_arrangement")    |
| `params_json`       | TEXT         | Input parameters as JSON                 |
| `status`            | VARCHAR(32)  | `queued|processing|succeeded|failed`     |
| `progress`          | FLOAT        | 0-100 percentage                         |
| `progress_message`  | VARCHAR(256) | Human-readable progress update           |
| `output_files_json` | TEXT         | JSON array of output artifacts           |
| `error_message`     | TEXT         | Error details if failed                  |
| `retry_count`       | INTEGER      | Number of retry attempts                 |
| `dedupe_hash`       | VARCHAR(64)  | SHA256 for deduplication                 |
| `created_at`        | DATETIME     | Job creation timestamp                   |
| `queued_at`         | DATETIME     | Enqueue timestamp                        |
| `started_at`        | DATETIME     | Worker start timestamp                   |
| `finished_at`       | DATETIME     | Completion timestamp                     |
| `expires_at`        | DATETIME     | (Optional) TTL for cleanup               |

**Indexes**:
- `ix_render_jobs_loop_dedupe_created` (composite: loop_id, dedupe_hash, created_at)
- `ix_render_jobs_status`

## Environment Variables

### Required

| Variable               | Description                          | Example                              |
|------------------------|--------------------------------------|--------------------------------------|
| `DATABASE_URL`         | Postgres connection string           | `postgresql://user:pass@host/db`     |
| `REDIS_URL`            | Redis connection string              | `redis://localhost:6379/0`           |
| `AWS_ACCESS_KEY_ID`    | AWS credentials                      | `AKIA...`                            |
| `AWS_SECRET_ACCESS_KEY`| AWS secret key                       | `wJalr...`                           |
| `AWS_S3_BUCKET`        | S3 bucket name                       | `looparchitect-audio`                |
| `AWS_REGION`           | AWS region                           | `us-east-1`                          |

### Optional

| Variable           | Description                     | Default                    |
|--------------------|---------------------------------|----------------------------|
| `FRONTEND_ORIGIN`  | CORS allowed origin             | (multiple defaults)        |
| `PORT`             | Web server port                 | `8000`                     |

## Local Development

### Prerequisites

- Python 3.11+
- PostgreSQL
- Redis
- AWS S3 bucket (or compatible storage)

### Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Run migrations**:
   ```bash
   alembic upgrade head
   ```

4. **Start Redis** (if not running):
   ```bash
   redis-server
   ```

5. **Start web server**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

6. **Start worker** (in separate terminal):
   ```bash
   python -m app.workers.main
   ```

7. **Run smoke test**:
   ```bash
   python scripts/smoke_test_render_pipeline.py
   ```

## Railway Deployment

### Services Configuration

#### Web Service

**Build settings**:
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Healthcheck: `/health`

**Environment variables**:
- `DATABASE_URL` (from Postgres addon)
- `REDIS_URL` (from Redis addon)
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_S3_BUCKET`
- `AWS_REGION`
- `FRONTEND_ORIGIN` (optional)

#### Worker Service

**Build settings**:
- Start command: `python -m app.workers.main`
- No healthcheck (background process)

**Environment variables**:
- Same as web service (share configuration)

### Deployment Steps

1. **Create Railway project**
2. **Add addons**:
   - PostgreSQL
   - Redis
3. **Deploy web service**:
   - Connect GitHub repo
   - Set start command
   - Configure environment variables
4. **Deploy worker service**:
   - Same repo, different start command
   - Share environment with web service
5. **Run migrations**:
   ```bash
   railway run alembic upgrade head
   ```
6. **Verify**:
   - Check web service logs for startup
   - Check worker logs for "LoopArchitect Worker Started"
   - Test endpoints via Swagger docs

## Job Lifecycle

```
1. Client → POST /loops/{id}/render-async
2. API validates loop and enqueues job
3. API returns job_id immediately (HTTP 202)
4. Worker pulls job from queue
5. Worker updates status: queued → processing
6. Worker downloads loop audio from S3
7. Worker renders variations
8. Worker uploads outputs to S3
9. Worker updates status: processing → succeeded
10. Client polls GET /jobs/{job_id}
11. Client downloads renders via presigned URLs
```

## Error Handling

### API Errors

- **503 Service Unavailable**: Redis queue offline
- **404 Not Found**: Loop or job not found
- **400 Bad Request**: Invalid parameters or missing audio file

### Worker Errors

- Exceptions caught and logged
- Job status set to `failed` with `error_message`
- Retry count incremented
- No automatic retries (implement via RQ retry settings if needed)

## Performance

### Deduplication

Identical render requests within a 5-minute window return the same job (idempotency).

Hash: `SHA256(loop_id + params)`

### Timeouts

- S3 operations: 30s (via boto3 config)
- Job polling: Client-side (recommended 5s interval)
- Presigned URLs: 1 hour expiry

### Concurrency

- Workers can scale horizontally (multiple instances)
- Each worker processes one job at a time
- Queue supports multiple workers

## Monitoring

### Logs

**Web service**:
- Request/response logging (middleware)
- Job enqueue events

**Worker**:
- Startup: "LoopArchitect Worker Started"
- Heartbeat: Every 60 seconds
- Job lifecycle: Start, progress updates, completion

### Metrics (Future)

- Job queue depth (Redis)
- Job completion time
- Error rates
- Worker count

## Testing

### Smoke Test

```bash
python scripts/smoke_test_render_pipeline.py --base-url http://localhost:8000
```

Tests:
- ✅ API health
- ✅ Loop upload
- ✅ Job enqueue
- ✅ Status polling
- ✅ Output artifacts
- ✅ Presigned URL validity

### Unit Tests

```bash
pytest tests/
```

## Troubleshooting

### "Redis connection failed"

- Verify `REDIS_URL` is set
- Check Redis is running (`redis-cli ping`)
- Check network connectivity for remote Redis

### "No module named 'redis'"

- Install dependencies: `pip install -r requirements.txt`

### Jobs stuck in "queued"

- Verify worker is running (`python -m app.workers.main`)
- Check worker logs for errors
- Verify Redis queue has jobs: `redis-cli LLEN rq:queue:render`

### S3 upload fails

- Verify AWS credentials
- Check bucket exists and permissions
- Verify region matches

### "Job not found"

- Job may have expired (if TTL implemented)
- Verify job_id is correct
- Check database: `SELECT * FROM render_jobs WHERE id = '...'`

## API Reference

Full API documentation available at:
- Local: http://localhost:8000/docs (Swagger UI)
- Production: https://your-domain.com/docs

## Future Enhancements

- [ ] Job retry with exponential backoff
- [ ] Job TTL and automatic cleanup
- [ ] Webhook notifications on job completion
- [ ] Real-time progress via WebSocket
- [ ] Job priority queue
- [ ] Batch render operations
- [ ] Cost estimation pre-render
- [ ] Audio preview generation (30s clips)
- [ ] Worker autoscaling based on queue depth

## Support

For issues or questions:
- Check logs (web and worker)
- Run smoke test to isolate failures
- Review Railway dashboard for service health
- Examine PostgreSQL for job records

---

**Last updated**: March 1, 2026  
**Version**: 1.0.0
