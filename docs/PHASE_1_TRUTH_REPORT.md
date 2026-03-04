# LoopArchitect — PHASE 1 Truth Report

**Generated:** March 3, 2026  
**Status:** Pre-implementation scan complete. No code changes made.

---

## 1. SERVICES & ARCHITECTURE

### 1.1 Service Inventory

| Service | Language | Framework | Path | Status |
|---------|----------|-----------|------|--------|
| **Web** | TypeScript | Next.js 14.2.3 | `/looparchitect-frontend` | live on Vercel |
| **API** | Python 3.11 | FastAPI | `/looparchitect-backend-api/app` | live on Railway |
| **Worker** | Python 3.11 | RQ + Redis | `/looparchitect-backend-api/app/workers` | live on Railway |

---

## 2. START COMMANDS & PORTS

### 2.1 Development (Local)

**Frontend:**
```bash
cd looparchitect-frontend
npm run dev
# Runs on http://localhost:3000 (or 3001 if port taken)
```

**Backend API:**
```bash
cd looparchitect-backend-api
./.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# Runs on http://localhost:8000
```

**Worker (local, requires Redis):**
```bash
cd looparchitect-backend-api
./.venv/Scripts/python -m app.workers.main
# Connects to REDIS_URL, processes arrangement jobs
```

### 2.2 Production (Railway/Vercel)

**Procfile (defines Railway multi-process services):**
```
web: sh -c 'uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'
worker: python -m app.workers.main
```

**Port Assignment:**
- Railway auto-assigns `$PORT` env var (typically 8000+)
- Frontend deployed on Vercel (automatic PORT handling)

---

## 3. ENVIRONMENT VARIABLES BY SERVICE

### 3.1 Frontend (`looparchitect-frontend`)

**Source:** `.env.local` (not committed)

| Variable | Purpose | Example |
|----------|---------|---------|
| `BACKEND_ORIGIN` | API endpoint URL | `http://localhost:8000` (dev) or Railway URL (prod) |

**Gap:** No `NEXT_PUBLIC_*` vars. Frontend hardcodes `/api` proxy path.

### 3.2 Backend API (`looparchitect-backend-api`)

**Source:** Environment variables (Railway dashboard or `.env` file locally)

| Variable | Purpose | Required | Default |
|----------|---------|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string | Yes (prod) | `sqlite:///./test.db` (dev) |
| `ENVIRONMENT` | `production` or `development` | No | `development` |
| `STORAGE_BACKEND` | `s3` or `local` | No | Auto-detect based on S3 config |
| `AWS_ACCESS_KEY_ID` | S3 auth | Yes (if S3) | — |
| `AWS_SECRET_ACCESS_KEY` | S3 auth | Yes (if S3) | — |
| `AWS_REGION` | S3 region | Yes (if S3) | — |
| `AWS_S3_BUCKET` | S3 bucket name | Yes (if S3) | — |
| `REDIS_URL` | Redis connection | Yes (prod) | — |
| `FRONTEND_ORIGIN` | CORS origin (fallback) | No | `https://web-production-3afc5.up.railway.app` |
| `CORS_ALLOWED_ORIGINS` | Additional CORS origins (CSV) | No | — |
| `OPENAI_API_KEY` | LLM style parsing | No | — |
| `FEATURE_LLM_STYLE_PARSING` | Enable LLM features | No | `false` |

**Feature Flags:**
- `FEATURE_STYLE_ENGINE` (render custom arrangements: `true`)
- `FEATURE_STYLE_SLIDERS` (style parameter sliders: `false`)
- `FEATURE_VARIATIONS` (multiple variations: `false`)
- `FEATURE_MIDI_EXPORT` (MIDI output: `false`)
- `FEATURE_STEM_EXPORT` (separate stems ZIP: `false`)

### 3.3 Worker

**Inherits all Backend API env vars plus:**

| Variable | Purpose | Required |
|----------|---------|----------|
| `REDIS_URL` | Job queue connection | Yes |

---

## 4. CURRENT CORS CONFIGURATION

**Location:** `app/middleware/cors.py`

**Policy:**
```python
# Always allowed (development):
- http://localhost:3000
- http://localhost:5173

# Production (from env):
- CORS_ALLOWED_ORIGINS (comma-separated)
- or FRONTEND_ORIGIN
- or default: https://web-production-3afc5.up.railway.app
```

