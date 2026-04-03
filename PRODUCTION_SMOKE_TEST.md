# LoopArchitect Production Smoke Test Checklist

**Date:** 2026-04-03
**Pipeline Status:** Production-hardened — regression tests, structured logs, code comments added
**Scope:** End-to-end verification of unified rendering pipeline with DAW export and health checks

---

## Pre-Test Setup

### Environment Verification
Before running tests, verify these are in place:

```bash
# Backend: Activate virtual environment
cd c:\Users\steve\looparchitect-backend-api
.\.venv\Scripts\Activate.ps1

# Backend: Set environment variables
$env:FEATURE_PRODUCER_ENGINE = "true"
$env:DEV_FALLBACK_LOOP_ONLY = ""  # MUST be empty in production
$env:DATABASE_URL = "postgresql://..."
$env:REDIS_URL = "redis://..."

# Backend: Start API
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Frontend: In separate terminal
cd c:\Users\steve\looparchitect-frontend
$env:BACKEND_ORIGIN = "http://localhost:8000"
npm run dev
```

### Health Check Baseline
Before starting tests, verify a healthy baseline:

```bash
# Terminal: Check backend readiness
curl -X GET http://localhost:8000/health/ready

# Expected response:
# {
#   "ok": true,
#   "db_ok": true,
#   "redis_ok": true,
#   "s3_ok": true,
#   "ffmpeg_ok": true,            <-- MUST be true
#   "storage_backend": "local|s3"
# }
```

