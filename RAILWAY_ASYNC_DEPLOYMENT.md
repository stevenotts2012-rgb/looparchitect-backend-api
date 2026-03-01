# Async Render Pipeline - Railway Deployment Guide

## Overview

The async render pipeline requires:
1. **API Service** - FastAPI with async endpoints
2. **Worker Service** - Background job processor (Redis + RQ)
3. **Redis** - Job queue storage (Railway Redis plugin)

This guide explains how to deploy both services to Railway.

## Architecture on Railway

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────┐
│   API Service   │────→│ Redis Queue  │────→│   Worker    │
│ (FastAPI/Render)│     │ (RQ + Redis) │     │ (bg process)│
└─────────────────┘     └──────────────┘     └─────────────┘
        ↓                                            ↓
    PORT 8000              DATABASE_URL          S3 Output
    (public)               (PostgreSQL)          (shared)
```

## Step 1: Add Redis to Railway Project

### Option A: Railway Redis Plugin (Recommended)

1. Go to your Railway project dashboard
2. Click **"Create Service"** → Select **"Redis"**
3. Railway will:
   - Provision a Redis instance
   - Add `REDIS_URL` environment variable automatically
   - Provide connection pooling + TLS

### Option B: External Redis (Upstash)

If Railway's Redis addon is unavailable:

1. Sign up at [upstash.com](https://upstash.com)
2. Create a Redis database
3. Copy connection string (Redis URL)
4. In Railway project settings, add:
   ```
   REDIS_URL=redis://default:PASSWORD@host:port
   ```

## Step 2: Configure API Service (FastAPI)

### Add Environment Variables

In Railway project → Settings → Variables:

```
# Existing variables (keep these)
DATABASE_URL=postgresql://...
AWS_S3_BUCKET=your-bucket
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# New for async pipeline
REDIS_URL=redis://default:...  # Auto-set by Railway Redis addon
LOG_LEVEL=INFO
```

### Verify Start Command

Railway should auto-detect from `Procfile`:
```
web: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
```

This ensures:
- Database migrations run before API starts
- API listens on PORT env var
- Workers can connect to same database

## Step 3: Add Worker Service

### Create Second Service

1. In Railway dashboard, click **"Create Service"**
2. Select **"GitHub Repo"** (same repo)
3. Configure:
   - **Name**: `looparchitect-backend-worker`
   - **Custom Start Command**: `python -m app.workers`
   - **Environment**: Copy from API service (same DB + S3 creds)

### Worker Service Configuration

The worker inherits environment from project:

```bash
# These are auto-inherited from project vars:
DATABASE_URL        # PostgreSQL connection
REDIS_URL          # Redis connection
AWS_S3_BUCKET      # S3 bucket name
AWS_*              # AWS credentials
```

**Start Command**:
```
python -m app.workers
```

This:
1. Connects to Redis (from REDIS_URL)
2. Listens to "render" queue
3. Processes jobs indefinitely
4. Logs to stdout (Railway captures)

### Important: Set Memory & CPU

For worker service:
- **Memory**: 512 MB (minimum)
- **CPU**: 0.5 (shared)
- **Instances**: 1 (can scale later)

Worker can be cheaper than API since it's not always at 100% CPU.

## Step 4: Database Migration on Deploy

The `Procfile` runs migrations automatically:

```
web: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
```

On first deploy:
1. API service starts
2. Runs `alembic upgrade head` → creates `render_jobs` table
3. Starts API server
4. Worker connects to same database

## Step 5: Verify Deployment

### Check API Service Logs

```bash
# Railway CLI (if installed)
railway logs --service looparchitect-backend-api

# Expected output:
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Check Worker Service Logs

```bash
railway logs --service looparchitect-backend-worker

# Expected output:
INFO:app.workers: Connected to Redis...
INFO:rq.worker: Worker started listening to render queue
Waiting for jobs...
```

### Test Async Endpoint

```bash
# Get your Railway domain from dashboard
curl -X POST "https://looparchitect-backend-api-prod.up.railway.app/api/v1/loops/1/render-async" \
  -H "Content-Type: application/json" \
  -d '{"genre": "pop", "length_seconds": 30}'
```

Expected response (202 Accepted):
```json
{
  "job_id": "...",
  "status": "queued",
  "poll_url": "/api/v1/jobs/..."
}
```

### Monitor Job in Worker Logs

In worker service logs, should see:
```
[Job abc123] Starting render for loop 1
[Job abc123] Downloaded audio (4.2 MB)
[Job abc123] Rendering Commercial variation
[Job abc123] Rendering Creative variation
[Job abc123] Rendering Experimental variation
[Job abc123] Uploaded renders to S3
[Job abc123] Succeeded
```

## Troubleshooting Railway Deployment

### Issue: "Redis connection refused"

```
Error: ECONNREFUSED 127.0.0.1:6379
```

**Solution:**
1. Verify `REDIS_URL` is set in Railway project vars
2. Restart worker service: Railway → looparchitect-backend-worker → Redeploy
3. Check Redis service is active: Railway dashboard → looparchitect-backend-redis (should be green)

**Fallback:** Manually set REDIS_URL:
```
REDIS_URL=redis://default:PASSWORD@host:port
```