**Current Production Origin:**
```
https://looparchitect-frontend.vercel.app
```
(Set via `FRONTEND_ORIGIN` env var on Railway)

---

## 5. CURRENT UPLOAD FLOW

```
User (Browser)
  ↓
Frontend: UploadForm.tsx
  ↓ POST /api/loops/upload (form-data: file)
  ↓
Next.js API Proxy: /api/[...path]
  ↓ forwards to BACKEND_ORIGIN
  ↓
Backend: POST /loops/upload
  ├─ Sanitize filename
  ├─ Validate file (WAV/MP3, size limits)
  ├─ Upload to S3 or local storage → file_key = "uploads/{uuid}.wav"
  ├─ Analyze audio (BPM, key, duration, bars)
  └─ Create Loop record in DB → return loop_id
  ↓
Frontend receives: { id, file_url, bpm, key, etc. }
  ↓
User sees loop_id for arrangement generation
```

**Audio Analysis:**
- Performed via `loop_analyzer.py`
- Uses librosa (BPM detection, key detection)
- Falls back to defaults if analysis fails
- Results stored in Loop model fields: `bpm`, `musical_key`, `duration_seconds`, `bars`

---

## 6. CURRENT ARRANGEMENT GENERATION FLOW

```
User (Browser)
  ↓
Frontend: generate/page.tsx
  ├─ Select loop_id
  ├─ Choose style: preset OR natural language text
  ├─ Optional: AI parsing checkbox
  ├─ Set target duration (seconds)
  ↓
POST /api/v1/arrangements/generate
  ├─ loop_id, target_seconds, style_preset (if preset mode)
  ├─ OR: style_text_input, use_ai_parsing (if NL mode)
  ↓
Backend: POST /api/v1/arrangements/generate
  ├─ Validate loop exists
  ├─ If use_ai_parsing=true AND style_text_input:
  │  └─ Call LLM style parser → StyleProfile (intent, confidence, resolved params)
  │  └─ Fall back to rule-based if LLM unavailable
  ├─ Else if style_preset:
  │  └─ Look up preset → generate style_render_plan
  ├─ Create Arrangement record (status=queued)
  ├─ Queue background job via RQ (Redis)
  └─ Return 202 Accepted + arrangement_id
  ↓
Frontend polls: GET /api/v1/arrangements/{id}
  ├─ Check status (queued → processing → done/failed)
  ├─ When done: download WAV file
  ↓
Worker (Background):
  ├─ Download loop audio from S3
  ├─ Parse style_profile_json (if LLM-generated)
  ├─ Render arrangement via render_phase_b_arrangement()
  │  └─ Repeat loop per section, apply effects
  ├─ Export to temp WAV
  ├─ Upload WAV to S3 → arrangements/{id}.wav
  ├─ Update Arrangement: status=done, output_s3_key, output_url
  └─ Return control to API
  ↓
Frontend downloads: GET /api/v1/arrangements/{id}/download
  └─ Returns single WAV file (audio/wav)
```

---

## 7. CURRENT EXPORT ARTIFACTS

**Today's Output:**
- **Single WAV file** uploaded to S3: `arrangements/{id}.wav`
- **Presigned download URL** valid for 3600 seconds
- **No stem separation**
- **No MIDI export**
- **No markers/structure file**
- **No DAW-import guide**

**Example Response (Download):**
```
Content-Type: audio/wav
Content-Disposition: attachment; filename="arrangement_123.wav"
```

**Gap:** No ZIP package, no stems, no DAW support.

---

## 8. CURRENT API ROUTES

### 8.1 Health & Diagnostics

| Method | Endpoint | Purpose | Returns |
|--------|----------|---------|---------|
| `GET` | `/` | Root health | `{"status":"ok", "version":"1.0.0"}` |
| `GET` | `/health` | Simple health | `{"status":"ok"}` |
| `GET` | `/api/v1/health` | API health | `{"status":"ok", "db":"ok"}` |
| `GET` | `/api/v1/db/health` | DB connection | `{"db_status":"ok"}` |

### 8.2 Loop Management

