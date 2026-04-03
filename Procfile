# ── Deployment topology ──────────────────────────────────────────────────────
#
# release (Railway / Heroku release phase — runs ONCE before web dynos start):
#   Applies all pending Alembic migrations atomically.  A failed migration
#   aborts the deploy so no live traffic is ever served against a stale schema.
#   Alembic is the single source of truth for schema changes.
#
# Production (recommended — dedicated worker):
#   web:    uvicorn app.main:app  (ENABLE_EMBEDDED_RQ_WORKER defaults to false)
#             → API only; no embedded workers in the web process.
#   worker: python -m app.workers.main
#             → Dedicated async job processor; connects to the same Redis.
#   Both services share the same Redis and PostgreSQL instances.
#
# Local dev / hobby (single-process, opt-in):
#   Set ENABLE_EMBEDDED_RQ_WORKER=true in your .env to run embedded workers
#   inside the web process.  No separate `worker` service is needed.
#   This is NOT the default; it must be explicitly enabled.
#
# ─────────────────────────────────────────────────────────────────────────────
release: python scripts/reconcile_db.py && alembic upgrade head
web: exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python -m app.workers.main