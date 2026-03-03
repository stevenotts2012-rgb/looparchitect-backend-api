# Railway Deployment Guide

**LoopArchitect: Full-Stack Audio Loop Architecture Platform**

This guide covers deploying both frontend (Next.js) and backend (FastAPI) on Railway.

---

## Architecture Overview

```
┌─────────────────────┐
│  Web (Frontend)     │
│  Next.js 14.2.3     │
│  PORT: 3000         │
└──────────┬──────────┘
           │ https://
           │ web-production-xxx.railway.app
           │
       ┌───┴────────────────────────┐
       │  Same-origin proxy (Route   │
       │  Handler): /api/*           │
       └───┴────────────────────────┘
           │ forwards to
           │ BACKEND_ORIGIN
           ↓
┌─────────────────────┐
│  API (Backend)      │
│  FastAPI + Uvicorn  │
│  PORT: 8000         │
│  api-production-xxx │
│  .railway.app       │
└─────────┬───────────┘
          │
   ┌──────┴──────┐
   ↓             ↓
PostgreSQL   Redis Queue
(Database)   (RQ Jobs)
   │
┌──┴──────────────────┐
│ Worker Service      │
│ RQ Consumer         │
│ (Background Render) │
└────────────────────┘
```

---

## Service Configuration

### 1. Web Service (Next.js Frontend)

**Railway Service Name:** `looparchitect-frontend`

**Build Command:**
```bash
npm run build
```

**Start Command:**
```bash
npm run start
```

**Environment Variables:**
| Variable | Value | Notes |
|----------|-------|-------|
| `BACKEND_ORIGIN` | `https://api-production-xxxxx.up.railway.app` | URL of API service (from Railway dashboard) |

**Port:** 3000 (Railway auto-configures)

**Health Check:** `GET https://web-production-xxxxx.railway.app/` → Next.js page loads

---

### 2. API Service (FastAPI Backend)

**Railway Service Name:** `looparchitect-backend-api`

**Build Command:**
```bash
(default Python build)
```

**Start Command:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

**Environment Variables:**

#### Core Configuration
| Variable | Value | Required | Notes |
|----------|-------|----------|-------|
| `ENVIRONMENT` | `production` | ✅ Yes | Sets prod mode (validates DATABASE_URL, REDIS_URL) |
| `DEBUG` | `false` | ✅ Yes | Disable debug mode in production |

#### Database
| Variable | Value | Required | Notes |
|----------|-------|----------|-------|
| `DATABASE_URL` | (Railway Postgres auto-provided) | ✅ Yes | PostgreSQL connection string |

#### Redis Queue
| Variable | Value | Required | Notes |
|----------|-------|----------|-------|
| `REDIS_URL` | (Railway Redis auto-provided) | ✅ Yes | Redis connection for RQ jobs |

#### AWS S3 Storage
| Variable | Value | Required | Notes |
|----------|-------|----------|-------|
| `STORAGE_BACKEND` | `s3` | ✅ Yes | Use S3 in production |
| `AWS_REGION` | `us-east-1` (or your region) | ✅ Yes | S3 bucket region |
| `AWS_S3_BUCKET` | (your bucket name) | ✅ Yes | S3 bucket for audio files |
| `AWS_ACCESS_KEY_ID` | (IAM credentials) | ✅ Yes | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | (IAM credentials) | ✅ Yes | AWS secret key |

#### CORS & Frontend
| Variable | Value | Required | Notes |
|----------|-------|----------|-------|
| `FRONTEND_ORIGIN` | `https://web-production-xxxxx.up.railway.app` | ✅ Yes | Frontend URL (for CORS) |

**Port:** 8000 (mapped via `$PORT` env var)

**Health Checks:**
- Liveness: `GET https://api-production-xxxxx.railway.app/health/live` → `200 {"ok": true}`
- Readiness: `GET https://api-production-xxxxx.railway.app/health/ready` → `200 {"ok": true, "db_ok": true, "redis_ok": true, "s3_ok": true}`

