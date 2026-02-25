# Phase B Audio Generation - Quick Reference & Testing Guide

## Quick Reference

### New API Endpoints

```bash
# 1. Generate arrangement (returns 202 Accepted)
POST /api/v1/arrangements/generate
Content-Type: application/json

{
  "loop_id": 1,
  "target_seconds": 120,
  "genre": "electronic",
  "intensity": "medium",
  "include_stems": false
}

# 2. Check status
GET /api/v1/arrangements/{arrangement_id}

# 3. Download audio (returns 409 if not ready)
GET /api/v1/arrangements/{arrangement_id}/download
```

## Testing Workflow

### Step 1: Ensure Database is Ready
```bash
cd c:\Users\steve\looparchitect-backend-api
alembic upgrade head
```
Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade  -> 001_add_missing_loop_columns
INFO  [alembic.runtime.migration] Running upgrade 001_add_missing_loop_columns -> 002_create_arrangements_table
```

### Step 2: Start the API Server
```bash
uvicorn main:app --reload
```
Expected output:
```
[19:01:58] INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Step 3: Create or Get a Loop

#### Option A: Use Existing Loop (if you have one)
```bash
# Query to find existing loop
sqlite3 test.db "SELECT id, name, duration_seconds FROM loops LIMIT 1;"

# You should get something like:
# 1|Test Loop|4.0
```

#### Option B: Upload a New Loop
```bash
# Create a test WAV file (if you don't have one)
# Then upload via:
curl -X POST http://localhost:8000/api/v1/loops/with-file \
  -F "file=@test_loop.wav" \
  -F "name=My Test Loop"
```

### Step 4: Generate Arrangement

```bash
# Submit generation request (assuming loop_id = 1)
curl -X POST http://localhost:8000/api/v1/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 30,
    "genre": "electronic",
    "intensity": "medium"
  }' | jq .

# Expected response (202 Accepted):
# {
#   "arrangement_id": 1,
#   "loop_id": 1,
#   "status": "queued",
#   "created_at": "2024-01-15T10:30:00.000Z"
# }
```

### Step 5: Check Status (Polling)

```bash
# Check arrangement status
ARRANGEMENT_ID=1

# First check (should be queued or processing)
curl http://localhost:8000/api/v1/arrangements/$ARRANGEMENT_ID | jq '.status'

# Poll every 2 seconds until complete
while true; do
  STATUS=$(curl -s http://localhost:8000/api/v1/arrangements/$ARRANGEMENT_ID | jq -r '.status')
  if [ "$STATUS" = "complete" ]; then
    echo "✓ Arrangement complete!"
    break
  elif [ "$STATUS" = "failed" ]; then
    echo "✗ Arrangement failed"
    curl http://localhost:8000/api/v1/arrangements/$ARRANGEMENT_ID | jq '.error_message'
    break
  else
    echo "Status: $STATUS"
    sleep 2
  fi
done
```

### Step 6: Download Audio File

```bash
# Download the generated arrangement
curl http://localhost:8000/api/v1/arrangements/1/download \
  -o my_arrangement.wav

# Verify file was created
ls -lh my_arrangement.wav

# Play the file (on Windows)
start my_arrangement.wav

# Or on Mac
open my_arrangement.wav

# Or on Linux
sox my_arrangement.wav -d
```

## Testing Different Parameters

### Test Different Durations
```bash
for SECONDS in 10 30 60 120 300 600; do
  echo "Testing $SECONDS seconds..."
  curl -X POST http://localhost:8000/api/v1/arrangements/generate \
    -H "Content-Type: application/json" \
    -d "{\"loop_id\": 1, \"target_seconds\": $SECONDS}"
  echo ""
done
```

### Test Different Intensities
```bash
for INTENSITY in low medium high; do
  echo "Testing intensity: $INTENSITY"
  curl -X POST http://localhost:8000/api/v1/arrangements/generate \
    -H "Content-Type: application/json" \
    -d "{\"loop_id\": 1, \"target_seconds\": 60, \"intensity\": \"$INTENSITY\"}"
  echo ""
done
```