| Method | Endpoint | Purpose | Request | Response |
|--------|----------|---------|---------|----------|
| `POST` | `/api/v1/loops/upload` | Upload audio | `FormData: file` | `LoopResponse` |
| `GET` | `/api/v1/loops/{id}` | Get loop details | — | `LoopResponse` |
| `GET` | `/api/v1/loops/{id}/download` | Download source | — | WAV bytes |
| `GET` | `/api/v1/loops/{id}/play` | Stream audio | — | Audio stream |
| `GET` | `/api/v1/loops` | List loops | — | `List[LoopResponse]` |

### 8.3 Style Management

| Method | Endpoint | Purpose | Returns |
|--------|----------|---------|---------|
| `GET` | `/api/v1/styles` | List presets | `{"styles": [StylePresetResponse]}` |

### 8.4 Arrangement Generation & Status

| Method | Endpoint | Purpose | Request | Response |
|--------|----------|---------|---------|----------|
| `POST` | `/api/v1/arrangements/generate` | Start generation | `AudioArrangementGenerateRequest` | 202 + `AudioArrangementGenerateResponse` |
| `GET` | `/api/v1/arrangements/{id}` | Check status | — | `ArrangementStatusResponse` |
| `GET` | `/api/v1/arrangements/{id}/download` | Download audio | — | WAV bytes |
| `GET` | `/api/v1/arrangements` | List arrangements | `?loop_id=...` | `List[ArrangementResponse]` |

### 8.5 Frontend API Proxy

| Path | Purpose | Target |
|------|---------|--------|
| `/api/[...path]` | Proxy to backend | `${BACKEND_ORIGIN}/api/...` |

---

## 9. STORAGE ABSTRACTION

**Location:** `app/services/storage.py`

**Interface:**
- `upload_file(file_bytes, content_type, key)` → S3 or local
- `create_presigned_get_url(key, expires_seconds)` → download URL
- `delete_file(key)` → cleanup

**Backends:**
- **S3:** Uses boto3, auto-creates presigned URLs
- **Local:** Stores in `./uploads/` directory, serves via static files

**Configuration:**
```python
storage_backend = "s3" if (ENVIRONMENT=='production' and S3_CONFIG_complete) else "local"
```

---

## 10. RENDER PIPELINE

**Location:** `app/services/arrangement_engine.py`

**Function:** `render_phase_b_arrangement()`

**Input:**
- `loop_audio` (pydub AudioSegment)
- `bpm` (float)
- `target_seconds` (int)
- `sections_override` (list of {name, bars, energy})
- `seed` (int, for randomization)
- `style_params` (dict of rendering parameters)

**Output:**
- `arranged_audio` (pydub AudioSegment)
- `timeline_json` (str with section structure)

**Process:**
1. Repeat loop to fill target duration
2. Apply per-section effects (volume, effects) based on energy/style
3. Export to temporary WAV
4. Return audio + metadata

**Current Gaps:**
- No stem separation within render
- No MIDI generation
- No marker/timing export

---

## 11. STYLE ENGINE V2 (LLM Integration)

**Activated:** ✅ OpenAI API key now set in production

**Location:** `app/services/llm_style_parser.py`

**Flow:**
1. User enters natural language: *"cinematic dark atmospheric synthwave"*
2. Backend receives `style_text_input` + `use_ai_parsing=true`
3. If LLM enabled (`FEATURE_LLM_STYLE_PARSING=true`) and API key set:
   - Call OpenAI GPT → infer intent (archetype, confidence, parameters)
   - Return `StyleProfile` object
4. Else (LLM disabled or API key missing):
   - Fall back to rule-based keyword matching
5. Serialize style profile → JSON → store in Arrangement DB

**Current Status:**
- ✅ LLM client functional (tested on Railway production)
- ✅ Fallback parser active (rule-based keyword matching)
- ✅ Multi-format audio decoder implemented (auto-detect codec)

**Known Issues (Fixed):**
- ❌ ~~Audio decoding ("unknown format 183") - FIXED (ffmpeg fallback strategy)~~

---

## 12. DATABASE SCHEMA

**Location:** `app/models/`

**Key Tables:**

### Loop Model
```python
id: Integer (PK)
name: String
filename: String
file_url: String
file_key: String  # S3 key like "uploads/{uuid}.wav"
bpm: Integer
musical_key: String
duration_seconds: Float
bars: Integer
analysis_json: Text
created_at: DateTime
```