**Database Migrations:** Automatic on startup via Alembic

---

### 3. Worker Service (Background Render Jobs)

**Railway Service Name:** `looparchitect-backend-worker`

**Build Command:**
```bash
(default Python build — same as API)
```

**Start Command:**
```bash
python -m app.workers.main
```

**Environment Variables:**
**Use the same environment variables as the API service.** Copy all vars from API to Worker:
- `ENVIRONMENT`, `DEBUG`
- `DATABASE_URL`, `REDIS_URL`
- `STORAGE_BACKEND`, `AWS_REGION`, `AWS_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- `FRONTEND_ORIGIN`

**Critical:** Worker must have identical `REDIS_URL` as API to receive jobs from the same queue.

**Resource Allocation (Recommended):**
- Memory: 512 MB
- CPU: Shared
- (Worker doesn't need much unless rendering is complex; scale as needed)

---

## Step-by-Step Setup on Railway

### 1. Create Railway Project
- Go to [railway.app](https://railway.app)
- Click "New Project" → "GitHub Repo" (or upload/connect)
- Select `looparchitect-backend-api` repo first

### 2. Deploy API Service
- Railway auto-detects Procfile and will offer `web` and `worker` services
- Click "API" (web service) → configure:
  - **Service Name:** `looparchitect-backend-api`
  - **Environment:** Set all vars from Section above
  - **Domains:** Railway auto-assigns (e.g., `api-production-xxxxx.railway.app`)

### 3. Deploy Worker Service
- Click "Deploy" → add `worker` service
  - **Service Name:** `looparchitect-backend-worker`
  - **Environment:** Copy all variables from API
  - Workers don't need public domain

### 4. Deploy Frontend
- In same Railway project (or separate project, if preferred):
  - Add GitHub repo: `looparchitect-frontend`
  - **Service Name:** `looparchitect-frontend`
  - **Environment Variables:**
    - `BACKEND_ORIGIN` = (copy API service URL from Railway)
  - **Domains:** Railway auto-assigns (e.g., `web-production-xxxxx.railway.app`)

### 5. Link Services (Optional but Recommended)
- In Railway project, services can reference each other:
  - Frontend knows API URL from deployment
  - Add `BACKEND_ORIGIN` after API deployment URL is known

---

## Verification Checklist

After all services are deployed:

### Backend / API Service
- [ ] Check logs: `✅ Application startup complete`
- [ ] Check logs: `🔒 CORS Configuration: Allowed origins: [...]`
- [ ] Test liveness: `curl.exe https://api-production-xxxxx.railway.app/health/live`
  - Expected: `200 {"ok": true}`
- [ ] Test readiness: `curl.exe https://api-production-xxxxx.railway.app/health/ready`
  - Expected: `200 {"ok": true, "db_ok": true, "redis_ok": true, "s3_ok": true}`
- [ ] Check logs: `Storage backend: s3 (bucket=..., region=...)`  
  - If you see "Using local file storage", S3 vars are not configured

### Worker Service
- [ ] Check logs: `Heartbeat: Worker running` (appears every 60s)
- [ ] Check logs: No errors on startup

### Frontend / Web Service
- [ ] Open `https://web-production-xxxxx.railway.app` in browser
  - Expected: LoopArchitect UI loads
- [ ] Check Network tab: `/api/v1/...` calls go to correct backend domain

### End-to-End Integration
- [ ] Upload a loop file:
  ```bash
  curl.exe -X POST "https://api-production-xxxxx.railway.app/api/v1/loops/upload" \
    -F "file=@C:\path\to\loop.wav"
  ```
  - Expected: `201 {"id": "...", "filename": "..."}` and file stored in S3
  
- [ ] Trigger a render job:
  ```bash
  curl.exe -X POST "https://api-production-xxxxx.railway.app/api/v1/render" \
    -H "Content-Type: application/json" \
    -d '{"loop_id": "<id>", "bpm": 120, "arrangement": "basic"}'
  ```
  - Expected: `202 {"job_id": "..."}` (async)
  - Worker should process job and download loop from S3

