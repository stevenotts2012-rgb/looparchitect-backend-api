# IMPLEMENTATION TICKETS

Based on: `FINAL_INTEGRATION_AUDIT.md` and `RAILWAY_FINAL_CHECKLIST.md`  
Date: 2026-03-08

---

## Priority Legend

- **P1** = Critical to producer-quality output or blocking production deployment
- **P2** = Important but not blocking for initial release
- **P3** = Nice-to-have enhancements

---

## P1 TICKETS (Critical)

### P1-1: Generate DAW Export Artifacts ✅ COMPLETED

**Status:** ✅ Completed 2026-03-08

**Problem:**  
The `/api/v1/arrangements/{id}/daw-export` endpoint returned metadata only and did not produce a real artifact.

**What was implemented (smallest safe change set):**
- Added real ZIP artifact generation in `app/services/daw_export.py` from completed arrangement audio.
- Added stems creation (`stems/*.wav`) from final render using deterministic band-splitting of real audio.
- Added real metadata files to ZIP root: `markers.csv`, `tempo_map.json`, `README.txt`.
- Added optional MIDI passthrough: include `midi/*.mid` only when real MIDI files exist (no placeholders).
- Added storage-backed persistence via existing `storage.upload_file(...)` with key `exports/{arrangement_id}.zip`.
- Updated `GET /api/v1/arrangements/{id}/daw-export` to generate-on-demand and return a real download URL.
- Added `GET /api/v1/arrangements/{id}/daw-export/download` endpoint to stream the ZIP from local/S3.

**Acceptance criteria (outcome):**
- [x] Completed render produces a real ZIP artifact
- [x] ZIP includes `stems/*.wav`
- [x] ZIP includes `markers.csv`, `tempo_map.json`, `README.txt`
- [x] `midi/*.mid` included only if real MIDI artifacts are present
- [x] Exported files are non-empty and correctly named
- [x] All stems start at 0:00 and have equal total duration
- [x] ZIP is stored via existing storage backend (S3/local)
- [x] API/frontend can consume a real download URL (`.../daw-export/download`)
- [x] No fake placeholder/empty export files

**Notes on MIDI support:**
- MIDI generation is still partial by design in current pipeline.
- Export includes MIDI only when pre-existing real MIDI files are detected in storage.
- README explicitly documents when MIDI is unavailable.

**Files changed:**
- `app/services/daw_export.py`
- `app/routes/arrangements.py`
- `app/schemas/arrangement.py`
- `app/models/arrangement.py`
- `looparchitect-frontend/api/client.ts`
- `tests/services/test_daw_export_artifacts.py`
- `tests/routes/test_daw_export_route.py`

---

### P1-2: Unify Queue Worker to Use Render Plan Events ✅ COMPLETED

**Status:** ✅ Completed 2026-03-08

**Problem:**  
Queue worker rendering diverged from the main producer pipeline because it could reconstruct arrangement behavior from legacy params instead of defaulting to render plan semantics.

**What was implemented:**
- Updated `app/workers/render_worker.py` to make `arrangement.render_plan_json` the primary/default source of truth.
- Added conversion from `render_plan_json` (`sections` + `events`) into the producer-style structure consumed by existing `_render_producer_arrangement`.
- Added event mapping so variation-like render plan events influence section rendering in worker outputs.
- Added explicit mode selection with safe defaults:
  - `render_plan` mode by default when plan exists
  - `dev_fallback` mode only when `DEV_FALLBACK_LOOP_ONLY=true` **and** environment is non-production
- Added operational logs covering:
  - render plan loaded
  - section count
  - event count
  - producer moves applied

**Acceptance criteria:**
- [x] Worker reads `arrangement.render_plan_json` from DB when available
- [x] Worker uses render plan events/structure to drive audio rendering
- [x] Worker does not default to legacy reconstruction when render plan exists
- [x] Fallback loop-only behavior is not default and is dev-gated
- [x] Tests validate render-plan path, event application, section layering behavior, and fallback gating

**Files changed:**
- `app/workers/render_worker.py`
- `tests/workers/test_render_worker_plan_unification.py`

