# Style Engine Discovery Plan

## Scope
This document captures discovery only (no behavior changes yet) for adding a style-aware arrangement engine that remains backward compatible with existing endpoints and storage abstraction.

## Current Pipeline (As-Is)

### Backend data models
- `app/models/loop.py`
  - Loop source metadata and storage pointers (`file_key`, `file_url`, bpm/bars/key).
- `app/models/arrangement.py`
  - Arrangement job record (`status`, `target_seconds`, `genre`, `intensity`, `include_stems`, `arrangement_json`, output fields).
- `app/models/job.py`
  - Async render job tracking (`render_jobs`) with queue status/progress/output.

### Backend routes and flow
- Upload / loop source:
  - `POST /api/v1/loops/with-file` (`app/routes/loops.py`) uploads + analyzes + creates Loop row.
  - `GET /api/v1/loops/{id}/play` and `/download` (`app/routes/audio.py`) verify source file exists and return stream/download URL.
- Arrangement generation:
  - `POST /api/v1/arrangements/generate` (`app/routes/arrangements.py`) validates loop source, creates `arrangements` row with `queued`, launches background task.
  - `GET /api/v1/arrangements` list, `GET /api/v1/arrangements/{id}` status, `GET /api/v1/arrangements/{id}/download` output fetch.
- Async render jobs (separate path):
  - `POST /api/v1/loops/{loop_id}/render-async` + `/api/v1/jobs/{job_id}` (`app/routes/render_jobs.py`) backed by Redis/RQ.

### Generation execution points
- Synchronous-background arrangement path:
  - `app/services/arrangement_jobs.py::run_arrangement_job`
  - Calls `app/services/arrangement_engine.py::render_phase_b_arrangement`
  - Uploads output through `app/services/storage.py` (S3/local abstraction preserved).
- Redis worker path:
  - `app/workers/render_worker.py::render_loop_worker`
  - Pulls jobs from queue and generates multiple transformed variations from `app/routes/render.py` helpers.

### Frontend generation integration
- `looparchitect-frontend/src/app/generate/page.tsx`
  - Calls generate endpoint, polls arrangement status, shows recent generations.
- `looparchitect-frontend/api/client.ts`
  - Typed API calls for generate/list/status/download/validate source.

## Existing Constraints Found in Repo
- Storage abstraction already centralized in `app/services/storage.py`.
- Router registration is auto-discovered in `app/routes/__init__.py` with explicit prefix config.
- Migrations already include some idempotent patterns (e.g., try/except around column add in `005_add_arrangement_s3_fields.py`).

## Style Engine Insertion Points (Minimal + Safe)

### 1) New style engine domain package (pure logic first)
- Add `app/style_engine/` modules for presets, seed, arrangement plan, energy curve, drums/bass/melody/transitions.
- Keep generators pure and deterministic using seeded RNG.
- No endpoint behavior change until integrated via flags.

### 2) API extension without breaking current contract
- Extend `AudioArrangementGenerateRequest` with optional fields:
  - `style_preset`, `style_params`, `seed`, `variation_count`.
- Keep old fields and defaults intact so existing frontend payloads still work.
- Extend response with optional new fields only:
  - `render_job_ids`, `seed_used`, `style_preset`, `structure_preview`.

### 3) Arrangement persistence updates
- Add optional arrangement columns:
  - `style_preset`, `style_params`, `seed`, `structure`, `midi_s3_key`, `stems_s3_prefix`.
- Use idempotent Alembic migration with existence checks / guarded adds.

### 4) Generation pipeline integration
- In `run_arrangement_job`, build a deterministic section plan before render.
- Persist structure JSON and feed section plan to renderer.
- Keep current audio output behavior as baseline fallback when style features are disabled.

### 5) New styles endpoint
- Add `GET /api/v1/styles` route returning preset metadata/defaults.
- No impact on existing routes.

### 6) Frontend non-breaking additions
- Add optional preset selector + optional seed + optional sliders gated by feature flags.
- Existing generate UX remains valid with default payload.

## Feature Flags (Planned)
- `FEATURE_STYLE_ENGINE` (master gate for style-aware structure generation)
- `FEATURE_STYLE_SLIDERS`
- `FEATURE_VARIATIONS`
- `FEATURE_BEAT_SWITCH`
- `FEATURE_MIDI_EXPORT`
- `FEATURE_STEM_EXPORT`

Behavior when disabled: silently fallback to current generation flow and existing schema defaults.

## Minimal File Touch Plan (Phase 0–1 oriented)