**If `ffmpeg_ok` is `false`:** Stop here and check [Failure Triage](#failure-triage-section) section under "FFmpeg not found".

---

## Smoke Test Sequence

### Step 1: Upload Loop (Ingest Phase)

**What it tests:** Loop ingestion, file storage, metadata capture  
**Expected duration:** < 5 seconds

#### Manual Steps (Frontend)

1. Open frontend at `http://localhost:3000`
2. Locate the **"Upload Loop"** section
3. Select any WAV or MP3 audio file (minimum 10 seconds)
4. Click **"Upload"** button
5. Wait for upload confirmation

#### Expected Success Evidence

```json
// Response in browser console or Network tab
{
  "id": 42,                          // <-- CAPTURE THIS as {loop_id}
  "filename": "test_loop.wav",
  "bpm": 120,
  "tempo": 120,
  "key": "C",
  "file_key": "uploads/test_loop_12345.wav",
  "play_url": "/api/v1/loops/42/play",
  "download_url": "/api/v1/loops/42/download"
}
```

#### What to Record
- **loop_id:** `42` (your actual ID)
- **filename:** from response
- **bpm:** from response

✅ **Success Criteria:**
- HTTP 201 (Created) status
- Response has `id` field (loop_id)
- `bpm` is a valid number
- `file_key` exists

---

### Step 2: Generate Arrangement (AI Analysis Phase)

**What it tests:** Style parsing, producer engine, render plan generation, unified executor invocation  
**Expected duration:** 5-30 seconds (depends on choice model)

#### Manual Steps (Frontend)

1. Go to **"Generate"** page
2. **Loop ID:** Enter the {loop_id} from Step 1 (e.g., `42`)
3. **Target Seconds:** Enter `60`
4. **Style Direction:** Enter a natural language directive, e.g.:
   ```
   upbeat electronic dance music with bright synths and driving bass
   ```
5. Click **"Generate Arrangement"** button
6. Wait for the response (may show progress toast)

#### Alternative: Direct API Test (curl)

```bash
$loop_id = 42
$body = @{
    loop_id = $loop_id
    target_seconds = 60
    style_text_input = "upbeat electronic dance music with bright synths"
    use_ai_parsing = $true
} | ConvertTo-Json

$response = curl -X POST http://localhost:8000/api/v1/arrangements/generate `
  -H "Content-Type: application/json" `
  -d $body

Write-Host $response | ConvertFrom-Json | ConvertTo-Json -Depth 10
```

#### Expected Success Evidence

```json
{
  "arrangement_id": 73,              // <-- CAPTURE THIS as {arrangement_id}
  "loop_id": 42,
  "status": "queued",
  "target_seconds": 60,
  "style_profile_json": {...},
  "producer_arrangement_json": {...},
  "progress": 0.0,
  "created_at": "2026-03-08T10:23:45Z",
  "structure_preview": [
    {"section": "intro", "bars": 4},
    {"section": "verse", "bars": 8},
    ...
  ]
}
```

✅ **Success Criteria:**
- HTTP 202 (Accepted) status
- Response has `arrangement_id` field
- `status` is `"queued"` or `"processing"`
- `producer_arrangement_json` is present (not null)
- `style_profile_json` is present (not null)

#### Critical Check: Render Plan Generation (Before Rendering)

**This is the key unified pipeline change.** The render plan must exist BEFORE rendering starts.

In backend logs, look for:
```
INFO: Building pre-render plan from producer_arrangement or style_sections
INFO: Render plan built with X sections, Y events
INFO: Calling render_from_plan(render_plan_json, audio_source, output_path)
```

Also verify the database:

```bash
# Connect to your database (psql, DBeaver, or SQLite)
# Query the arrangement record
SELECT id, status, render_plan_json, progress FROM arrangements WHERE id = 73;

# Expected:
# id | status | render_plan_json | progress
# 73 | processing | {...} | 0.25 (or higher)
#
# render_plan_json must be non-null JSON object with sections and events
```

What to Record
- **arrangement_id:** `73` (your actual ID)
- **status:** `"queued"` or `"processing"`
- **render_plan_json:** Should contain `sections`, `events`, `metadata`

---

### Step 3: Poll Arrangement Status (Monitor Phase)

**What it tests:** Status endpoint, real-time progress polling  
**Expected duration:** 10-60 seconds total (status updates every 2-5 seconds)

#### Manual Steps (Frontend)

After generating arrangement, the frontend typically shows a progress bar. You can also manually poll:

```bash
$arrangement_id = 73

# Poll every 5 seconds until done
for ($i = 0; $i -lt 12; $i++) {
    $response = curl -X GET http://localhost:8000/api/v1/arrangements/$arrangement_id
    $data = $response | ConvertFrom-Json
    Write-Host "Status: $($data.status) | Progress: $($data.progress)"
    
    if ($data.status -eq "completed" -or $data.status -eq "done") {
        Write-Host "✅ Arrangement complete!"
        break
    }
    Start-Sleep -Seconds 5
}
```

#### Expected Progression

```
Status: queued     | Progress: 0.0
Status: processing | Progress: 0.15  (render plan building)
Status: processing | Progress: 0.35  (rendering in progress)
Status: processing | Progress: 0.65  (audio effects/transitions)
Status: processing | Progress: 0.85  (DAW export generation)
Status: completed  | Progress: 1.0   ✅
```

#### Verify Render Executor Was Called

In **backend logs**, confirm both code paths recorded the same execution:

```
INFO: run_arrangement_job() calling render_from_plan for arrangement 73
INFO: render_from_plan: Loaded render plan with sections=[...], events=[...]
INFO: _render_producer_arrangement: Rendering section intro (bars 0-4)
INFO: _render_producer_arrangement: Applying event kick:on at 0.5ms
INFO: render_from_plan: Completed render in 14.3s
```

✅ **Success Criteria:**
- Final `status` is `"completed"` (or `"done"`)
- `progress` reaches `1.0`
- `output_url` is non-empty (points to rendered audio)
- No error logs containing "render_from_plan" or "executor"
- `timeline_json` is populated (metadata about sections, transitions)

---

### Step 4: Download Arrangement Audio (Verify Audio File)

**What it tests:** Audio file rendering, file download, correct duration  
**Expected duration:** 2-10 seconds

#### Manual Steps (Frontend)

1. After arrangement is `completed`, click **"Download Arrangement"** button
2. Browser should download file like `arrangement_73.wav`
3. Open the file in your audio player (VLC, Windows Media Player, etc.)

#### Alternative: Direct Download via API

```bash
$arrangement_id = 73

# Method 1: Direct download
curl -X GET http://localhost:8000/api/v1/arrangements/$arrangement_id/download `
  -o "arrangement_$($arrangement_id).wav"

# Method 2: Check file metadata first
$statusResponse = curl -X GET http://localhost:8000/api/v1/arrangements/$arrangement_id
$data = $statusResponse | ConvertFrom-Json
Write-Host "Output file URL: $($data.output_url)"
```

#### Verify Audio Duration

```bash
# Using ffprobe (from FFmpeg)
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1:novalue=1 "arrangement_73.wav"

# Expected output: A number close to 60 (seconds)
# Example: 60.248
```

✅ **Success Criteria:**
- Downloaded file size > 1 MB (actual audio data)
- File plays without errors
- Duration is approximately {target_seconds} ± 2 seconds
- Audio is audible (not silent)

---

### Step 5: Verify DAW Export ZIP (Producer Stems)

**What it tests:** DAW exporter, stems per section, MIDI artifacts, ZIP packaging  
**Expected duration:** 3-15 seconds

#### Manual Steps from Arrangement Status Response

```bash
$arrangement_id = 73

# Get arrangement details
$response = curl -X GET http://localhost:8000/api/v1/arrangements/$arrangement_id
$data = $response | ConvertFrom-Json

# Look for stems endpoint
Write-Host "DAW Export URL: $($data.stems_zip_url)"
# Expected: "/api/v1/arrangements/73/daw-export/download"

# Download the ZIP
curl -X GET "http://localhost:8000$($data.stems_zip_url)" `
  -o "arrangement_73_daw_export.zip"
```

#### Verify ZIP Contents

```bash
# Extract and inspect ZIP contents
$zipFile = "arrangement_73_daw_export.zip"
$extractPath = "daw_export_contents"

Expand-Archive -Path $zipFile -DestinationPath $extractPath

# List contents
Get-ChildItem -Recurse $extractPath

# Expected structure:
# daw_export_contents/
#   ├── metadata.json          (arrangement metadata)
#   ├── arrangement.wav        (composite audio)
#   ├── section_intro/         (per-section stems)
#   │   ├── drums.wav
#   │   ├── bass.wav
#   │   ├── synths.wav
#   │   └── [other stems]
#   └── section_verse/
#       ├── drums.wav
#       ├── bass.wav
#       └── synths.wav
```

#### Verify Metadata in ZIP

```bash
# Read metadata.json
Get-Content "$extractPath/metadata.json" | ConvertFrom-Json | ConvertTo-Json -Depth 10

# Expected:
# {
#   "arrangement_id": 73,
#   "loop_id": 42,
#   "style_profile": {...},
#   "producer_arrangement": {...},
#   "render_plan": {...},
#   "sections": [
#     {
#       "name": "intro",
#       "bars": 4,
#       "stems": ["drums.wav", "bass.wav", ...]
#     },
#     ...
#   ],
#   "generated_at": "2026-03-08T10:24:15Z"
# }
```

✅ **Success Criteria:**
- ZIP file > 5 MB (contains multiple stems)
- ZIP extracts without errors
- Contains `metadata.json` with arrangement data
- Contains section folders (e.g., `section_intro`, `section_verse`)
- Each section has at least 2-4 stem files (drums, bass, synths, etc.)
- `metadata.json` includes `render_plan` with sections and events

---

### Step 6: Verify Health Checks (FFmpeg Availability)

**What it tests:** Production readiness, FFmpeg availability, external dependencies  
**Expected duration:** < 1 second

#### Manual Steps

```bash
# Full readiness check
$response = curl -X GET http://localhost:8000/health/ready
$data = $response | ConvertFrom-Json

Write-Host "Overall Status: $($data.ok)"
Write-Host "DB OK: $($data.db_ok)"
Write-Host "Redis OK: $($data.redis_ok)"
Write-Host "S3 OK: $($data.s3_ok)"
Write-Host "FFmpeg OK: $($data.ffmpeg_ok)"
Write-Host "Storage Backend: $($data.storage_backend)"
```

#### Expected Response

```json
{
  "ok": true,
  "db_ok": true,
  "redis_ok": true,
  "s3_ok": true,
  "ffmpeg_ok": true,                 // <-- MUST be true
  "storage_backend": "local"         // or "s3"
}
```

✅ **Success Criteria:**
- Overall `ok` is `true`
- `ffmpeg_ok` is `true` (critical)
- `db_ok` is `true`
- `redis_ok` is `true`
- `s3_ok` matches configured backend

---

### Step 7: Unified Executor Proof (Logs)

**What it tests:** Both API and worker paths call the same render executor  
**Expected duration:** Can be verified post-hoc from logs

#### Check Backend Logs for Unified Execution

In your backend terminal output or Railway logs, search for these exact signatures:

```
# API path (POST /arrangements/generate) → run_arrangement_job:
INFO: run_arrangement_job(arrangement_id=73)
INFO: Building pre-render plan from producer_arrangement
INFO: Calling render_from_plan(render_plan_json=..., audio_source=..., output_path=...)

# Worker path (background job) → render_loop_worker:
INFO: render_loop_worker(arrangement_id=73)
INFO: Using render_plan from arrangement.render_plan_json
INFO: Calling render_from_plan(render_plan_json=..., audio_source=..., output_path=...)
```

Both paths must end with a call to `render_from_plan(...)`.

#### Verify No Dev Fallback in Logs

Ensure the dev fallback did NOT trigger (should not appear in a normal production run):

**DO NOT SEE:**
```
WARN: DEV_FALLBACK_LOOP_ONLY=true; using fallback loop-only render
```

If you see this, check environment variables and ensure `DEV_FALLBACK_LOOP_ONLY` is empty/unset.

✅ **Success Criteria:**
- Logs show `render_from_plan(...)` called for this arrangement
- No mention of "fallback" or "dev mode" render
- Both entry points (API + worker, if worker test is run) show same executor function name

---

### Step 8: Verify No Render Plan Duplicates (Dev Fallback Gating)

**What it tests:** Dev fallback is properly gated by environment variable  
**Expected duration:** < 1 second (verification only)

#### Verify Environment Configuration

```bash
# Check that DEV_FALLBACK_LOOP_ONLY is NOT set to "true"
echo $env:DEV_FALLBACK_LOOP_ONLY

# Should output empty string or not exist
# If it shows "true", remove it:
$env:DEV_FALLBACK_LOOP_ONLY = ""
```

#### Verify Behavior in Code

No production arrangement should synthesize a fallback render plan. This only happens if:

1. `DEV_FALLBACK_LOOP_ONLY=true` AND
2. Rendering fails AND
3. NOT in production environment

**Check logs:** If arrangement was rendered without fallback fallback, you should NOT see:

```
WARN: Building synthetic render plan for dev fallback
```

✅ **Success Criteria:**
- `DEV_FALLBACK_LOOP_ONLY` is empty or unset
- No "dev fallback" or "synthetic render plan" messages in logs
- Arrangement rendered via the normal `render_from_plan` path

---

## Complete E2E Flow Diagram

```
1. UPLOAD LOOP (Step 1)
   ⬇
   {loop_id: 42}

2. GENERATE ARRANGEMENT (Step 2)
   ⬇
   {arrangement_id: 73, status: queued}
   
3. BUILD RENDER PLAN (Unified Pipeline)
   ⬇
   [_build_pre_render_plan() → render_plan_json created]
   
4. INVOKE SHARED EXECUTOR (Unified Pipeline)
   ⬇
   [render_from_plan(render_plan_json, ...) called]
   
5. RENDER AUDIO (Shared Renderer)
   ⬇
   [_render_producer_arrangement() produces audio]
   
6. EXPORT STEMS (DAW Exporter)
   ⬇
   [Stems ZIP created]
   
7. STATUS: COMPLETED (Step 3)
   ⬇
   {status: completed, progress: 1.0}

8. DOWNLOAD AUDIO (Step 4)
   ⬇
   arrangement_73.wav (~60 seconds)

9. DOWNLOAD STEMS ZIP (Step 5)
   ⬇
   arrangement_73_daw_export.zip (section stems + metadata)

10. VERIFY HEALTH (Step 6)
    ⬇
    {ffmpeg_ok: true, ok: true}
```

---

## Failure Triage Section

If any step fails, use this table to find the root cause quickly.

### Step 1: Upload Loop Fails

| Symptom | First Check | Second Check | Action |
|---------|-------------|--------------|--------|
| 413 Payload Too Large | File size > 100MB | Check `MAX_UPLOAD_SIZE` in config | Use a smaller test file |
| 415 Unsupported Media Type | File is MP3 but API says only WAV | Check accepted formats in `/loops/upload` route | Convert to WAV |
| 500 Internal Server | Backend logs show "sqlite3.Error" | Check `DATABASE_URL` connectivity | Verify DB is running and accessible |
| No response / timeout | Network connectivity | Backend running on port 8000 | `curl http://localhost:8000/health/live` |

### Step 2: Generate Arrangement Fails

| Symptom | First Check | Second Check | Action |
|---------|-------------|--------------|--------|
| 404 Loop not found | loop_id in request matches Step 1 response | Query DB for loop record | Re-run Step 1 with correct file |
| 500 Internal Server (ProducerEngine) | Check logs for "ProducerEngine failed" | Is FEATURE_PRODUCER_ENGINE=true? | Set `$env:FEATURE_PRODUCER_ENGINE="true"` and restart |
| 500 render_plan build error | Logs show "Building pre-render plan failed" | Check render_plan.py for syntax errors | Run `pytest tests/services/test_render_plan.py` |
| Status stuck at 'queued' after 30s | Check Redis connection | Check worker queue logs | Verify `REDIS_URL` is set and Redis is running |
| style_profile_json is null | use_ai_parsing=false and no style_text_input provided | Backend logs show LLM parsing skipped | Provide a style_text_input string |

### Step 3: Poll Status Never Completes

| Symptom | First Check | Second Check | Action |
|---------|-------------|--------------|--------|
| Status remains 'queued' | Check if background task started | Look for "render_loop_worker" in logs | Verify Redis and worker queue connectivity |
| Status in 'processing' forever | Check FFmpeg availability | Logs show "FFmpeg not found" or render hangs | Run `ffmpeg -version` in terminal |
| Progress jumps to 1.0 but status != 'completed' | Check for race condition | Logs show render finished but status not updated | May be brief transition; poll again |
| 500 error when polling | Database connection lost | Check DB logs for connection timeout | Restart DB, re-authenticate |

### Step 4: Download Audio Fails

| Symptom | First Check | Second Check | Action |
|---------|-------------|--------------|--------|
| 409 Conflict (not yet complete) | Verify Step 3 shows status='completed' | Check output_url in status response | Wait for arrangement to finish rendering |
| 404 Not Found | output_url is null | Storage backend has audio but URL not set | Check render_executor.py for output_url assignment |
| Downloaded file is 0 bytes | Render completed but audio never written | Check logs for "render_from_plan" completion | Re-run generation with verbose logging |
| Downloaded file is not playable | Audio format corruption | Run ffprobe on downloaded file | Check pydub audio export in render_executor |

### Step 5: DAW Export ZIP Missing or Fails

| Symptom | First Check | Second Check | Action |
|---------|-------------|--------------|--------|
| 404 DAW export not generated | Check arrangement status includes stems_zip_url | Logs show "DAW export generation skipped" | Verify DAWExporter is installed and imported |
| 404 No such file in S3 | Storage backend is S3 | Check S3 bucket for "exports/{id}.zip" key | Verify S3 credentials and permissions |
| ZIP corrupted / won't extract | Download was incomplete | File size is reasonable (> 5MB) | Re-download the file |
| ZIP contains no stems | Stems generation was skipped | Check logs for "DAW exporter" errors | Verify pydub is installed |

### Step 6: Health Check Shows ffmpeg_ok=false

| Symptom | First Check | Second Check | Action |
|---------|-------------|--------------|--------|
| FFmpeg not found | Run `where ffmpeg` in terminal | Is FFmpeg in PATH? | Install FFmpeg or set `FFMPEG_BINARY` path |
| FFprobe not found | Run `where ffprobe` in terminal | Is FFprobe in PATH? | FFprobe typically installed with FFmpeg |
| should_enforce_audio_binaries in PROD | Check `ENVIRONMENT` setting | Is this production mode? | In prod, FFmpeg is required; install it |

### Step 7: Unified Executor Not Called

| Symptom | First Check | Second Check | Action |
|---------|-------------|--------------|--------|
| Logs never show "render_from_plan" | Backend running? | Check for import errors in render_executor.py | `python -c "from app.services.render_executor import render_from_plan"` |
| Arrangement uses old render path | Check render_executor.py is in app/services/ | Verify arrangement_jobs.py imports render_executor | Run `pytest tests/services/test_render_executor_unified_paths.py` |
| Worker uses different executor | Worker still in old codebase? | Check render_worker.py imports from render_executor | Run integration test with worker + API |

### Step 8: Dev Fallback Triggered Unexpectedly

| Symptom | First Check | Second Check | Action |
|---------|-------------|--------------|--------|
| Logs show "fallback render" | Is `DEV_FALLBACK_LOOP_ONLY=true`? | Is environment non-production? | Unset: `$env:DEV_FALLBACK_LOOP_ONLY=""` |
| Render used fallback but should use normal path | Primary render failed? | Check for errors before fallback logic | Fix the primary render error first |

---

## Expected Request/Response Examples

### /api/v1/loops/upload

**Request:**
```bash
POST /api/v1/loops/upload
Form-Data:
  file: (binary audio file)
```

**Expected Response (201):**
```json
{
  "id": 42,
  "filename": "test_loop.wav",
  "bpm": 120,
  "tempo": 120,
  "key": "C",
  "file_key": "uploads/test_loop_12345.wav",
  "filesize_bytes": 2400000,
  "play_url": "/api/v1/loops/42/play",
  "download_url": "/api/v1/loops/42/download",
  "created_at": "2026-03-08T10:20:00Z"
}
```

---

### /api/v1/arrangements/generate

**Request:**
```json
POST /api/v1/arrangements/generate
{
  "loop_id": 42,
  "target_seconds": 60,
  "style_text_input": "upbeat electronic dance music with bright synths",
  "use_ai_parsing": true,
  "include_stems": true
}
```

**Expected Response (202):**
```json
{
  "arrangement_id": 73,
  "loop_id": 42,
  "status": "queued",
  "target_seconds": 60,
  "progress": 0.0,
  "progress_message": "Queued for processing",
  "style_profile_json": {
    "style": "Electronic",
    "intensity": "high",
    "energy_curve": [0.3, 0.5, 0.7, 0.9]
  },
  "producer_arrangement_json": {
    "sections": [
      {"name": "intro", "bars": 4, "tracks": [...]}
    ]
  },
  "render_plan_json": null,  // Will be populated before rendering
  "structure_preview": [
    {"section": "intro", "bars": 4},
    {"section": "verse", "bars": 8}
  ],
  "created_at": "2026-03-08T10:23:45Z"
}
```

**Note:** `render_plan_json` will be null initially, but will be populated before rendering begins.

---

### /api/v1/arrangements/{arrangement_id} (Status Poll)

**Request:**
```bash
GET /api/v1/arrangements/73
```

**Expected Response (200) - In Progress:**
```json
{
  "arrangement_id": 73,
  "loop_id": 42,
  "status": "processing",
  "progress": 0.45,
  "progress_message": "Rendering audio sections...",
  "output_url": "/api/v1/arrangements/73/download",
  "stems_zip_url": "/api/v1/arrangements/73/daw-export/download",
  "render_plan_json": {
    "sections": [
      {"name": "intro", "bar_range": [0, 4], "tracks": 4}
    ],
    "events": [
      {"type": "kick:on", "bar": 0, "timestamp_ms": 0.0}
    ],
    "metadata": {...}
  },
  "timeline_json": null
}
```

**Expected Response (200) - Completed:**
```json
{
  "arrangement_id": 73,
  "loop_id": 42,
  "status": "completed",
  "progress": 1.0,
  "progress_message": "Complete",
  "output_url": "/api/v1/arrangements/73/download",
  "stems_zip_url": "/api/v1/arrangements/73/daw-export/download",
  "render_plan_json": {...},
  "timeline_json": {
    "sections": [
      {
        "name": "intro",
        "start_beat": 0,
        "end_beat": 16,
        "transitions": [...]
      }
    ],
    "events_applied": 24,
    "total_duration_seconds": 60.2
  },
  "completed_at": "2026-03-08T10:24:15Z"
}
```

---

### /api/v1/arrangements/{arrangement_id}/download

**Request:**
```bash
GET /api/v1/arrangements/73/download
```

**Expected Response (200):**
```
[Binary WAV file data - ~2-10 MB]
Headers:
  Content-Type: audio/wav
  Content-Disposition: attachment; filename="arrangement_73.wav"
  Content-Length: 5242880
```

---

### /api/v1/arrangements/{arrangement_id}/daw-export/download

**Request:**
```bash
GET /api/v1/arrangements/73/daw-export/download
```

**Expected Response (200):**
```
[Binary ZIP file data - ~10-50 MB]
Headers:
  Content-Type: application/zip
  Content-Disposition: attachment; filename="arrangement_73_daw_export.zip"
  Content-Length: 31457280

Contents (when extracted):
  metadata.json
  arrangement.wav
  section_intro/
    ├── drums.wav
    ├── bass.wav
    ├── synths.wav
    └── effects.wav
  section_verse/
    ├── drums.wav
    ├── bass.wav
    ├── synths.wav
    └── effects.wav
```

---

### /health/ready

**Request:**
```bash
GET /health/ready
```

**Expected Response (200):**
```json
{
  "ok": true,
  "db_ok": true,
  "redis_ok": true,
  "s3_ok": true,
  "ffmpeg_ok": true,
  "storage_backend": "local"
}
```

---

## Quick Reference Checklist

Print this and check off as you complete each step:

```
Pre-Test:
☐ Backend running on 127.0.0.1:8000
☐ Frontend running on localhost:3000
☐ FEATURE_PRODUCER_ENGINE=true
☐ DEV_FALLBACK_LOOP_ONLY="" (empty)
☐ Health check: ffmpeg_ok=true

Step 1: Upload Loop
☐ HTTP 201 response
☐ loop_id captured
☐ file_key exists
☐ bpm valid

Step 2: Generate Arrangement
☐ HTTP 202 response
☐ arrangement_id captured
☐ render_plan_json in logs (pre-render)
☐ No 404 or 500 errors

Step 3: Poll Status
☐ Status progresses through queued → processing → completed
☐ Progress: 0.0 → 0.5 → 1.0
☐ render_from_plan called (check logs)
☐ Takes < 60 seconds total

Step 4: Download Audio
☐ HTTP 200 response
☐ File > 1 MB
☐ Duration ~ target_seconds ± 2s
☐ Audio plays without errors

Step 5: DAW Export ZIP
☐ HTTP 200 response
☐ ZIP > 5 MB
☐ Extracts successfully
☐ Contains section folders
☐ metadata.json has render_plan

Step 6: Health Check
☐ ffmpeg_ok: true
☐ db_ok: true
☐ redis_ok: true
☐ Overall ok: true

Step 7: Unified Executor
☐ Logs show render_from_plan() called
☐ Both API and worker paths use same function
☐ No "fallback" or "alternate" render mentioned

Step 8: Dev Fallback Gating
☐ DEV_FALLBACK_LOOP_ONLY is empty
☐ No synthetic render plan created
☐ No fallback render messages in logs

Overall:
☐ All 8 steps passed
☐ No warnings or errors in logs
☐ Audio quality sounds good
☐ DAW stems are separate and clean
```

---

## Notes for Production Deployment

1. **FFmpeg is Required:** Ensure `ffmpeg` and `ffprobe` are installed on your production server before deploying. The health check will fail if not found.

2. **Dev Fallback Must Be Disabled:** Always ensure `DEV_FALLBACK_LOOP_ONLY` is empty/unset in production. This mode is only for development testing.

3. **Unified Executor Verification:** If you're migrating from an older version, run `pytest tests/services/test_render_executor_unified_paths.py` to confirm both code paths are using the same executor.

4. **Database Migrations:** Before deploying, ensure `render_plan_json` column exists in the `arrangements` table. Run migrations: `alembic upgrade head`.

5. **Redis Queue:** The arrangement generation uses Redis + background workers. Verify Redis is reachable and workers are running.

6. **S3 Storage (Optional):** If using S3 instead of local storage, verify AWS credentials and bucket permissions before testing.

7. **Monitoring:** Set up alerts for:
   - `ffmpeg_ok=false` in health checks
   - Arrangement status stuck in `processing` > 5 minutes
   - DAW export generation failures
   - render_from_plan errors in logs

---

## 5-Phase Production Hardening Regression Checklist

*Added 2026-04-03 — covers all regression risks addressed across Phases 1–5.*

### Phase 1 — Audio URL Stability

| # | Scenario | Expected | Verified |
|---|----------|----------|---------|
| 1.1 | GET /arrangements/{id} with status=done | output_url and output_file_url are **non-null** and point to fresh presigned URL | ☐ |
| 1.2 | GET /arrangements/{id} with status=done when stored output_url is expired | Fresh URL regenerated from output_s3_key; stale URL **never** returned | ☐ |
| 1.3 | GET /arrangements/?loop_id=X includes a done arrangement | List item has **non-null** output_url derived fresh from output_s3_key | ☐ |
| 1.4 | GET /arrangements/{id} with status=processing | output_url **is null**, progress_message is descriptive | ☐ |
| 1.5 | GET /arrangements/{id} with status=failed | output_url **is null**, error_message is populated | ☐ |
| 1.6 | GET /arrangements/{id} with status=queued | output_url **is null**, progress_message is set or null | ☐ |
| 1.7 | Repeated GET /arrangements/{id} polls (10+) on done arrangement | Same non-null URL every time, player never resets to 0:00 | ☐ |
| 1.8 | GET /health/ready with Redis down | Returns 503 with structured JSON; never crashes | ☐ |
| 1.9 | GET /health/queue with Redis down | Returns 200 with redis_ok=false, error field populated | ☐ |
| 1.10 | GET /health/worker with no workers registered | Returns 200 with ok=false, worker_count=0 | ☐ |

### Phase 2 — DAW Export ZIP

| # | Scenario | Expected | Verified |
|---|----------|----------|---------|
| 2.1 | GET /arrangements/{id}/daw-export on done arrangement | ready_for_export=true, download_url is populated, ZIP created | ☐ |
| 2.2 | GET /arrangements/{id}/daw-export called twice | Second call reuses cached ZIP; same download_url returned | ☐ |
| 2.3 | GET /arrangements/{id}/daw-export on processing arrangement | ready_for_export=false, message field explains why | ☐ |
| 2.4 | GET /arrangements/{id}/daw-export on non-existent ID | 404 response | ☐ |
| 2.5 | GET /arrangements/{id}/daw-export/download before ZIP generated | 404 response, not empty body | ☐ |
| 2.6 | GET /arrangements/{id}/daw-export/download after ZIP generated | 200 with content-type: application/zip, non-empty body | ☐ |
| 2.7 | Downloaded ZIP contains all required files | stems/kick.wav, stems/bass.wav, stems/snare.wav, stems/hats.wav, stems/melody.wav, stems/pads.wav, markers.csv, tempo_map.json, README.txt | ☐ |
| 2.8 | All stem WAV files have identical duration | len(set(durations)) == 1 (DAW alignment requirement) | ☐ |
| 2.9 | ZIP filename in Content-Disposition | `arrangement_{id}_daw_export.zip` | ☐ |

### Phase 3 — Audio Preload Speed

| # | Scenario | Expected | Verified |
|---|----------|----------|---------|
| 3.1 | Time from arrangement done → first GET returning audio_url | < 1 poll cycle (URL is returned in same response that shows status=done) | ☐ |
| 3.2 | Frontend receives output_url immediately in done response | No second round-trip needed to get the audio URL | ☐ |
| 3.3 | Worker sets progress_message at each stage | "Downloading audio" → "Loading audio" → "Rendering" → "Uploading" visible in polls | ☐ |

### Phase 4 — Cache Safety (No Stale URL as Source of Truth)

| # | Scenario | Expected | Verified |
|---|----------|----------|---------|
| 4.1 | Arrangement DB row has expired output_url, fresh output_s3_key | GET regenerates from output_s3_key; expired URL not surfaced | ☐ |
| 4.2 | List endpoint for done arrangements | Each done item gets fresh URL (not DB-cached URL) | ☐ |
| 4.3 | DAW export ZIP already in storage | Reused from storage key; no re-generation | ☐ |
| 4.4 | DAW export ZIP missing from storage | Regenerated and stored; next call reuses | ☐ |
| 4.5 | output_s3_key is null for a done arrangement | Graceful fallback; warning logged; does not 500 | ☐ |

### Phase 5 — UX Progress Messages

| # | Status | Expected progress_message | Verified |
|---|--------|--------------------------|---------|
| 5.1 | queued | null or "Queued" | ☐ |
| 5.2 | processing (early) | "Worker accepted job" | ☐ |
| 5.3 | processing (audio load) | "Loading audio" or "Downloading audio" | ☐ |
| 5.4 | processing (render) | "Rendering" or "Rendering from render_plan_json" | ☐ |
| 5.5 | processing (upload) | "Uploading" | ☐ |
| 5.6 | done | "Arrangement job completed" | ☐ |
| 5.7 | failed | "Worker failed" or specific timeout message | ☐ |

---

## Automated Regression Test Coverage

Run the following test commands to verify regression coverage:

```bash
# Phase 1: Arrangement response contract
python3 -m pytest tests/routes/test_arrangements.py -v

# Phase 2: DAW export end-to-end
python3 -m pytest tests/routes/test_daw_export_route.py -v

# Phase 3: Upload endpoint regression (success, validation failure, storage failure)
python3 -m pytest tests/routes/test_upload_regression.py -v

# All route tests
python3 -m pytest tests/routes/ --ignore=tests/routes/test_loops_s3_integration.py --ignore=tests/services/test_stem_engine.py -v
```

Expected: All tests pass. The `test_loops_s3_integration.py` requires `moto` (pip install moto).

---

## Document History

| Date | Version | Status | Notes |
|------|---------|--------|-------|
| 2026-03-08 | 1.0 | Complete | Initial production smoke test with unified executor |
| 2026-04-03 | 2.0 | Updated | Added 5-phase regression checklist covering audio URL stability, DAW export, preload speed, cache safety, UX progress messages |
| 2026-04-03 | 2.1 | Updated | Production hardening: upload regression tests, structured log events (upload_success/failure, worker_pickup/complete/failure, presigned_url_generated/failed), code comments for critical paths |

---

**Created by:** GitHub Copilot  
**Last Updated:** 2026-04-03  
**Related Tickets:** P1-1 (DAW export), P1-2 (worker unification), P1-3 (FFmpeg readiness), Phase 1–5 production hardening
