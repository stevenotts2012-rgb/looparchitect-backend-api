# LoopArchitect API Quick Reference

## Base URL
- Local: `http://localhost:8000`
- Production: `https://your-app.onrender.com`

All endpoints use prefix: `/api/v1`

---

## Health & Monitoring

### Health Check
```
GET /api/v1/health
```
Returns: `{"status": "ok", "message": "Service is healthy"}`

### Readiness Probe
```
GET /api/v1/ready
```
Returns: Database + storage health status

---

## Loop Management

### List Loops
```
GET /api/v1/loops?status={status}&genre={genre}&limit={limit}&offset={offset}
```
**Query Params:**
- `status`: pending | processing | complete | failed
- `genre`: Filter by genre
- `limit`: Max results (1-1000, default: 100)
- `offset`: Pagination offset (default: 0)

### Get Loop
```
GET /api/v1/loops/{loop_id}
```
Returns full loop metadata including status, BPM, key, etc.

### Create Loop (Metadata Only)
```
POST /api/v1/loops
Content-Type: application/json

{
  "name": "My Loop",
  "tempo": 140,
  "key": "C",
  "genre": "Hip Hop"
}
```

### Upload File with Auto-Record
```
POST /api/v1/loops/upload
Content-Type: multipart/form-data

file: <audio file>
```
Returns: `{"loop_id": 1, "file_url": "..."}`

### Upload File Only (No DB Record)
```
POST /api/v1/upload
Content-Type: multipart/form-data

file: <audio file>
```
Returns: `{"file_url": "..."}`

### Upload with Metadata
```
POST /api/v1/loops/with-file
Content-Type: multipart/form-data

loop_in: '{"name":"My Loop","tempo":140,"key":"C","genre":"Trap"}'
file: <audio file>
```
Returns: Full loop record with analysis (if local storage)

### Update Loop
```
PATCH /api/v1/loops/{loop_id}
Content-Type: application/json

{
  "status": "complete",
  "bpm": 128
}
```

### Delete Loop
```
DELETE /api/v1/loops/{loop_id}?delete_file=true
```
**Query Params:**
- `delete_file`: true (default) | false

---

## Audio Operations

### Download Loop
```
GET /api/v1/loops/{loop_id}/download
```
- S3: Redirects to presigned URL
- Local: Returns file directly

### Stream Loop
```
GET /api/v1/loops/{loop_id}/stream
```
Returns: StreamingResponse for progressive playback

### Analyze Loop (Background)
```
POST /api/v1/analyze-loop/{loop_id}
```
Returns: `{"loop_id": 1, "status": "pending", "check_status_at": "/api/v1/loops/1"}`

### Generate Beat (Background)
```
POST /api/v1/generate-beat/{loop_id}?target_length={seconds}
```
**Query Params:**
- `target_length`: 10-600 seconds

Returns: `{"loop_id": 1, "status": "pending", ...}`

### Extend Loop (Background)
```
POST /api/v1/extend-loop/{loop_id}?bars={bars}
```
**Query Params:**
- `bars`: 1-128 bars

Returns: `{"loop_id": 1, "status": "pending", ...}`

---

## File Validation

### Allowed Formats
- **MIME Types:** audio/wav, audio/mpeg, audio/mp3
- **Extensions:** .wav, .mp3
- **Max Size:** 50MB (default)

### Security
- Filename sanitization enabled
- Path traversal prevention
- File type validation (MIME + extension)
- Size limits enforced

---

## Storage Modes

### Local Storage (Development)
- Files saved to `uploads/` directory
- Direct file serving
- Immediate audio analysis

### S3 Storage (Production)
- Automatic when `AWS_S3_BUCKET` is set
- Presigned URLs for downloads (1-hour expiration)
- Streaming from S3

**Environment Variables:**
```bash
AWS_S3_BUCKET=your-bucket
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_REGION=us-east-1  # optional
```

---

## Response Codes

- `200 OK` - Success
- `201 Created` - Resource created
- `307 Temporary Redirect` - S3 presigned URL
- `400 Bad Request` - Invalid input
- `404 Not Found` - Resource not found
- `422 Unprocessable Entity` - Validation error
- `500 Internal Server Error` - Server error
- `503 Service Unavailable` - System not ready

---

## Error Response Format

```json
{
  "error": "Error Type",
  "detail": "Detailed error message",
  "path": "/api/v1/endpoint-path"
}
```

---

## Background Task Workflow

