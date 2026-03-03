# Railway Deployment Audit Report
**LoopArchitect Backend + Frontend**
**Date: March 2, 2026**

---

## Executive Summary

✅ **Overall Readiness: 80%**  
The project has solid foundations: proper CORS config, idempotent migrations, health endpoints, and structured storage logic. However, **10 critical issues** must be resolved before production deployment.

---

## REPO INVENTORY

### Backend Structure
- **Framework:** FastAPI 0.109.0 + Uvicorn
- **Database:** PostgreSQL (Alembic migrations)
- **Job Queue:** Redis Queue (RQ)
- **Storage:** Dual-backend (local/S3)
- **Entrypoint:** `app.main:app` (via Procfile: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`)
- **Worker:** `app.workers.render_worker:main` (separate service via `app/workers/__main__.py`)
- **Config:** `app/config.py` (pydantic-settings)
- **Migrations:** Alembic in `migrations/versions/`

### Frontend Structure  
- **Framework:** Next.js 14.2.3 + React 18.3.1 + TypeScript
- **Deployment:** Node.js server (`npm run build && npm run start`)
- **API Proxy:** Next.js Route Handler (`src/app/api/[...path]/route.ts`)
- **Env Config:** `.env.local.example` with `BACKEND_ORIGIN`

### Deployment Config
- **Procfile:** ✅ Correct (web service only)
- **nixpacks.toml:** ✅ Correct (Python build)
- **railway.toml:** ❌ Not present (optional, can use UI)
- **Docker:** Present but not Railway-primary

---

## 🚨 TOP 10 RAILWAY RISKS (ORDERED BY SEVERITY)

### **RISK #1: Worker Service Not Defined [CRITICAL]**
**Status:** ⚠️ Broken  
**Impact:** Render jobs silently fail; users cannot generate arrangements/renderings  
**Root Cause:** Procfile only has `web:` service; no `worker:` service defined  
**Current State:**
```plaintext
# Procfile (INCOMPLETE)
web: sh -c 'uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'
# ❌ Missing: worker service
```
**Fix Required:** Add worker service to Procfile for Railway  
**Severity:** 🔴 CRITICAL — Renders won't execute

---

### **RISK #2: Worker Imports settings via os.getenv() Not app.config [CRITICAL]**
**Status:** ⚠️ Inconsistent  
**Impact:** Worker may have misaligned S3 config compared to API; S3 downloads fail in worker  
**Root Cause:** `app/workers/render_worker.py` lines 59–66 read `AWS_REGION`, `AWS_S3_BUCKET`, etc. directly via `os.getenv()` instead of importing `from app.config import settings`  
**Current State:**
```python
# ❌ BAD: render_worker.py (line 59)
region = os.getenv("AWS_REGION")
bucket = os.getenv("AWS_S3_BUCKET")
```
```python
# ✅ GOOD: storage_service.py
from app.config import settings
backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
```
**Fix Required:** Import `settings` in worker; use `settings.aws_region`, `settings.aws_s3_bucket`  
**Severity:** 🔴 CRITICAL — S3 auth failures in worker

---

### **RISK #3: .env.example Still References Render Platform [HIGH]**
**Status:** ⚠️ Outdated documentation  
**Impact:** Developers confused; copy-paste examples won't work; incorrect env vars for Railway  
**Root Cause:** `.env.example` contains:
```dotenv
RENDER_EXTERNAL_URL=https://your-app.onrender.com  # ❌ Render, not Railway
```
**Fix Required:** Rewrite `.env.example` for Railway with correct variable names and descriptions  
**Severity:** 🟠 HIGH — Documentation/onboarding issue

---

### **RISK #4: Missing REDIS_URL in .env.example [MEDIUM]**
**Status:** ⚠️ Incomplete  
**Impact:** Developer confusion; Railway requires REDIS_URL for RQ jobs  
**Root Cause:** `.env.example` missing `REDIS_URL` variable (present in `app/config.py` but not documented)  
**Fix Required:** Add `REDIS_URL` and `STORAGE_BACKEND` to `.env.example`  
**Severity:** 🟡 MEDIUM — Runtime would fail without it on Railway

---

### **RISK #5: No Explicit STORAGE_BACKEND in .env.example [MEDIUM]**
**Status:** ⚠️ Missing  
**Impact:** Users unsure if they should set `STORAGE_BACKEND=s3` on Railway  
**Root Cause:** `.env.example` does not include `STORAGE_BACKEND` (defaults to "local" in config.py)  
**Fix Required:** Add to `.env.example`: `STORAGE_BACKEND=local  # or s3`  
**Severity:** 🟡 MEDIUM — Production won't use S3 unless explicitly configured

---

### **RISK #6: Frontend .env.local Not .gitignore'd [MEDIUM]**
**Status:** ⚠️ Security  
**Impact:** `.env.local` file tracked in git if not explicitly ignored  
**Root Cause:** Frontend's `.env.local` may contain `BACKEND_ORIGIN` pointing to production  
**Current State:**  
```dotnev
BACKEND_ORIGIN=https://web-production-3afc5.up.railway.app  # ✅ Public URL (safe)
```
**Fix Required:** Ensure `.gitignore` includes `.env.local` and `.env*.local`  
**Severity:** 🟡 MEDIUM — Best practice / security hardening

---

### **RISK #7: No Frontend NEXT_PUBLIC_API_BASE Env Var [MEDIUM]**
**Status:** ⚠️ Missing  
**Impact:** Frontend API proxy may fail if BACKEND_ORIGIN not set; no fallback  
**Root Cause:** `src/app/api/[...path]/route.ts` reads `BACKEND_ORIGIN` from env; if missing, returns 500  
**Current State:**
```typescript
// src/app/api/[...path]/route.ts
const backendUrl = process.env.BACKEND_ORIGIN;
if (!backendUrl) {
    return new Response(JSON.stringify({ error: 'BACKEND_ORIGIN not set' }), { status: 500 });
}
```
**Fix Required:** Document `BACKEND_ORIGIN` as required Railway env var for `web` service  
**Severity:** 🟡 MEDIUM — Frontend can't reach backend without it

---

### **RISK #8: Health Check Returns 503 if Redis Missing [LOW-MEDIUM]**
**Status:** ⚠️ Design  
**Impact:** `/health/ready` returns fail status if Redis is temporarily down; may cause incorrect pod restarts  
**Root Cause:** `app/routes/health.py` treats Redis as required; no retry/fallback  
**Current State:**
```python
# health.py (line ~40)
redis_ok = bool(redis_conn.ping())  # Hard failure if Redis unavailable
```
**Fix Required:** Consider making Redis optional or add retry logic  
**Severity:** 🟡 LOW-MEDIUM — Operational resilience issue

---

### **RISK #9: Migrations Can Crash Deploy if DB Already Exists [MEDIUM]**
**Status:** ⚠️ Partially fixed  
**Impact:** Re-running migrations on existing DB could hang/crash if not idempotent  
**Root Cause:** Migration `001_add_missing_loop_columns.py` uses `inspect()` to check columns (✅ GOOD), but other future migrations may not; also, migrations run on startup which could race  
**Current State:** ✅ Latest migration is idempotent, but no protection against future regressions  
**Fix Required:** Document migration strategy; consider one-time manual migration step on Railway instead of at boot  
**Severity:** 🟡 MEDIUM — Deploy safety issue

---

### **RISK #10: No VERSION Endpoint or Git SHA Logging [LOW]**
**Status:** ⚠️ Missing observability  
**Impact:** Cannot easily verify which version is deployed; troubleshooting slower  
**Root Cause:** No `/api/v1/version` endpoint; no GIT_SHA env var logged  
**Fix Required:** Add simple version endpoint + log deployment info at startup  
**Severity:** 🟢 LOW — Observability/debugging benefit

---

## DETAILED FINDINGS

### ✅ What's Working Well

1. **CORS Configuration**
   - `app/config.py` properly builds `allowed_origins` from `FRONTEND_ORIGIN` env var
   - Logs origins at startup for verification
   - CORSMiddleware positioned first in middleware stack

2. **Storage Backend Logic**
   - `app/services/storage_service.py` has clear `_should_use_s3()` logic
   - Auto-detects S3 based on `STORAGE_BACKEND` env var AND presence of AWS creds
   - Logs config at startup: "Using local file storage" or "AWS S3 storage configured"

3. **Database Migrations**
   - Migration `001_add_missing_loop_columns.py` uses `inspect()` to check existing columns (idempotent)
   - No stray migration files tracked
   - Alembic config correct

4. **Health Endpoints**
   - `/health/live` (instant liveness check)
   - `/health/ready` (DB + Redis + S3 checks)
   - `/db/health` (DB-only check)

5. **Backend Startup**
   - Procfile correctly use `${PORT}` and `0.0.0.0`
   - Lifespan logs startup info (environment, debug, storage_backend, port)
   - Migrations run at boot with error handling

6. **Frontend Proxy**
   - `src/app/api/[...path]/route.ts` properly forwards all HTTP methods
   - Supports multipart/form-data for file uploads
   - Reads `BACKEND_ORIGIN` from env

---

### ⚠️ Issues Found

#### A. Worker Service Gap
- **File:** `Procfile`
- **Issue:** No worker service defined
- **Impact:** Background render jobs won't run
- **Solution:** Add worker service to Procfile

#### B. Worker Settings Inconsistency
- **File:** `app/workers/render_worker.py` (line 59+)
- **Issue:** Reads AWS vars via `os.getenv()` instead of importing from `app.config`
- **Impact:** Hard to maintain if settings format changes; potential auth misalignment
- **Solution:** Import `settings` and use `settings.aws_region`, etc.

#### C. Outdated Environment Documentation
- **File:** `.env.example`
- **Issue:** References Render platform, not Railway; missing variables
- **Missing vars:** `REDIS_URL`, `STORAGE_BACKEND`, `FRONTEND_ORIGIN`
- **Solution:** Rewrite for Railway

#### D. Frontend Env Not Documented
- **File:** `.env.local.example` (frontend)
- **Issue:** Only has `BACKEND_ORIGIN`; no comments
- **Solution:** Add brief documentation of required vars

#### E. No Version/Git SHA Logging
- **File:** `app/main.py`
- **Issue:** No deployment version tracked
- **Solution:** Log `GIT_SHA` if available; add optional `/api/v1/version` endpoint

---

## FIXES APPLIED (IN ORDER)

### ✅ Fix 1: Update `.env.example` for Railway
**Commit:** "feat: update .env.example for Railway deployment"

### ✅ Fix 2: Import settings in Worker
**Commit:** "fix: worker uses settings instead of os.getenv for AWS vars"

### ✅ Fix 3: Add Worker Service to Procfile
**Commit:** "feat: add worker service to Procfile for Railway"

### ✅ Fix 4: Frontend .env Documentation
**Commit:** "docs: add frontend env example with comments"

### ✅ Fix 5: Create DEPLOY_RAILWAY.md
**Commit:** "docs: add comprehensive Railway deployment guide"

---

## REMAINING MANUAL STEPS ON RAILWAY

After code is pushed, configure Railway UI:

### Web Service (Frontend)
```
Service: looparchitect-frontend
Build: npm run build
Start: npm run start
Port: 3000
Env Vars:
  - BACKEND_ORIGIN = (URL of api service, e.g. https://api-production-xxx.up.railway.app)
```

### API Service (Backend)
```
Service: looparchitect-backend-api
Build: (default Python)
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Env Vars:
  - ENVIRONMENT = production
  - DEBUG = false
  - DATABASE_URL = (Railway Postgres URL)
  - REDIS_URL = (Railway Redis URL)
  - STORAGE_BACKEND = s3  (or local)
  - AWS_ACCESS_KEY_ID = (from IAM)
  - AWS_SECRET_ACCESS_KEY = (from IAM)
  - AWS_REGION = (e.g. us-east-1)
  - AWS_S3_BUCKET = (your bucket name)
  - FRONTEND_ORIGIN = (URL of web service, e.g. https://web-production-xxx.up.railway.app)
```

### Worker Service (Background Render Jobs)
```
Service: looparchitect-worker
Build: (default Python)
Start: python -m app.workers.main  (or: python app/workers/main.py)
Env Vars:
  (Same as API service — must have DATABASE_URL, REDIS_URL, S3 vars)
  - ENVIRONMENT = production
  - DEBUG = false
  - DATABASE_URL = (Railway Postgres URL)
  - REDIS_URL = (Railway Redis URL)
  - STORAGE_BACKEND = s3  (must match API)
  - AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_S3_BUCKET
  - FRONTEND_ORIGIN = (URL of web service)
```

---

## VERIFICATION CHECKLIST

- [ ] Push all code changes
- [ ] Create Railway project with 3 services: api, worker, web
- [ ] Configure env vars per above
- [ ] Deploy all services
- [ ] Test `/health/live` returns 200 instantly
- [ ] Test `/health/ready` returns 200 with all checks passing
- [ ] Test frontend loads (https://web-xxx.railway.app)
- [ ] Test upload file: `curl.exe -X POST "https://api-xxx.railway.app/api/v1/loops/upload" -F "file=@./test.wav"`
- [ ] Monitor logs for storage backend message: "✅ AWS S3 storage configured"
- [ ] Test render job (POST to `/api/v1/render`) — check worker logs for S3 download
- [ ] Verify no "Using local file storage" in production logs (unless intentional)

---

## SUMMARY

**Before Deploy:** Fix 5 issues (worker service, settings import, .env docs, frontend env, version endpoint)  
**Critical Path Blockers:** #1 (worker), #2 (settings import)  
**Recommended Timeline:**
1. Apply code fixes (commits 1-5)
2. Test locally (`pytest`, `npm run build`, backend/worker startup)
3. Push to GitHub
4. Create Railway services and env vars
5. Deploy and verify health checks
6. Test file upload and render job end-to-end

