# API Quick Reference - Audio Operations

## New Endpoints

### Create Arrangement (Async)
```http
POST /api/v1/arrangements
```

**Description:** Create an arrangement job from a loop (async)  
**Body:**
```json
{
  "loop_id": 1,
  "target_duration_seconds": 180
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/arrangements \
  -H "Content-Type: application/json" \
  -d '{"loop_id":1,"target_duration_seconds":180}'
```

**Response:**
```json
{
  "id": 12,
  "loop_id": 1,
  "status": "queued",
  "output_url": null
}
```

---

### Get Arrangement
```http
GET /api/v1/arrangements/{id}
```

**Description:** Get arrangement job status and output URL (if done)

**Example:**
```bash
curl http://localhost:8000/api/v1/arrangements/12
```

---

### List Arrangements
```http
GET /api/v1/arrangements?loop_id={loop_id}
```

**Description:** List arrangements, optionally filtered by loop_id

**Example:**
```bash
curl "http://localhost:8000/api/v1/arrangements?loop_id=1"
```

---

### Download Loop File
```http
GET /api/v1/loops/{loop_id}/download
```

**Description:** Download a loop file  
**Storage Modes:**
- Local: Returns file directly via FileResponse
- S3: Redirects to presigned URL (1-hour expiration)

**Example:**
```bash
curl http://localhost:8000/api/v1/loops/1/download -o my-loop.wav
```

**Responses:**
- `200 OK` - File downloaded successfully
- `307 Temporary Redirect` - S3 presigned URL redirect
- `404 Not Found` - Loop doesn't exist
- `500 Internal Server Error` - Download failed

---

### Generate Full Beat
```http
POST /api/v1/generate-beat/{loop_id}?target_length={seconds}
```

**Description:** Queue background task to generate a full beat from a loop  
**Query Parameters:**
- `target_length` (required): Beat length in seconds (10-600)

**Example:**
```bash
curl -X POST "http://localhost:8000/api/v1/generate-beat/1?target_length=120"
```

**Response:**
```json
{
  "loop_id": 1,
  "status": "pending",
  "check_status_at": "/api/v1/loops/1"
}
```

**Status Flow:**
1. `pending` - Task queued
2. `processing` - Task running
3. `complete` - Beat generated (check `processed_file_url`)
4. `failed` - Generation failed

---

### Extend Loop
```http
POST /api/v1/extend-loop/{loop_id}?bars={bars}
```

**Description:** Queue background task to extend a loop to N bars  
**Query Parameters:**
- `bars` (required): Number of bars to extend to (1-128)

**Example:**
```bash
curl -X POST "http://localhost:8000/api/v1/extend-loop/1?bars=8"
```

**Response:**
```json
{
  "loop_id": 1,
  "status": "pending",
  "check_status_at": "/api/v1/loops/1"
}
```

**Note:** Requires loop to have BPM data (run analyze-loop first if needed)

---

### Analyze Loop
```http
POST /api/v1/analyze-loop/{loop_id}
```

**Description:** Queue background task to analyze loop audio (BPM, key, duration)  

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/analyze-loop/1
```

**Response:**
```json
{
  "loop_id": 1,
  "status": "pending",
  "check_status_at": "/api/v1/loops/1"
}
```

**Analysis Results:**
After completion, check the loop record:
```json
{
  "id": 1,
  "status": "complete",
  "bpm": 128,
  "musical_key": "C",
  "duration_seconds": 3.52,
  "analysis_json": "{\"bpm\": 128, \"key\": \"C\", \"duration_seconds\": 3.52, \"sample_rate\": 44100, \"channels\": 2}"
}
```

---

## Enhanced Existing Endpoints

### List Loops (Enhanced)
```http
GET /api/v1/loops?status={status}
```

**New Query Parameter:**
- `status` (optional): Filter by status - `pending`, `processing`, `complete`, `failed`

**Examples:**
```bash
# Get all loops
curl http://localhost:8000/api/v1/loops

# Get only completed loops
curl "http://localhost:8000/api/v1/loops?status=complete"

