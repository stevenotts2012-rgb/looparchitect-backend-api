web: sh -c 'python -m app.workers.main & exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'
worker: python -m app.workers.main