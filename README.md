# LoopArchitect

A music production platform composed of:

- **Backend** – FastAPI (Python) serving the REST API
- **Worker** – RQ background worker that processes render jobs
- **Frontend** – Next.js (TypeScript) user interface

---

## Required Environment Variables

### Backend (`.env`)

Copy `.env.example` to `.env` and fill in the values.

| Variable | Required | Default | Description |
|---|---|---|---|
| `ENVIRONMENT` | No | `development` | Set to `production` in production |
| `DEBUG` | No | `false` | Enable FastAPI debug mode — must be `false` in production |
| `DATABASE_URL` | **Yes (prod)** | SQLite `test.db` | PostgreSQL connection string |
| `REDIS_URL` | **Yes (prod)** | `redis://localhost:6379/0` | Redis connection URL |
| `STORAGE_BACKEND` | No | auto | `local` or `s3` |
| `AWS_ACCESS_KEY_ID` | Yes (S3) | — | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | Yes (S3) | — | AWS credentials |
| `AWS_REGION` | Yes (S3) | — | e.g. `us-east-1` |
| `AWS_S3_BUCKET` | Yes (S3) | — | S3 bucket name |
| `FRONTEND_ORIGIN` | No | — | Production frontend URL for CORS (e.g. `https://yourapp.vercel.app`) |
| `CORS_ALLOWED_ORIGINS` | No | — | Comma-separated extra allowed origins |
| `API_BASE_URL` | No | `http://localhost:8000` | Public backend URL (used for self-referencing links) |
| `ENABLE_EMBEDDED_RQ_WORKER` | No | `true` | Run RQ worker thread inside the web process |
| `MAX_UPLOAD_SIZE_MB` | No | `100` | Maximum file upload size in MB |
| `MAX_REQUEST_BODY_SIZE_MB` | No | `100` | Maximum request body size in MB |
| `RENDER_JOB_TIMEOUT_SECONDS` | No | `900` | Render job timeout |

### Frontend (`.env.local`)

Copy `looparchitect-frontend/.env.local.example` to `looparchitect-frontend/.env.local` and adjust.

| Variable | Required | Description |
|---|---|---|
| `BACKEND_ORIGIN` | **Yes (local dev)** | Server-side URL of the FastAPI backend used by the Next.js proxy. Never exposed to the browser. Example: `http://localhost:8000` |
| `NEXT_PUBLIC_API_URL` | **Yes (production)** | Browser-visible backend origin. Leave **unset** in local dev (the Next.js catch-all proxy handles routing). Set to the deployed backend URL in production, e.g. `https://api.yourapp.com` |

#### How the frontend determines the API base URL

In **local development** `NEXT_PUBLIC_API_URL` is left unset.  
The API client (`src/api/client.ts`) defaults to an empty string, causing all
`fetch` calls to use relative URLs such as `/api/v1/…`.  
These requests are forwarded server-side by the Next.js catch-all proxy
(`src/app/api/[...path]/route.ts`) to the FastAPI backend at
`BACKEND_ORIGIN` (default: `http://localhost:8000`).  
The browser never contacts the backend directly; CORS is never an issue in
this mode.

In **production** set `NEXT_PUBLIC_API_URL` to the deployed backend origin.  
The API client sends requests directly from the browser to that URL; the
Next.js proxy is bypassed.

#### How the backend determines allowed origins

CORS is configured in `app/config.py` (`Settings.allowed_origins`):

1. Local dev origins are **always** included:
   `http://localhost:3000`, `http://127.0.0.1:3000`,
   `http://localhost:5173`, `http://127.0.0.1:5173`
2. Origins from `CORS_ALLOWED_ORIGINS` (comma-separated) are appended.
3. The origin from `FRONTEND_ORIGIN` is appended if set.

The wildcard `*` is never used; production frontends must be listed
explicitly via `FRONTEND_ORIGIN` or `CORS_ALLOWED_ORIGINS`.

---

## Running Locally

### Prerequisites

- Python 3.11+
- Node.js 18+
- Redis (local or Docker: `docker run -p 6379:6379 redis:alpine`)
- FFmpeg (required for audio processing)

### Backend

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — for local dev the defaults work out of the box

# 3. Apply database migrations
alembic upgrade head

# 4. Start the development server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API is available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

### Worker

```bash
# Run from the repository root (same virtual environment as the backend)
python -m app.workers.main
```

The worker connects to `REDIS_URL` (default `redis://localhost:6379/0`), picks
up render jobs from the `render` queue, and logs lifecycle events:
`JOB_START`, `JOB_SUCCESS`, and `JOB_FAILURE`.

### Frontend

```bash
cd looparchitect-frontend

# 1. Install dependencies
npm install

# 2. Configure environment
cp .env.local.example .env.local
# BACKEND_ORIGIN is already set to http://localhost:8000

# 3. Start the dev server
npm run dev
```

Frontend is available at `http://localhost:3000`.

---

## Production Deployment

### Backend

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
```

Or with Gunicorn (recommended for multi-worker deployments):

```bash
gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:${PORT:-8000}
```

### Worker

```bash
python -m app.workers.main
```

Run this as a separate process/container from the backend.  
Set `ENABLE_EMBEDDED_RQ_WORKER=false` on the backend when using a dedicated
worker process to avoid duplicate workers.

### Frontend

```bash
cd looparchitect-frontend

# Build
npm run build

# Start production server
npm start
```

Or deploy to Vercel / Railway — the `looparchitect-frontend` directory is the
Next.js application root.

---

## Procfile (Railway / Heroku)

```
web:    sh -c 'python -m app.workers.main & exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'
worker: python -m app.workers.main
```

For dedicated worker dynos, set `ENABLE_EMBEDDED_RQ_WORKER=false` on the web
process so only the `worker` dyno runs RQ jobs.