1. POST to task endpoint (analyze, generate-beat, extend-loop)
2. Receive immediate response with `status: "pending"`
3. Poll `GET /api/v1/loops/{id}` to check status
4. Status transitions: `pending` → `processing` → `complete` or `failed`
5. When `complete`, check `processed_file_url` for result

**Polling Recommended:**
- Initial: 1 second delay
- Subsequent: Every 2-5 seconds
- Max wait: 60-120 seconds

---

## Common Workflows

### Upload & Analyze
```bash
# 1. Upload
curl -X POST http://localhost:8000/api/v1/loops/upload \
  -F "file=@drum-loop.wav"
# Response: {"loop_id": 1, "file_url": "..."}

# 2. Analyze
curl -X POST http://localhost:8000/api/v1/analyze-loop/1

# 3. Check status
curl http://localhost:8000/api/v1/loops/1
# Wait until status: "complete"
```

### Generate Beat
```bash
# Queue generation
curl -X POST "http://localhost:8000/api/v1/generate-beat/1?target_length=120"

# Poll status
curl http://localhost:8000/api/v1/loops/1

# Download when complete
curl http://localhost:8000/api/v1/loops/1/download -o beat.wav
```

### Browse & Filter
```bash
# Get all complete loops
curl "http://localhost:8000/api/v1/loops?status=complete"

# Get Hip Hop loops
curl "http://localhost:8000/api/v1/loops?genre=Hip%20Hop"

# Pagination
curl "http://localhost:8000/api/v1/loops?limit=20&offset=40"
```

---

## Swagger Documentation

Interactive API documentation available at:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

---

## Production Deployment

### Render.com
```bash
# Start command
uvicorn main:app --host 0.0.0.0 --port $PORT --workers 2
```

### Environment Variables Required
```bash
DATABASE_URL=<postgres-url>
AWS_S3_BUCKET=<bucket-name>  # optional for S3
AWS_ACCESS_KEY_ID=<key>      # optional for S3
AWS_SECRET_ACCESS_KEY=<secret>  # optional for S3
```

### Health Check Endpoint
```
GET /api/v1/health
```
Configure in Render dashboard for automatic health monitoring.

---

## curl Examples

### Upload
```bash
curl -X POST http://localhost:8000/api/v1/loops/upload \
  -F "file=@myloop.wav" \
  -H "Content-Type: multipart/form-data"
```

### Stream
```bash
curl http://localhost:8000/api/v1/loops/1/stream \
  --output streamed.wav
```

### Download
```bash
curl -L http://localhost:8000/api/v1/loops/1/download \
  --output downloaded.wav
```

### List with Filters
```bash
curl "http://localhost:8000/api/v1/loops?status=complete&limit=10"
```

### Health Check
```bash
curl http://localhost:8000/api/v1/health
```

### Readiness Check
```bash
curl http://localhost:8000/api/v1/ready
```

---

## Python Example

```python
import requests

# Upload file
with open("loop.wav", "rb") as f:
    response = requests.post(
        "http://localhost:8000/api/v1/loops/upload",
        files={"file": f}
    )
    loop_id = response.json()["loop_id"]

# Analyze
requests.post(f"http://localhost:8000/api/v1/analyze-loop/{loop_id}")

# Check status
import time
while True:
    status = requests.get(f"http://localhost:8000/api/v1/loops/{loop_id}").json()
    if status["status"] == "complete":
        print(f"BPM: {status['bpm']}, Key: {status['musical_key']}")
        break
    time.sleep(2)

# Download
response = requests.get(
    f"http://localhost:8000/api/v1/loops/{loop_id}/download",
    allow_redirects=True
)
with open("output.wav", "wb") as f:
    f.write(response.content)
```

---

## JavaScript/Fetch Example

```javascript
// Upload
const formData = new FormData();
formData.append('file', fileInput.files[0]);

const uploadResponse = await fetch('http://localhost:8000/api/v1/loops/upload', {
  method: 'POST',
  body: formData
});
const { loop_id } = await uploadResponse.json();

// Analyze
await fetch(`http://localhost:8000/api/v1/analyze-loop/${loop_id}`, {
  method: 'POST'
});

// Poll status
const checkStatus = async () => {
  const response = await fetch(`http://localhost:8000/api/v1/loops/${loop_id}`);
  const data = await response.json();
  
  if (data.status === 'complete') {
    console.log(`BPM: ${data.bpm}, Key: ${data.musical_key}`);
  } else {
    setTimeout(checkStatus, 2000);
  }
};
checkStatus();
```

---

**API Version:** 1.0.0  
**Last Updated:** 2026-02-24