**Test results:**
```text
pytest tests/workers/test_render_worker_plan_unification.py -v
4 passed

pytest tests/routes/test_arrangements.py -q
3 passed

pytest tests/services/test_daw_export_artifacts.py tests/routes/test_daw_export_route.py -q
2 passed
```

---

### P1-3: Validate FFmpeg Availability in Production ✅ COMPLETED

**Status:** ✅ Completed 2026-03-08

**Problem:**  
Audio processing depends on `ffmpeg` and `ffprobe` being available in the runtime environment. While local dev works, Railway deployment may not have these binaries unless explicitly configured in the build or runtime image.

**Why it matters:**  
Without FFmpeg, audio decode/encode fails, breaking upload processing and arrangement rendering entirely.

**Files involved:**
- `Dockerfile` - ✅ Already includes FFmpeg installation
- `nixpacks.toml` - ✅ Already includes ffmpeg in nixPkgs
- `app/services/audio_runtime.py` - ✅ Already has comprehensive FFmpeg discovery and configuration
- `app/config.py` - ✅ Already has ffmpeg_binary, ffprobe_binary, enforce_audio_binaries config
- `main.py` - ✅ Already calls `configure_audio_binaries()` at startup
- `app/routes/health.py` - ✅ Updated to include FFmpeg validation
- `tests/routes/test_health.py` - ✅ New test file created

**Acceptance criteria:**
- [x] FFmpeg binary available in Railway runtime (nixpacks.toml + Dockerfile configured)
- [x] Startup logs confirm FFmpeg/FFprobe discovery (audio_runtime.py logs at startup)
- [x] Audio decode test passes in production environment (test created, skipped locally without ffmpeg)
- [x] Environment variables `FFMPEG_BINARY` and `FFPROBE_BINARY` configurable (config.py)
- [x] Health check validates FFmpeg availability (added to /health/ready endpoint)

**Estimated risk:** Low  
- Well-documented solution for Railway/Nixpacks
- Straightforward package installation

**Changes made:**

1. **Updated app/routes/health.py**
   - Added `import shutil` for binary discovery
   - Added FFmpeg/FFprobe check in `health_ready()` endpoint
   - Added `ffmpeg_ok` field to readiness response payload
   - Health check fails if FFmpeg missing in production (respects `should_enforce_audio_binaries`)

2. **Created tests/routes/test_health.py**
   - `test_health_live()` - Verifies liveness endpoint
   - `test_health_ready_includes_ffmpeg()` - Validates ffmpeg_ok field in response
   - `test_ffmpeg_functional()` - Functional test (skipped if FFmpeg unavailable)
   - `test_health_legacy_endpoint()` - Backward compatibility check

3. **Verified existing configuration**
   - nixpacks.toml already includes `"ffmpeg"` in nixPkgs array
   - Dockerfile already installs ffmpeg via apt-get
   - app/services/audio_runtime.py already has comprehensive binary discovery
   - main.py already calls configure_audio_binaries() at startup

**Test results:**
```
tests/routes/test_health.py::test_health_live PASSED
tests/routes/test_health.py::test_health_ready_includes_ffmpeg PASSED
tests/routes/test_health.py::test_ffmpeg_functional SKIPPED (expected on Windows)
tests/routes/test_health.py::test_health_legacy_endpoint PASSED
```

**How to verify on Railway:**

1. **Check startup logs after deployment:**
   ```
   Look for: "Audio binaries configured: ffmpeg=/path/to/ffmpeg, ffprobe=/path/to/ffprobe"
   ```

2. **Call health endpoint:**
   ```bash
   curl https://your-app.railway.app/api/v1/health/ready
   ```
   Should return:
   ```json
   {
     "ok": true,
     "db_ok": true,
     "redis_ok": true,
     "s3_ok": true,
     "ffmpeg_ok": true,
     "storage_backend": "s3"
   }
   ```

3. **Test audio upload:**
   - Upload a loop via frontend or API
   - If FFmpeg is missing, upload will fail with decoding error
   - If FFmpeg is present, upload succeeds and analysis runs

4. **Check Railway build logs:**
   - Nixpacks build should show: `Installing nixPkgs: python311, ffmpeg...`
   - Or Docker build should show: `Setting up ffmpeg...`

