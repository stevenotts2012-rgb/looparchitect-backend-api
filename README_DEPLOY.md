# LoopArchitect Backend API - Deployment Guide

This guide covers deploying the FastAPI backend on **Railway** and **Render** platforms.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Local Development](#local-development)
- [Railway Deployment](#railway-deployment)
- [Render Deployment](#render-deployment)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

- Python 3.11+
- Git and GitHub account
- Railway or Render account
- (Optional) PostgreSQL database URL for production

---

## Local Development

### 1. Clone and Install

```bash
git clone https://github.com/yourusername/looparchitect-backend-api.git
cd looparchitect-backend-api
python -m venv .venv

# Activate venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -e .
pip install -e ".[dev]"  # Includes pytest and test tools
```

### 2. Run Tests

```bash
pytest tests/test_smoke.py -v
```

### 3. Run Locally

```bash
uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/docs (Swagger UI) to explore the API.

---

## Railway Deployment

### 1. Connect GitHub to Railway

1. Go to [railway.app](https://railway.app)
2. Sign in with GitHub
3. Create a new project: **"Deploy from GitHub repo"**
4. Select your repository

### 2. Configure Environment Variables

In Railway dashboard, go to **Variables** and add (if needed):

```
RENDER=false                          # Not running on Render
DEBUG=false                           # Disable debug mode in production
DATABASE_URL=postgresql://...        # If using PostgreSQL
FRONTEND_ORIGIN=https://myapp.com    # Adjust to your frontend domain
```

**Notes:**
- `requirements.txt` is auto-detected by Railway
- `Procfile` specifies the start command (already configured)
- `runtime.txt` specifies Python version (3.11.x)

### 3. Trigger Deploy

Railway auto-deploys when:
- You push commits to the main branch
- Environment variables change

Deployment takes 2-5 minutes.

### 4. Verify Deployment

Once deployment completes:

```bash
# Health check
curl https://your-service.railway.app/health
# Expected: {"ok":true}

# Root endpoint
curl https://your-service.railway.app/
# Expected: {"status":"ok","message":"LoopArchitect API","version":"1.0.0","docs":"/docs"}

# Swagger UI
open https://your-service.railway.app/docs
```

---

## Render Deployment

### 1. Connect GitHub to Render

1. Go to [render.com](https://render.com)
2. Sign in with GitHub
3. Create a new **Web Service**
4. Select your repository

### 2. Configure Service

| Setting | Value |
|---------|-------|
| **Name** | looparchitect-backend-api |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

### 3. Configure Environment Variables

In Render dashboard, go to **Environment** and add:

```
DEBUG=false
DATABASE_URL=postgresql://...        # If using PostgreSQL
FRONTEND_ORIGIN=https://myapp.com    # Adjust to your frontend domain
```

### 4. Trigger Deploy

Click **Deploy** to start the first deployment (2-5 minutes).

Subsequent deployments are auto-triggered when you push to `main`.

### 5. Verify Deployment

Once deployment completes:

```bash
# Set your Render domain
RENDER_URL="https://your-service.onrender.com"

# Health check
curl $RENDER_URL/health

# Root endpoint
curl $RENDER_URL/

# Swagger UI
open $RENDER_URL/docs
```

---

## Port Binding & Environment

Both Railway and Render:
- Inject a `$PORT` environment variable (dynamic port assignment)
- Expect the app to bind to `0.0.0.0:<PORT>`
- Use the unified start command:

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

This is already configured in `Procfile` (for Railway) and the Render start command.

---

## File Structure

The project is set up for standard Python packaging:

```
looparchitect-backend-api/
├── Procfile                    # Railway start command
├── runtime.txt                 # Python 3.11.x
├── requirements.txt            # All dependencies with pinned versions
├── pyproject.toml              # Project config + pytest, build tools
├── pytest.ini                  # Test discovery + pythonpath
├── main.py                     # Entry point: FastAPI app instance
├── app/
│   ├── __init__.py            # Empty (makes app a package)
│   ├── main.py                # Same as root main.py (legacy, can be ignored)
│   ├── config.py              # Settings (loaded from .env or env vars)
│   ├── db.py                  # SQLAlchemy engine + session factory
│   ├── models/                # SQLAlchemy ORM models
│   ├── schemas/               # Pydantic request/response schemas
│   ├── routes/                # FastAPI routers (health, loops, arrange, etc.)
│   ├── services/              # Business logic (storage, audio analysis, etc.)
│   ├── middleware/            # CORS, logging, etc.
│   └── db/                    # Database utilities
├── tests/
│   ├── test_smoke.py         # End-to-end API tests using TestClient
│   └── ...
├── migrations/                # Alembic database schema migrations
├── uploads/                   # Local storage for uploaded files (auto-created)
└── renders/                   # Rendered audio files (auto-created)
```

---

## Troubleshooting

### Build Fails: "No module named 'app'"

**Cause:** PYTHONPATH not set or `app` is not a proper package.

**Solution:**
```bash
# Ensure app/__init__.py exists (should be empty)
touch app/__init__.py

# Reinstall the project in editable mode
pip install -e .
```

### Import Error: "cannot import name 'LoopCreate' from app.models.schemas"

**Cause:** Schemas file has syntax errors or incorrect structure.

**Solution:**
```bash
# Verify schemas.py syntax
python -c "from app.models.schemas import LoopCreate; print('OK')"

# If error, check app/models/schemas.py for indentation/syntax
```

### Tests Fail Locally but Work on Railway/Render

**Cause:** Missing development dependencies or environment variables.

**Solution:**
```bash
# Install dev dependencies
pip install -e ".[dev]"

# Set minimal env (or use .env file)
export DATABASE_URL="sqlite:///test.db"

# Run tests
pytest tests/test_smoke.py -v
```

### Service Starts but Returns 502 on Railway/Render

**Cause:** Failed database initialization or missing startup migration.

**Solution:**
1. Check logs: Railway dashboard → **Logs** or Render dashboard → **Logs**
2. Look for database connection errors or migration issues
3. If using PostgreSQL, verify `DATABASE_URL` is correct and the DB is accessible

### CORS Errors When Calling from Frontend

**Cause:** Frontend origin not in allowed list.

**Solution:**
1. Set `FRONTEND_ORIGIN` environment variable:
   ```
   FRONTEND_ORIGIN=https://yourfrontend.example.com
   ```
2. Or update `allowed_origins` in `app/config.py`

---

## Key Start Commands

### Development (Local)
```bash
uvicorn app.main:app --reload --port 8000
```

### Production (Railway/Render)
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The `$PORT` variable is automatically provided by Railway and Render.

---

## FAQ

**Q: Which database should I use?**
- Development: SQLite (default, no setup needed)
- Production: PostgreSQL (recommended for multi-instance deployments)

**Q: How do I run migrations in production?**
- Migrations run automatically on app startup (see `run_migrations()` in `main.py`)
- Manual migration: Set `DATABASE_URL` and run `alembic upgrade head`

**Q: Can I deploy to both Railway and Render at the same time?**
- Yes! Each platform pulls from your GitHub repo independently
- They will both pull the same `main` branch
- Use the same `requirements.txt` and `Procfile` for both

**Q: How do I set environment variables?**
- Railway: Dashboard → Variables tab
- Render: Dashboard → Environment tab
- Local: Create a `.env` file (ignored by git)

---

## Next Steps

1. Push code to GitHub: `git push origin main`
2. Choose your platform (Railway or Render above)
3. Monitor the build in the platform's dashboard
4. Test the live endpoint with `curl` or Swagger UI at `/docs`
5. Set up a frontend to call your API endpoints

Good luck! 🚀