# Get failed tasks
curl "http://localhost:8000/api/v1/loops?status=failed"
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "drum-loop.wav",
    "status": "complete",
    "bpm": 128,
    "musical_key": "C",
    "file_url": "/uploads/abc123.wav",
    "processed_file_url": "/uploads/beat_1_abc123.wav",
    "analysis_json": "{...}",
    "created_at": "2026-02-24T10:30:00Z"
  }
]
```

---

### Get Loop (Enhanced)
```http
GET /api/v1/loops/{loop_id}
```

**New Response Fields:**
- `status` - Task status (pending/processing/complete/failed)
- `processed_file_url` - URL to generated/processed file
- `analysis_json` - JSON string with analysis results

**Example:**
```bash
curl http://localhost:8000/api/v1/loops/1
```

**Response:**
```json
{
  "id": 1,
  "name": "drum-loop.wav",
  "filename": null,
  "file_url": "/uploads/abc123.wav",
  "title": "My Drum Loop",
  "tempo": 128.0,
  "bpm": 128,
  "key": "C",
  "musical_key": "C",
  "genre": "Hip Hop",
  "duration_seconds": 3.52,
  "status": "complete",
  "processed_file_url": "/uploads/beat_1_abc123.wav",
  "analysis_json": "{\"bpm\": 128, \"key\": \"C\", \"duration_seconds\": 3.52}",
  "created_at": "2026-02-24T10:30:00Z"
}
```

---

## Complete Workflow Example

### 1. Upload a Loop
```bash
curl -X POST http://localhost:8000/api/v1/loops/upload \
  -F "file=@my-drum-loop.wav" \
  -H "Content-Type: multipart/form-data"
```

Response:
```json
{
  "loop_id": 1,
  "file_url": "/uploads/abc123.wav"
}
```

---

### 2. Analyze the Loop
```bash
curl -X POST http://localhost:8000/api/v1/analyze-loop/1
```

Response:
```json
{
  "loop_id": 1,
  "status": "pending",
  "check_status_at": "/api/v1/loops/1"
}
```

---

### 3. Check Analysis Status
```bash
curl http://localhost:8000/api/v1/loops/1
```

Response (after completion):
```json
{
  "id": 1,
  "status": "complete",
  "bpm": 128,
  "musical_key": "C",
  "duration_seconds": 3.52,
  ...
}
```

---

### 4. Generate a Full Beat (120 seconds)
```bash
curl -X POST "http://localhost:8000/api/v1/generate-beat/1?target_length=120"
```

Response:
```json
{
  "loop_id": 1,
  "status": "pending",
  "check_status_at": "/api/v1/loops/1"
}
```

---

### 5. Wait for Processing, Then Download
```bash
# Check if complete
curl http://localhost:8000/api/v1/loops/1

# Download the generated beat
curl http://localhost:8000/api/v1/loops/1/download -o full-beat.wav
```

---

## Status Field Values

| Status | Description |
|--------|-------------|
| `pending` | Task queued, not started |
| `processing` | Task currently running |
| `complete` | Task finished successfully |
| `failed` | Task encountered an error |

---

## Error Responses

### 404 Not Found
```json
{
  "detail": "Loop not found"
}
```

### 400 Bad Request
```json
{
  "detail": "target_length must be between 10 and 600 seconds"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Failed to analyze loop: [error message]"
}
```

---

## Storage Modes

### Local Development
- Files stored in `uploads/` directory
- Downloads served directly via FastAPI FileResponse
- Analysis runs immediately after upload

### Production (S3)
- Files uploaded to S3 bucket
- Downloads use presigned URLs (1-hour expiration)
- Analysis requires file download (use /analyze-loop endpoint)

**Environment Detection:**
- S3 mode enabled if `AWS_S3_BUCKET` env var is set
- Local mode used otherwise

---

## Background Task Processing

All POST endpoints (generate-beat, extend-loop, analyze-loop) use FastAPI BackgroundTasks:

**Benefits:**
- HTTP request returns immediately
- Long-running operations don't block server
- Status can be checked via GET /loops/{id}

**Pattern:**
1. POST request queues task → Returns immediately with "pending" status
2. Task runs in background → Updates status to "processing"
3. Task completes → Updates status to "complete" or "failed"
4. Client polls GET /loops/{id} to check status

**Polling Recommendation:**
- Initial delay: 1 second
- Subsequent polls: Every 2-5 seconds
- Max polling time: 60 seconds (for analysis), 120 seconds (for beat generation)

---

## Loop CRUD API

### Create Loop (Metadata Only)
```http
POST /api/v1/loops
```

**Description:** Create a new loop record with metadata only (no file upload)

**Request Body:** (Only `name` is required)
```json
{
  "name": "My Loop",
  "bpm": 140,
  "bars": 16,
  "genre": "Trap",
  "duration_seconds": 8.0
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/loops \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Trap Beat",
    "bpm": 140,
    "bars": 16,
    "genre": "Trap"
  }'