### Test Different Genres
```bash
for GENRE in electronic hip-hop ambient generic; do
  echo "Testing genre: $GENRE"
  curl -X POST http://localhost:8000/api/v1/arrangements/generate \
    -H "Content-Type: application/json" \
    -d "{\"loop_id\": 1, \"target_seconds\": 60, \"genre\": \"$GENRE\"}"
  echo ""
done
```

## API Response Examples

### 202 - Generate Success
```json
{
  "arrangement_id": 1,
  "loop_id": 1,
  "status": "queued",
  "created_at": "2024-01-15T10:30:00.000Z"
}
```

### 200 - Status Queued
```json
{
  "id": 1,
  "loop_id": 1,
  "status": "queued",
  "target_seconds": 60,
  "genre": "electronic",
  "intensity": "medium",
  "include_stems": false,
  "output_file_url": null,
  "stems_zip_url": null,
  "arrangement_json": null,
  "error_message": null,
  "created_at": "2024-01-15T10:30:00.000Z",
  "updated_at": "2024-01-15T10:30:00.000Z"
}
```

### 200 - Status Processing
```json
{
  "id": 1,
  "loop_id": 1,
  "status": "processing",
  "target_seconds": 60,
  ...
  "updated_at": "2024-01-15T10:30:05.000Z"
}
```

### 200 - Status Complete
```json
{
  "id": 1,
  "loop_id": 1,
  "status": "complete",
  "target_seconds": 60,
  ...
  "output_file_url": "/renders/arrangements/abc123def456.wav",
  "arrangement_json": "{\"total_duration_seconds\": 60, \"sections\": [...]}",
  "updated_at": "2024-01-15T10:30:15.000Z"
}
```

### 200 - Download Success
```
[Binary WAV file with Content-Type: audio/wav]
Content-Disposition: attachment; filename="arrangement_1.wav"
```

### 409 - Download Not Ready
```json
{
  "detail": "Arrangement is still queued. Try again later."
}
```

### 404 - Arrangement Not Found
```json
{
  "detail": "Arrangement with ID 999 not found"
}
```

### 404 - Loop Not Found
```json
{
  "detail": "Loop with ID 999 not found"
}
```

### 400 - Generation Failed
```json
{
  "detail": "Arrangement generation failed: Audio file not found at /uploads/missing.wav"
}
```

### 422 - Invalid Parameters
```json
{
  "detail": [
    {
      "loc": ["body", "target_seconds"],
      "msg": "ensure this value is greater than or equal to 10",
      "type": "value_error.number.not_ge"
    }
  ]
}
```

## Database Inspection

### Check Arrangements Table
```bash
sqlite3 test.db
```

```sql
-- List all arrangements
SELECT id, loop_id, status, target_seconds, genre, intensity FROM arrangements;

-- Check for failures
SELECT id, status, error_message FROM arrangements WHERE status='failed';

-- Get details for specific arrangement
SELECT * FROM arrangements WHERE id=1 \G;

-- Count by status
SELECT status, COUNT(*) FROM arrangements GROUP BY status;

-- Get file sizes
SELECT id, output_file_url, LENGTH(arrangement_json) as json_size FROM arrangements;
```

## File System Inspection

```bash
# Check output files
ls -lh renders/arrangements/
du -sh renders/arrangements/

# Verify file is valid WAV
file renders/arrangements/*.wav

# Check file size estimates:
# - 10 second arrangement: ~150KB
# - 60 second arrangement: ~900KB  
# - 120 second arrangement: ~1.8MB
# (Varies by sample rate and bit depth)

# Play random arrangement
ls renders/arrangements/*.wav | shuf | head -1 | xargs mpv

# Delete old arrangements (keep last 10)
ls -t renders/arrangements/*.wav | tail -n +11 | xargs rm
```