---

## Environment Variables Reference

### All Required Variables

**Create these in Railway UI or via CLI:**

```bash
# File: .railwayenv (for reference only; set in UI)

# Application
ENVIRONMENT=production
DEBUG=false

# Database (Railway auto-provides)
DATABASE_URL=postgresql://postgres:...@postgres-production-xxx.railway.app:5432/...

# Redis (Railway auto-provides)
REDIS_URL=redis://:...@redis-production-xxx.railway.app:...

# Storage
STORAGE_BACKEND=s3
AWS_REGION=us-east-1
AWS_S3_BUCKET=looparchitect-audio
AWS_ACCESS_KEY_ID=(from IAM)
AWS_SECRET_ACCESS_KEY=(from IAM)

# CORS
FRONTEND_ORIGIN=https://web-production-xxxxx.railway.app
```

---

## Common Issues & Troubleshooting

### Issue: Frontend shows "Cannot reach API" or CORS error
**Root Cause:** `BACKEND_ORIGIN` not set or incorrect URL  
**Fix:** 
1. Check frontend service logs for env vars
2. Verify `BACKEND_ORIGIN` matches API service domain exactly
3. Restart frontend service

### Issue: Upload works but files not in S3; logs say "Using local file storage"
**Root Cause:** S3 credentials missing or misconfigured  
**Fix:**
1. Check API service logs at startup
2. Verify `STORAGE_BACKEND=s3` is set
3. Verify all AWS_* vars are present (keys, region, bucket)
4. Confirm IAM credentials have S3 permissions
5. Restart API service

### Issue: Worker crashes immediately or doesn't process jobs
**Root Cause:** Missing `REDIS_URL` or `DATABASE_URL`  
**Fix:**
1. Copy **exact** env vars from API service to Worker service
2. Verify `REDIS_URL` is identical in both
3. Restart worker
4. Check logs: `Heartbeat: Worker running` should appear ~every 60s

### Issue: Database migration fails at startup
**Root Cause:** Migration conflicts or schema mismatch  
**Fix:**
1. Check API logs for exact Alembic error
2. If "column already exists": Migration is idempotent; safe to retry
3. Restart API service
4. If persists, check Railway Postgres logs

### Issue: S3 uploads succeed but downloads fail in worker
**Root Cause:** Worker doesn't have same AWS credentials as API  
**Fix:**
1. Ensure Worker has same `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_S3_BUCKET`
2. Test credentials manually: `aws s3 ls s3://bucket-name`

---

## Scaling & Optimization

### Increase Worker Concurrency (Optional)
By default, worker processes RQ jobs sequentially. To parallelize:
1. Increase `Worker` service replica count on Railway (scales horizontally)
2. Or modify `app/workers/__main__.py` to spawn multiple processes per instance

### Database Optimization
- Enable read replicas on Railway for reports/analytics (if applicable)
- Monitor connection pool via `DATABASE_URL` string

### Redis Optimization
- Monitor job queue depth via Redis Dashboard
- Scale Redis memory if queue backlog grows

---

## Rollback Procedure

If deployment breaks:

1. **Identify failing service:** Check Railway dashboard logs
2. **Revert code:** `git revert <commit-hash>`
3. **Push:** `git push origin main`
4. **Railway auto-redeploys** (if connected to GitHub auto-deploy)
5. **Verify:** Check health endpoints again

---

## Additional Resources

- [Railway Documentation](https://docs.railway.app)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)
- [Next.js Production Deployment](https://nextjs.org/docs/deployment)
- [AWS S3 Setup](https://docs.aws.amazon.com/s3/)
- [Redis Queue (RQ) Docs](https://python-rq.org/)

---

## Support & Questions

For issues:
1. Check Railway service logs
2. Review [RAILWAY_AUDIT_REPORT.md](./RAILWAY_AUDIT_REPORT.md) for known issues
3. Test locally first: `uvicorn app.main:app` and `npm run dev`

