# Production Smoke Tests

## 3-Variation Render Smoke Test

Run:

```bash
python scripts/smoke_test_variations.py --base-url https://<your-web-service> --loop-id <LOOP_ID> --timeout-seconds 900 --poll-interval 5
```

## What passing looks like

- Script prints `PRODUCTION_VARIATION_SMOKE_STARTED`.
- Exactly 3 jobs are returned from `/render-async`.
- Each job reaches terminal state and emits `PRODUCTION_VARIATION_SMOKE_JOB_TERMINAL`.
- Script prints `PRODUCTION_VARIATION_SMOKE_PASSED` and exits `0`.

## What failure means

- `PRODUCTION_VARIATION_SMOKE_FAILED reason=fewer_than_3_jobs`: backend did not return 3 jobs.
- `PRODUCTION_VARIATION_SMOKE_FAILED reason=processing_timeout`: one or more jobs never reached terminal within timeout.
- `PRODUCTION_VARIATION_SMOKE_FAILED reason=exception`: HTTP/network/server error during smoke run.

## Required Railway services

- **web** service (API endpoints `/api/v1/loops/{loop_id}/render-async` and `/api/v1/jobs/{job_id}`)
- **worker** service (RQ worker processing render jobs)
- **Redis** service (job queue backend)

> Important: web and worker must run the same commit SHA.
