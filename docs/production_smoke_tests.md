# Production Smoke Tests

## 2-Variation Render Smoke Test (Production Reliability Lock)

Production is locked to **2 variations** for stability.
The third variation is intentionally disabled in production until it is stabilized separately.

Run:

```bash
python scripts/smoke_test_variations.py --base-url https://<your-web-service> --loop-id <LOOP_ID> --timeout-seconds 900 --poll-interval 5
```

## What passing looks like

- Script prints `PRODUCTION_VARIATION_SMOKE_STARTED`.
- Exactly **2 jobs** are returned from `/render-async`.
- Both jobs reach terminal state and emit `PRODUCTION_VARIATION_SMOKE_JOB_TERMINAL`.
- Script prints `PRODUCTION_VARIATION_SMOKE_PASSED` and exits `0`.

## What failure means

- `PRODUCTION_VARIATION_SMOKE_FAILED reason=expected_exactly_2_jobs`: backend did not return exactly 2 jobs.
- `PRODUCTION_VARIATION_SMOKE_FAILED reason=processing_timeout`: one or more jobs stayed non-terminal (e.g. processing/queued) past timeout.
- `PRODUCTION_VARIATION_SMOKE_FAILED reason=exception`: HTTP/network/server error during smoke run.

## Required Railway services

- **web** service (API endpoints `/api/v1/loops/{loop_id}/render-async` and `/api/v1/jobs/{job_id}`)
- **worker** service (RQ worker processing render jobs)
- **Redis** service (job queue backend)

> Important: web and worker must run the same commit SHA.
