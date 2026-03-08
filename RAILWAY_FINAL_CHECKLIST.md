# RAILWAY FINAL CHECKLIST

Date: 2026-03-08
Target: `looparchitect-backend-api` + `looparchitect-frontend`

## 1) Backend Runtime and Startup

- [ ] `PORT` is provided by Railway runtime
- [ ] `ENVIRONMENT=production`
- [ ] App startup logs show:
  - storage backend decision
  - CORS origins
  - feature flags (`feature_producer_engine`, `feature_style_engine`, `feature_llm_style_parsing`)
- [ ] Health endpoints reachable:
  - `/api/v1/health`
  - `/api/v1/health/ready`

## 2) Database and Schema

- [ ] `DATABASE_URL` configured in Railway service variables
- [ ] Startup table reconciliation succeeds (no fatal startup migration errors)
- [ ] `arrangements` table contains required columns:
  - `style_profile_json`
  - `ai_parsing_used`
  - `producer_arrangement_json`
  - `render_plan_json`
  - `progress`
  - `progress_message`
  - `output_s3_key`
  - `output_url`

## 3) Storage Backend

### If using S3 in production

- [ ] `STORAGE_BACKEND=s3` (explicit) **or** S3 vars complete with production auto-select
- [ ] Required vars set:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_REGION`
  - `AWS_S3_BUCKET` (or `S3_BUCKET_NAME`)
- [ ] Upload and download endpoints work against S3:
  - `/api/v1/loops/with-file`
  - `/api/v1/arrangements/{id}/download`

### If using local (non-production/dev)

- [ ] `uploads/` writable
- [ ] Local debug render plans appear as `uploads/{arrangement_id}_render_plan.json`

## 4) Redis / Queue

- [ ] `REDIS_URL` configured (required for queue endpoints and readiness)
- [ ] Redis ping succeeds in health checks
- [ ] If queue APIs are exposed to users, confirm worker process is deployed and consuming jobs

Note: Current frontend generate flow uses the main arrangement background-task pipeline, not the queue render-jobs pipeline.

## 5) CORS + Frontend Connectivity

- [ ] Backend CORS includes frontend origin(s):
  - `CORS_ALLOWED_ORIGINS` or `FRONTEND_ORIGIN`
- [ ] Frontend proxy variable configured:
  - `BACKEND_ORIGIN` (preferred) or `NEXT_PUBLIC_API_URL`
- [ ] Frontend can call through `/api/*` proxy without 502 errors

## 6) Feature Flags

- [ ] `FEATURE_PRODUCER_ENGINE=true` (recommended for producer flow)
- [ ] `FEATURE_LLM_STYLE_PARSING=true` only when `OPENAI_API_KEY` is present
- [ ] Optional flags are intentionally set (or disabled) per environment strategy

## 7) Audio Tooling

- [ ] `ffmpeg` and `ffprobe` available in runtime image, or explicitly configured with:
  - `FFMPEG_BINARY`
  - `FFPROBE_BINARY`
- [ ] No runtime decode failures for common WAV/MP3 upload inputs

## 8) End-to-End Smoke on Railway

- [ ] Upload a loop via frontend Upload page
- [ ] Generate from frontend Generate page with style text + sliders
- [ ] Confirm arrangement reaches `done`
- [ ] Download produced WAV successfully
- [ ] Verify metadata endpoint includes structure/render plan:
  - `/api/v1/arrangements/{id}/metadata`

## 9) Known Production Gaps (Track Explicitly)

- [ ] Queue worker does not currently consume main `render_plan_json` events
- [ ] `/api/v1/arrangements/{id}/daw-export` is metadata/info response, not full file package generation

## 10) Go/No-Go Summary

- **Go** when sections 1–8 are fully checked and section 9 gaps are accepted for this release.
- **No-Go** if health/DB/storage/cors checks fail or frontend cannot complete upload→generate→download.
