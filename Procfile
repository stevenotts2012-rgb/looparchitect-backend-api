# ── Deployment topology ──────────────────────────────────────────────────────
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
web: exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python -m app.workers.main