### Backend (new)
- `app/style_engine/__init__.py`
- `app/style_engine/types.py`
- `app/style_engine/presets.py`
- `app/style_engine/seed.py`
- `app/style_engine/energy_curve.py`
- `app/style_engine/arrangement.py`
- `app/style_engine/drums.py`
- `app/style_engine/bass.py`
- `app/style_engine/melody.py`
- `app/style_engine/transitions.py`
- `app/style_engine/validators.py`
- `app/style_engine/export_midi.py`
- `app/style_engine/export_stems.py`
- `app/style_engine/render.py`
- `app/services/style_service.py`
- `app/routes/styles.py`
- `migrations/versions/<new>_add_style_fields_to_arrangements.py`
- `tests/style_engine/test_presets.py`
- `tests/style_engine/test_arrangement_plan.py`
- `tests/style_engine/test_seed_determinism.py`

### Backend (existing modifications)
- `app/routes/__init__.py` (register styles router)
- `app/schemas/arrangement.py` (optional request/response fields)
- `app/models/arrangement.py` (new nullable columns)
- `app/services/arrangement_jobs.py` (inject structure plan generation + persistence)
- `app/services/arrangement_engine.py` (optional section-plan-aware rendering hook)
- `app/config.py` (feature flags)

### Frontend
- `looparchitect-frontend/api/client.ts` (types + optional style payload + styles endpoint client)
- `looparchitect-frontend/src/app/generate/page.tsx` (preset selector, optional seed/sliders/variation count)
- `looparchitect-frontend/src/components/` (small UI controls only if needed)

## Risks & Mitigations
- Risk: Endpoint contract drift.
  - Mitigation: all new request fields optional; old request body remains valid.
- Risk: Storage regressions.
  - Mitigation: continue using `storage` abstraction only; no direct path hardcoding in new modules.
- Risk: Non-deterministic output.
  - Mitigation: centralized seeded RNG utility and pure generator tests.
- Risk: Migration safety.
  - Mitigation: idempotent guarded migration operations.

## Discovery Conclusion
Current architecture already supports safe insertion of a style layer primarily at:
1) schema/model optional extension,
2) pre-render structure planning in arrangement job service,
3) optional frontend payload enrichment.

No endpoint removals are required.

## Phase 0 Status (Implemented)
- Added isolated `app/style_engine/` skeleton modules with typed models and deterministic RNG utilities.
- Added built-in presets for: ATL, Dark, Melodic, Drill, Cinematic, Club, Experimental.
- Added pure helper modules for arrangement planning, drums, bass, melody, transitions, validators, and export placeholders.
- Added `app/services/style_service.py` and a non-registered skeleton route file `app/routes/styles.py`.
- Added focused tests under `tests/style_engine/` for preset inventory, seed determinism, and deterministic section planning.
- No existing API route registration was changed in this phase; runtime behavior remains backward compatible.

## Phase 1 Status (Implemented)
- Added `GET /api/v1/styles` endpoint and frontend style preset + seed controls.
- Extended generate request/response with optional style fields while preserving backward compatibility.
- Added idempotent migration for style columns on `arrangements`.
- Persisted structure preview safely using existing `arrangement_json` field for pre-migration compatibility.

## Phase 2 Status (Implemented)
- Hooked style section plan into render path in `run_arrangement_job` when `FEATURE_STYLE_ENGINE=true`.
- Added deterministic section energy shaping in `render_phase_b_arrangement`:
  - low energy: reduced density/brightness,
  - mid energy: subtle trim,
  - high energy: increased presence.
- Preserved existing fallback render behavior when style plan is absent or feature flag is disabled.
- Added tests for section override rendering and style-section parsing.

## Phase 3 Status (Implemented)
- Added audio synthesis module (`app/style_engine/audio_synthesis.py`) for converting pattern data structures to audio:
  - Drum synthesis using filtered sine waves and noise bursts
  - Bass synthesis using sine wave fundamentals with harmonics
  - Melody synthesis using pitched sine tones
- Integrated pattern generation into arrangement engine:
  - Added `FEATURE_PATTERN_GENERATION` flag for gradual rollout
  - Modified `render_phase_b_arrangement` to accept seed parameter
  - Added `_generate_and_mix_patterns` helper that generates and mixes drum/bass/melody patterns per section
  - Section-aware pattern density (intro/outro: low, verse: medium, hook: high, bridge: varied)
  - Configurable mix level (30% by default) for generated patterns
- Enhanced data storage:
  - Modified arrangement route to wrap structure and seed in `arrangement_json` as `{"seed": X, "sections": [...]}`
  - Added `_parse_seed_from_json` helper in job worker to extract seed
  - Maintains backward compatibility with legacy array format
- Added comprehensive tests:
  - 8 audio synthesis tests (determinism, multi-bar rendering, pattern mixing)
  - 7 pattern generation integration tests (feature gating, determinism, section types)
  - 6 job worker tests (seed extraction, wrapped format support)
- All existing tests remain green (48 total tests passing)