### Arrangement Model
```python
id: Integer (PK)
loop_id: Integer (FK)
status: String  # queued, processing, done, failed
progress: Float  # 0-100
progress_message: String
target_seconds: Integer
output_s3_key: String  # "arrangements/{id}.wav"
output_url: String  # presigned download URL
output_file_url: String (deprecated)
stems_zip_url: String  # (future)
arrangement_json: Text  # timeline with sections
style_profile_json: Text  # V2: LLM-generated style
ai_parsing_used: Boolean  # V2: was LLM used?
error_message: Text
created_at: DateTime
updated_at: DateTime
```

**Migrations:** Alembic (in `migrations/` directory), runs on startup

---

## 13. CURRENT FEATURE FLAGS

| Flag | Status | Purpose |
|------|--------|---------|
| `FEATURE_STYLE_ENGINE` | ✅ true | Custom arrangement rendering |
| `FEATURE_STYLE_SLIDERS` | ❌ false | User parameter sliders |
| `FEATURE_VARIATIONS` | ❌ false | Multiple arrangement variations |
| `FEATURE_BEAT_SWITCH` | ❌ false | Beat-level switching |
| `FEATURE_MIDI_EXPORT` | ❌ false | MIDI file generation |
| `FEATURE_STEM_EXPORT` | ❌ false | Stem ZIP export |
| `FEATURE_PATTERN_GENERATION` | ❌ false | Generative drum patterns |
| `FEATURE_LLM_STYLE_PARSING` | ✅ true (just enabled) | LLM-based style inference |

---

## 14. FRONTEND STRUCTURE

**Pages:**
- `/` : Home + upload form
- `/generate` : Arrangement generation & download
- `(other tabs: history, settings, etc.)`

**Key Components:**
- `UploadForm.tsx` : File upload
- `ArrangementStatus.tsx` : Status display
- `WaveformViewer.tsx` : Audio preview (wavesurfer.js)
- `BeforeAfterComparison.tsx` : Loop vs. arrangement comparison
- `DownloadButton.tsx` : Download arrangement

**API Client:** `api/client.ts`
- Exports functions: `uploadLoop()`, `generateArrangement()`, `getArrangementStatus()`, `downloadArrangement()`
- Base path: `/api` (Next.js proxy)
- No Zod schemas (validation at endpoint level)

---

## 15. KNOWN GAPS & CONSTRAINTS

### Must Fix (Blocking DAW Integration)
1. **No stem separation** → Single WAV only
2. **No MIDI export** → Can't edit beats in DAW
3. **No markers/structure file** → No section markers for import
4. **No DAW import guide** → Users confused about workflow
5. **No ZIP export** → Can't drag-and-drop into DAW

### Should Improve (UX/Performance)
1. **No style input validation** → User wouldn't know bad style text
2. **No style preview before render** → Render is slow, can't iterate fast
3. **No render job history UI** → Hard to track past jobs
4. **No help/tooltips** → Unclear what style text should be
5. **Audio file format detection**: Now fixed ✅

### Technical Debt
1. **Duplicate style configs**: Frontend has presets; backend has different format
2. **No shared Zod schema**: Frontend/backend style validation disconnected
3. **Hardcoded API paths**: `/api` prefix not configurable
4. **No API diagnostics UI**: Can't see if Backend connected from Frontend

---

## 16. RAILWAY DEPLOYMENT STATUS

**Current Production:**
- **Web**: Vercel (https://looparchitect-frontend.vercel.app)
- **API**: Railway (https://web-production-3afc5.up.railway.app)
- **Worker**: Railway (same dyno, separate process)
- **Database**: Railway PostgreSQL
- **Redis**: Railway
- **S3**: AWS

**Environment:** `ENVIRONMENT=production`

**Recent Changes:**
1. ✅ Deployed audio decoding fix (multi-format decoder)
2. ✅ Set OpenAI API key in production
3. ✅ Enabled `FEATURE_LLM_STYLE_PARSING=true` in production
4. ✅ Fixed CORS to allow Vercel origin

---

## STOP: NO CODE CHANGES YET

This Truth Report documents the current state **as-is**. 

**Next steps (PHASES 2-6) will:**
1. Align env vars and CORS (Phase 2)
2. Build Style Direction Engine UX (Phase 3)
3. Implement DAW-ready ZIP exports (Phase 4)
4. Add help guides per tab (Phase 5)
5. Create verification checklist (Phase 6)

**Awaiting confirmation to proceed with Phase 2.**