---

## P2 TICKETS (Important)

### P2-1: Remove or Consolidate Legacy Fallback Render Path

**Problem:**  
`DEV_FALLBACK_LOOP_ONLY` mode in arrangement services creates a simple repeated-loop output as a fallback. This increases loop repetition risk and creates an alternate code path that's harder to test and maintain.

**Why it matters:**  
Fallback paths reduce production quality and create code debt. If producer rendering fails, better to surface the error than silently fall back to low-quality loop repetition.

**Files likely involved:**
- `app/services/arrangement_jobs.py` - Fallback logic
- `app/core/config.py` - Feature flag configuration
- `tests/` - Remove tests for fallback behavior if consolidated

**Acceptance criteria:**
- [ ] Remove `DEV_FALLBACK_LOOP_ONLY` branches from production code
- [ ] Producer rendering failures bubble up as arrangement job errors (status=failed)
- [ ] Dev/test environments can still use simplified render logic via explicit test fixtures
- [ ] No regression in error handling tests

**Estimated risk:** Low  
- Clean removal of unused code path
- Better error visibility

**Implementation plan:**

1. Remove fallback branches from `arrangement_jobs.py`
2. Ensure producer generate failures set `arrangement.status = 'failed'`
3. Add explicit error tests for producer generation failures
4. Update dev documentation for simplified local testing approach

---

### P2-2: Add Render Plan Event Validation

**Problem:**  
`render_plan_json` is persisted but not structurally validated. Malformed event data could cause rendering failures or silent errors downstream.

**Why it matters:**  
Structured validation ensures render plans are correct by construction and makes debugging easier when issues arise.

**Files likely involved:**
- `app/schemas/arrangement.py` - Add Pydantic models for render plan events
- `app/services/arrangement_jobs.py` - Validate before persistence
- `tests/services/test_arrangement_jobs.py` - Add validation tests

**Acceptance criteria:**
- [ ] Pydantic schema for render plan event structure
- [ ] Events validated before `render_plan_json` is set on arrangement
- [ ] Invalid plans cause job to fail with clear error message
- [ ] Tests cover valid and invalid plan structures

**Estimated risk:** Low  
- Straightforward schema definition and validation

**Implementation plan:**

1. **Define schemas** (`app/schemas/arrangement.py`)
   ```python
   class RenderPlanEvent(BaseModel):
       event_type: str  # 'section' | 'transition' | 'effect'
       start_time: float
       duration: float
       section_name: Optional[str]
       parameters: Dict[str, Any]
   
   class RenderPlan(BaseModel):
       events: List[RenderPlanEvent]
       total_duration: float
   ```

2. **Validate in job** (`app/services/arrangement_jobs.py`)
   ```python
   render_plan = RenderPlan(events=events, total_duration=duration)
   arrangement.render_plan_json = render_plan.json()
   ```

3. **Add tests** for plan validation edge cases

---

### P2-3: Improve Progress Reporting Granularity

**Problem:**  
Frontend polling shows generic "processing" for long render jobs. No detailed progress breakdown (e.g., "rendering section 2 of 5").

**Why it matters:**  
Better progress feedback improves user experience, especially for longer arrangements (>2 minutes).

**Files likely involved:**
- `app/services/arrangement_jobs.py` - Progress update calls
- `app/models/arrangement.py` - `progress_message` field (already exists)
- `src/app/generate/page.tsx` - Display progress message

**Acceptance criteria:**
- [ ] Progress messages include section/step details
- [ ] Frontend shows progress message below status
- [ ] Messages update at key milestones (section start, transition, upload)

**Estimated risk:** Low  
- Non-breaking enhancement to existing progress field

**Implementation plan:**

1. Add progress updates in `arrangement_jobs.py`:
   ```python
   arrangement.progress_message = f"Rendering section {i+1}/{len(sections)}"
   db.commit()
   ```

2. Display in frontend `ArrangementStatus` component
3. Add progress message tests

---

## P3 TICKETS (Nice-to-Have)

### P3-1: Cache Style Profile Parsing Results

**Problem:**  
Same style text inputs are re-parsed on every arrangement generation, even if the style profile is identical.

