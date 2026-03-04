# Feature Inventory (Frontend + API + Worker)

## Core Product Features

1. **Loop Upload + Metadata Capture**
   - Upload audio with metadata (`name`, `tempo/bpm`, `bars`, `key`, `genre`)
   - Auto-analysis (BPM/key/bars/duration) with non-fatal fallback
   - Source endpoints: `app/routes/loops.py`, `app/services/loop_analyzer.py`, `app/models/loop.py`

2. **Arrangement Generation (Async)**
   - Generate arrangement jobs from `loop_id` + `target_seconds`
   - Section-based structure generation (`Intro`, `Verse`, `Hook`, `Bridge`, `Outro` etc.)
   - Async job status lifecycle (`queued` → `processing` → `done`/`failed`)
   - Source endpoints: `app/routes/arrangements.py`, `app/services/arrangement_jobs.py`, `app/services/arrangement_engine.py`

3. **Style / Creative Direction Engine**
   - Preset-based style preview and section planning
   - Natural language “type like” parsing via LLM (with rule-based fallback)
   - Slider override mapping (energy/darkness/bounce/warmth/texture)
   - Genre/profile-aware render shaping (Trap/R&B/Pop/Cinematic)
   - Sources: `app/services/style_service.py`, `app/services/llm_style_parser.py`, `app/routes/arrangements.py`, `app/services/arrangement_engine.py`

4. **Render Plan + Timeline Pipeline**
   - Build timeline JSON with sections and bar-level events
   - Emit render profile metadata (`genre_profile`, archetype hints, style signature)
   - Dev artifact output: `uploads/{arrangement_id}_render_plan.json`
   - Source: `app/services/arrangement_engine.py`, `app/services/arrangement_jobs.py`

5. **Job/Worker Queue + Polling**
   - RQ/Redis worker stack for render jobs (separate render-jobs pipeline)
   - Arrangement pipeline uses FastAPI background task path
   - Job status APIs and pollable response models
   - Source: `app/workers/main.py`, `app/workers/render_worker.py`, `app/routes/render_jobs.py`, `app/services/job_service.py`

6. **Storage Backend Selection**
   - S3 in production (if configured), local in dev fallback
   - Presigned URL generation for fetch/download
   - Source: `app/services/storage.py`, `app/config.py`

7. **DB Persistence + Models**
   - Loop, Arrangement, RenderJob persistence
   - Runtime table-creation fallback + Alembic support
   - Source: `app/models/*.py`, `app/db.py`, `app/main.py`, `migrations/`

8. **API Docs / OpenAPI**
   - Auto-registered routers with `/docs`, `/openapi.json`
   - OpenAPI server URL construction for local/public deployments
   - Source: `app/main.py`, `app/routes/__init__.py`

9. **Frontend UX States**
   - Generate screen with polling, history, structure preview, status components
   - Upload flow and download flows
   - Error/success states surfaced in UI
   - Source: `looparchitect-frontend/src/app/generate/page.tsx`, `looparchitect-frontend/api/client.ts`, `looparchitect-frontend/src/components/*`

10. **Help/Guide UX**
    - Inline helper text/tooltips/examples in style controls
    - No full dedicated per-tab guided help system yet
    - Source: `looparchitect-frontend/src/components/StyleSliders.tsx`, `StyleTextInput.tsx`, `DownloadButton.tsx`

11. **Feature Flags / Optional Phase Features**
    - Flags: style engine, LLM parsing, pattern generation, variations, beat switch, MIDI/stems exports
    - Optional dev fallback now explicitly gated by `DEV_FALLBACK_LOOP_ONLY=false` default
    - Source: `app/config.py`, `app/services/arrangement_jobs.py`

12. **Security + CORS + Railway Config**
    - CORS allowlist from env with localhost defaults
    - Startup validation for required production vars
    - Proxy env support (`BACKEND_ORIGIN` with `NEXT_PUBLIC_API_URL` fallback)
    - Source: `app/main.py`, `app/config.py`, `looparchitect-frontend/src/app/api/[...path]/route.ts`
