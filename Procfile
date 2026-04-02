# ── Deployment topology ──────────────────────────────────────────────────────
#
# release (Railway / Heroku release phase — runs ONCE before web dynos start):
#   Applies all pending Alembic migrations atomically.  A failed migration
#   aborts the deploy so no live traffic is ever served against a stale schema.
#   Alembic is the single source of truth for schema changes.
#
# Single-process (default, Dockerfile / Railway hobby):
#   The web process starts uvicorn.  app.main enables embedded RQ workers
#   via ENABLE_EMBEDDED_RQ_WORKER=true (default), so no separate worker
#   process is needed.  The `worker` entry below is unused.
#
# Two-process (Railway Pro / dedicated worker):
#   Set ENABLE_EMBEDDED_RQ_WORKER=false on the web service so the web
#   process does NOT run embedded workers.  Scale the `worker` service
#   separately.  The web process no longer double-processes jobs.
#
# ─────────────────────────────────────────────────────────────────────────────
release: alembic upgrade head
web: exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python -m app.workers.main