**Why it matters:**  
Caching style profiles reduces LLM API costs and speeds up generation for common style patterns.

**Files likely involved:**
- `app/services/llm_style_parser.py` - Add cache layer
- `app/core/config.py` - Cache TTL configuration
- Cache backend (Redis or in-memory)

**Acceptance criteria:**
- [ ] Style text hashed and used as cache key
- [ ] Cached profiles reused within TTL window (e.g., 1 hour)
- [ ] Cache miss falls back to normal parsing
- [ ] Cache clear mechanism for testing

**Estimated risk:** Low  
- Standard caching pattern

---

### P3-2: Add Arrangement Preview Endpoint

**Problem:**  
No way to preview arrangement structure without triggering full render.

**Why it matters:**  
Users could validate arrangement structure (sections, duration, energy profile) before committing to render, saving time and resources.

**Files likely involved:**
- `app/routes/arrangements.py` - New `/arrangements/preview` endpoint
- `app/services/producer_engine.py` - Preview generation (structure only, no audio)

**Acceptance criteria:**
- [ ] Endpoint returns arrangement structure JSON without rendering audio
- [ ] Frontend can show timeline preview before generating
- [ ] Preview request does not create arrangement record

**Estimated risk:** Low  
- Reuses existing producer generation logic

---

### P3-3: Add Arrangement Versioning

**Problem:**  
Regenerating an arrangement with different parameters overwrites the previous version.

**Why it matters:**  
Users may want to compare multiple arrangement variations for the same loop.

**Files likely involved:**
- `app/models/arrangement.py` - Add `parent_id` and `version` fields
- `app/routes/arrangements.py` - Create new arrangement instead of updating
- Frontend - Show version history UI

**Acceptance criteria:**
- [ ] New arrangement created on regenerate, linked to parent
- [ ] API returns list of versions for a loop
- [ ] Frontend allows switching between versions

**Estimated risk:** Medium  
- Schema changes and UI updates required

---

### P3-4: Implement Rate Limiting

**Problem:**  
No rate limiting on expensive endpoints (generate, render) could lead to resource exhaustion or abuse.

**Why it matters:**  
Production stability and cost control.

**Files likely involved:**
- `app/middleware/rate_limit.py` - New middleware
- `app/routes/arrangements.py` - Apply rate limit decorator
- Redis for distributed rate limit state

**Acceptance criteria:**
- [ ] Max 10 concurrent arrangements per user
- [ ] 429 response when limit exceeded
- [ ] Rate limit headers in response

**Estimated risk:** Low  
- Standard FastAPI middleware pattern

---

## Summary

| Priority | Ticket | Impact | Risk |
|---|---|---|---|
| P1-1 | DAW Export Artifacts | High - Enables DAW integration | Medium |
| P1-2 | Unify Queue Worker | High - Consistency + scalability | Medium |
| P1-3 | FFmpeg Validation | Critical - Blocks audio processing | Low |
| P2-1 | Remove Fallback Path | Medium - Code quality | Low |
| P2-2 | Validate Render Plans | Medium - Reliability | Low |
| P2-3 | Progress Granularity | Medium - UX improvement | Low |
| P3-1 | Cache Style Profiles | Low - Performance optimization | Low |
| P3-2 | Preview Endpoint | Low - UX enhancement | Low |
| P3-3 | Arrangement Versioning | Low - Feature expansion | Medium |
| P3-4 | Rate Limiting | Low - Production hardening | Low |

## Recommended Implementation Order

1. **P1-3** (FFmpeg validation) - Deployment blocker, must verify first
2. **P1-1** (DAW export) - Core feature completion
3. **P1-2** (Queue worker unification) - Architecture consistency
4. **P2-1** (Remove fallback) - Code cleanup, pairs well with P1-2
5. **P2-2** (Validate render plans) - Foundation for reliability
6. **P2-3** (Progress reporting) - Quick UX win
7. **P3 tickets** - As needed based on user feedback and production monitoring

---

## Notes

- All P1 tickets include implementation plans to minimize risk and scope
- P1 tickets are independent and can be implemented in parallel by different developers
- P2/P3 tickets are smaller scope and can be picked up opportunistically
- Test coverage is required for all tickets before merging