### Issue: "No such table or view 'render_jobs'"

```
Error: (psycopg2.ProgrammingError) relation "render_jobs" does not exist
```

**Solution:**
1. Manually run migration via Railway CLI:
   ```bash
   railway shell -s looparchitect-backend-api
   alembic upgrade head
   exit
   ```
2. Or restart API service to trigger `alembic upgrade head` in Procfile
3. Wait for logs to show: `INFO [alembic.migration] Running upgrade ... -> render_jobs table`

### Issue: "Worker not processing jobs"

**Checklist:**
1. Worker service is running: Check "Redeploy" completed successfully
2. Worker logs show: "Waiting for jobs..."
3. Redis is connected: Check `REDIS_URL` in both services
4. API service is enqueuing: Check API logs for "Enqueued job..."

**Debug command:**
```bash
# SSH into worker
railway shell -s looparchitect-backend-worker

# Check if listening to queue
echo "LLEN rq:queue:render" | redis-cli -u $REDIS_URL

# Expected: 0 or positive number of pending jobs
```

### Issue: "Job stuck in processing"

**Solution:**
1. Restart worker service: Railway dashboard → Restart
2. Check worker logs for exception in render_loop_worker
3. If S3 upload fails: verify AWS credentials
4. If audio download fails: verify loop has file_key or file_url

## Environment Variables Reference

### Required for API + Worker

```
# PostgreSQL (Railway provision or Railway env vars)
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Redis (Railway Redis addon)
REDIS_URL=redis://default:password@host:19846

# S3 / Audio Storage
AWS_S3_BUCKET=your-bucket
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# Optional logging
LOG_LEVEL=INFO  # or DEBUG for verbose
```

### Optional (Defaults Work)

```
API_HOST=0.0.0.0
API_PORT=${PORT}  # Railway injects this

# Worker settings (already in code)
RENDER_QUEUE_NAME=render  # RQ queue name
RENDER_JOB_TIMEOUT=600    # 10 minutes max per job
RENDER_JOB_RESULT_TTL=3600  # Keep results 1 hour
```

## Scaling the Worker

For high throughput, deploy multiple worker instances:

1. In Railway dashboard, go to worker service
2. Click **"Scaling"** 
3. Set **"Max Instances"** to 2-5
4. Railway auto-scales based on CPU/memory

Each instance:
- Connects to same Redis queue
- Listens to "render" queue
- Processes jobs in parallel

**Cost:** Each instance = 1x worker (0.5 CPU, 512 MB RAM) ≈ $5/month

## Monitoring in Production

### Railway Dashboard Metrics

Worker service should show:
- **CPU**: 10-30% (idle), 70-90% (processing)
- **Memory**: 200-300 MB
- **Logs**: Continuous output while processing

### Production Logging

Worker logs appear in Railway:
```
[Job xyz] Starting render ...
[Job xyz] Downloaded audio (5.2 MB)
[Job xyz] Rendering variant (1/3) - Commercial
[Job xyz] Uploaded output to S3
[Job xyz] Job completed successfully
```

For structured logging, check [PRODUCTION_SETUP_COMPLETE.md](PRODUCTION_SETUP_COMPLETE.md).

## Backup & Persistence

### Redis Backups

Railway Redis addon includes:
- **Daily backups** (auto-retained 7 days)
- **Instant restore** via Railway dashboard
- **Point-in-time recovery** (paid plan)

Jobs are ephemeral (not persisted after completion), so loss is low-risk.

### Database Backups

PostgreSQL backups handled by Railway:
- **Automatic daily backups**
- **7-day retention** (free tier)
- **Point-in-time restore** available

Render jobs are stored in `render_jobs` table, included in backups.

## Cost Estimation

| Component | Cost | Notes |
|-----------|------|-------|
| API Service | ~$5/mo | 0.5 CPU, shared |
| Worker Service | ~$5/mo | 0.5 CPU, shared |
| Redis (Railway) | ~$5/mo | 50 MB |
| PostgreSQL | ~$10/mo | 1 GB included |
| S3 Storage | Variable | Pay per GB stored |
| **Total** | **~$25-50/mo** | Scaling as needed |

## Next Steps After Deployment

1. **Test pipeline**: Use curl to render a loop
2. **Monitor logs**: Watch both API and worker services
3. **Scale if needed**: Add more worker instances for throughput
4. **Enable metrics**: Check Railway monitoring
5. **Update frontend**: Point to async render endpoint

See [LOCAL_QUEUE_DEVELOPMENT.md](LOCAL_QUEUE_DEVELOPMENT.md) for local testing.

## Rollback

If async pipeline has issues:

1. **Disable async endpoint** (use sync fallback):
   - Workers can be stopped temporarily
   - API service handles all requests locally
   - Jobs remain in database for inspection

2. **Restart worker service**:
   ```bash
   railway redeploy -s looparchitect-backend-worker
   ```

3. **Check logs** for root cause in Railway dashboard

## Support

For issues:
1. Check [LOCAL_QUEUE_DEVELOPMENT.md](LOCAL_QUEUE_DEVELOPMENT.md) for debugging
2. Review Railway docs: https://docs.railway.app
3. Check RQ docs: https://python-rq.org
