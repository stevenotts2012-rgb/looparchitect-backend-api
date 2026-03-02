# Railway Deployment (Production)

This project runs as two Railway services:
- API service (FastAPI)
- Worker service (`python -m app.workers`)

Both services must share the same core runtime variables.

## Required Environment Variables (API + Worker)

Set these in both services:

- `ENVIRONMENT=production`
- `DEBUG=false`
- `DATABASE_URL`
- `REDIS_URL`
- `STORAGE_BACKEND` (`local` or `s3`)

If `STORAGE_BACKEND=s3`, also set:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `AWS_S3_BUCKET`

Optional:

- `FRONTEND_ORIGIN` (for explicit frontend CORS origin)

## Start Commands

API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Worker:

```bash
python -m app.workers
```

## Health Verification

Use your Railway API domain:

```bash
curl https://<api-domain>/api/v1/health/live
curl https://<api-domain>/api/v1/health/ready
```

Expected:
- `live` returns HTTP `200` with `{ "ok": true }`
- `ready` returns HTTP `200` with `{ "ok": true, "db_ok": true, "redis_ok": true, "s3_ok": true|false, ... }`
- If dependencies are unavailable, `ready` returns HTTP `503`.

## Download Verification (End-to-End)

```bash
curl -L -o arrangement.wav \
  https://<api-domain>/api/v1/arrangements/<ARRANGEMENT_ID>/download
```

Expected:
- HTTP `200` and audio file downloaded.
- `Content-Disposition` header present.
- `Access-Control-Allow-Origin: *`
- `Access-Control-Expose-Headers: Content-Disposition`

## Local/CI Verification Script

```bash
python scripts/verify_production_pipeline.py
```

Optional env vars for deeper checks:

- `BASE_URL` (default `http://127.0.0.1:8000`)
- `TEST_LOOP_ID`
- `TEST_ARRANGEMENT_ID`

## Railway UI Checklist

1. Set required variables in API service.
2. Set the same required variables in Worker service.
3. Redeploy API and Worker.
4. Confirm API returns `200` on `/api/v1/health/live` and `/api/v1/health/ready`.
5. Trigger one arrangement and verify `/api/v1/arrangements/{id}/download` returns downloadable audio.
