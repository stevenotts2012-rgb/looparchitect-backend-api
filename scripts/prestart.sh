#!/usr/bin/env sh
# prestart.sh — run Alembic migrations before the web process starts.
#
# Used by the Dockerfile CMD so that Docker-based deployments always apply
# pending migrations atomically before uvicorn begins serving traffic.
#
# Railway / Heroku deployments use the `release` phase in the Procfile
# instead and do NOT need this script.
#
# Usage (see Dockerfile):
#   CMD ["sh", "scripts/prestart.sh"]
set -e

echo "==> Running Alembic migrations..."
alembic upgrade head
echo "==> Migrations complete. Starting web server..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