## Common Issues & Solutions

### Issue: 404 "Loop with ID 1 not found"
**Solution**: 
```bash
# Check if loops exist
sqlite3 test.db "SELECT id, name FROM loops;"

# If empty, upload a loop first
curl -X POST http://localhost:8000/api/v1/loops/with-file \
  -F "file=@test_loop.wav" \
  -F "name=Test Loop"
```

### Issue: 409 "Arrangement is still queued"
**Solution**: Wait a few seconds and try again
```bash
sleep 5  # Wait for background job to start
curl http://localhost:8000/api/v1/arrangements/1/download
```

### Issue: 422 Validation Error
**Solution**: Check parameters
```bash
# Duration must be 10-3600 (not 5, not 4000)
# intensity must be: low, medium, high
# genre can be any string

# Valid example:
{
  "loop_id": 1,
  "target_seconds": 120,
  "genre": "electronic",
  "intensity": "medium"
}
```

### Issue: File Not Found After Download
**Solution**: Check if arrangement actually completed
```bash
# Verify status
curl http://localhost:8000/api/v1/arrangements/1 | jq '.status'

# Check if file exists
ls -l renders/arrangements/

# If not there, check error
curl http://localhost:8000/api/v1/arrangements/1 | jq '.error_message'
```

## Advanced Testing

### Test with Python
```python
import requests
import time

# Generate
response = requests.post(
    'http://localhost:8000/api/v1/arrangements/generate',
    json={
        'loop_id': 1,
        'target_seconds': 60,
        'intensity': 'medium'
    }
)
arrangement_id = response.json()['arrangement_id']
print(f"Created arrangement {arrangement_id}")

# Poll status
while True:
    status = requests.get(f'http://localhost:8000/api/v1/arrangements/{arrangement_id}').json()
    print(f"Status: {status['status']}")
    if status['status'] == 'complete':
        break
    elif status['status'] == 'failed':
        print(f"Error: {status['error_message']}")
        break
    time.sleep(2)

# Download
if status['status'] == 'complete':
    response = requests.get(f'http://localhost:8000/api/v1/arrangements/{arrangement_id}/download')
    with open(f'arrangement_{arrangement_id}.wav', 'wb') as f:
        f.write(response.content)
    print(f"Downloaded to arrangement_{arrangement_id}.wav")
```

### Load Testing
```bash
#!/bin/bash
# Generate 10 arrangements in parallel
for i in {1..10}; do
  echo "Creating arrangement $i..."
  curl -X POST http://localhost:8000/api/v1/arrangements/generate \
    -H "Content-Type: application/json" \
    -d "{\"loop_id\": 1, \"target_seconds\": 30}" &
done
wait
echo "All requests submitted"

# Monitor progress
for i in {1..10}; do
  while true; do
    STATUS=$(curl -s http://localhost:8000/api/v1/arrangements/$i | jq -r '.status')
    echo "Arrangement $i: $STATUS"
    [ "$STATUS" = "complete" ] && break
    sleep 1
  done &
done
```

## Performance Notes

### Typical Generation Times
- 10 seconds: < 1 second
- 30 seconds: ~2 seconds
- 60 seconds: ~3-4 seconds
- 120 seconds: ~6-8 seconds
- 300 seconds: ~15-20 seconds

Times vary based on:
- CPU speed
- System load
- Audio parameters
- pydub/FFmpeg efficiency

### File Sizes (Approximate)
- Sample rate: 44.1 kHz (standard)
- Bit depth: 16-bit (standard)
- Channels: 1 (mono, from loop)
- Formula: ~88KB per second

Examples:
- 10 seconds: ~880KB
- 60 seconds: ~5.3MB
- 120 seconds: ~10.6MB

---

**Last Updated**: January 2024  
**Tested With**: FastAPI 0.104.1, pydub 0.25.1  
**Python**: 3.11+