```

**Response (201 Created):**
```json
{
  "id": 1,
  "name": "Trap Beat",
  "bpm": 140,
  "bars": 16,
  "genre": "Trap",
  "created_at": "2026-02-25T10:30:00Z"
}
```

---

### Create Loop with File Upload
```http
POST /api/v1/loops/with-file
```

**Description:** Create a loop AND upload audio file to S3 in one multipart request

**Request:** (Content-Type: multipart/form-data)
- `file` (required) - Audio file (WAV or MP3)
- `loop_in` (required) - JSON string with loop metadata

**Example:**
```bash
curl -X POST http://localhost:8000/api/v1/loops/with-file \
  -F "file=@my-loop.wav" \
  -F 'loop_in={"name":"My Loop","bpm":140,"bars":16,"genre":"Trap"}'
```

**Response (201 Created):**
```json
{
  "id": 2,
  "name": "My Loop",
  "file_key": "uploads/abc123def456.wav",
  "bpm": 140,
  "bars": 16,
  "genre": "Trap",
  "created_at": "2026-02-25T10:35:00Z"
}
```

---

### List All Loops
```http
GET /api/v1/loops
```

**Description:** List loops with optional filtering and pagination

**Query Parameters:**
- `status` (optional) - Filter by status: "pending", "processing", "complete", "failed"
- `genre` (optional) - Filter by genre
- `limit` (default=100) - Max results (1-1000)
- `offset` (default=0) - Pagination offset

**Examples:**
```bash
# Get all loops
curl http://localhost:8000/api/v1/loops

# Filter by genre
curl "http://localhost:8000/api/v1/loops?genre=Trap&limit=10"

# Filter by status
curl "http://localhost:8000/api/v1/loops?status=complete"
```

**Response (200 OK):**
```json
[
  {
    "id": 1,
    "name": "Trap Beat",
    "bpm": 140,
    "bars": 16,
    "genre": "Trap",
    "file_key": "uploads/abc123.wav",
    "created_at": "2026-02-25T10:30:00Z"
  }
]
```

---

### Get Single Loop
```http
GET /api/v1/loops/{loop_id}
```

**Description:** Get detailed loop information

**Example:**
```bash
curl http://localhost:8000/api/v1/loops/1
```

**Response (200 OK):**
```json
{
  "id": 1,
  "name": "Trap Beat",
  "file_key": "uploads/abc123.wav",
  "bpm": 140,
  "bars": 16,
  "genre": "Trap",
  "duration_seconds": 8.0,
  "status": "pending",
  "created_at": "2026-02-25T10:30:00Z"
}
```

---

### Update Loop (Full Update)
```http
PUT /api/v1/loops/{loop_id}
```

**Description:** Fully update a loop record

**Example:**
```bash
curl -X PUT http://localhost:8000/api/v1/loops/1 \
  -H "Content-Type: application/json" \
  -d '{"bpm": 160, "bars": 32, "genre": "House"}'
```

**Response (200 OK):**
```json
{
  "id": 1,
  "name": "Trap Beat",
  "bpm": 160,
  "bars": 32,
  "genre": "House",
  "created_at": "2026-02-25T10:30:00Z"
}
```

---

### Partially Update Loop (PATCH)
```http
PATCH /api/v1/loops/{loop_id}
```

**Description:** Partially update a loop record (only specified fields)

**Example:**
```bash
curl -X PATCH http://localhost:8000/api/v1/loops/1 \
  -H "Content-Type: application/json" \
  -d '{"bpm": 150}'
```

**Response (200 OK):**
```json
{
  "id": 1,
  "bpm": 150
}
```

---

### Delete Loop
```http
DELETE /api/v1/loops/{loop_id}
```

**Description:** Delete a loop record (note: S3 file is NOT deleted)

**Example:**
```bash
curl -X DELETE http://localhost:8000/api/v1/loops/1
```

**Response (200 OK):**
```json
{
  "id": 1,
  "message": "Loop deleted successfully"
}
```

---

## Environment Variables

### Required for S3
```bash
AWS_S3_BUCKET=your-bucket-name
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1  # Optional, defaults to us-east-1
```

### Database
```bash
DATABASE_URL=postgresql://user:password@host:port/dbname
```

---

## OpenAPI Documentation

All endpoints are documented in the interactive API docs:

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

New endpoints will appear under the "audio" tag.
