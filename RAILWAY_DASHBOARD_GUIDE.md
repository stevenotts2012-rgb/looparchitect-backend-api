# Railway Dashboard Diagnostic Guide

## How to Check Production Status

### Step 1: Access Railway Dashboard
**URL:** https://railway.app

Log in with your account (should already be connected to GitHub)

### Step 2: Select Your Project
- Click **LoopArchitect** project in the sidebar
- You should see 3 services: `web`, `api`, `worker`

### Step 3: Check API Service (Most Important)

Click **api** service and navigate to:

#### A. **Deployments** Tab (First Check)
Look for the most recent deployment:

**Status Options:**
- 🟢 **SUCCESS** → Deployment completed successfully
- 🟡 **BUILDING** → Still compiling/uploading
- 🔴 **FAILED** → Build or deploy error
- ⏳ **QUEUED** → Waiting in build queue

**If BUILDING:**
- Click the deployment to see build logs
- Look for progress messages
- Typical build time: 3-5 minutes
- **Action:** Wait and refresh in 1 minute

**If FAILED:**
- Click to view full build log
- Look for error messages (scroll to bottom)
- Common errors:
  - `ModuleNotFoundError` - Missing dependencies
  - `SyntaxError` - Code issue (shouldn't happen, tests pass locally)
  - `Database connection failed` - Environment variable issue
- **Action:** Note the error and we can debug it

**If SUCCESS:**
- Build completed successfully
- Proceed to Logs tab

#### B. **Logs** Tab (If Build Successful)
Look for application startup messages:

**Good Signs:**
```
✓ INFO: Uvicorn running on 0.0.0.0:8000
✓ INFO: Application startup complete
✓ Registered router from api
✓ Database connection established
```

**Bad Signs:**
```
✗ ERROR: Failed to import...
✗ ERROR: Database connection failed
✗ ERROR: Redis unavailable
```

**If errors in logs:**
- Screenshot the error message
- Come back and share the error

#### C. **Metrics** Tab (Health Check)
- **CPU Usage:** Should be low when idle
- **Memory:** Check if constantly maxed out
- **Network:** Should show some activity
- **Restart Count:** 0 is good, >5 indicates crashing

### Step 4: Check Web Service (Frontend)

Click **web** service:
- Same tabs as API service
- Look for similar deployment status
- Frontend builds separately (Next.js)
- Should see `Build succeeded` if compiled correctly

### Step 5: Check Worker Service (Background Jobs)

Click **worker** service:
- Same tabs as API
- Background job processor
- Can be stopped initially (not critical for basic testing)

---

## What to Report Back

Once you check the dashboard, answer these:

1. **API Deployment Status:** (SUCCESS / BUILDING / FAILED / QUEUED)
2. **Web Deployment Status:** (SUCCESS / BUILDING / FAILED / QUEUED)
3. **Any Error Messages:** (If FAILED, copy the error text)
4. **Elapsed Time Since Push:** (Should be ~5-10 minutes now)

---

## Quick Decision Tree

```
Is API deployment showing as SUCCESS? 
├─ YES → Go to Logs tab
│        ├─ Any ERROR messages?
│        │  ├─ YES → Copy and report the error
│        │  └─ NO  → Service should be running, check health endpoint
│        └─ Copy any WARNING messages
│
└─ NO → Is it BUILDING?
       ├─ YES → Wait 2-3 more minutes, refresh browser
       ├─ QUEUED → Check queue position (should start soon)
       └─ FAILED → Click deployment, find ERROR at bottom of build log, report it
```

---

## Next Steps Based on Dashboard Status

### ✅ If API shows SUCCESS
1. Check Logs for ERROR or WARN messages
2. Once confirmed starting, test health endpoint:
   ```
   https://web-production-3afc5.up.railway.app/api/v1/health
   ```
3. Come back and report status

### 🟡 If API shows BUILDING
1. This is normal (5-10 minutes typical)
2. Wait 2-3 more minutes
3. Refresh dashboard
4. Come back with status

### 🔴 If API shows FAILED
1. Click the failed deployment
2. Scroll to bottom of build log
3. Find the ERROR line
4. Come back and share the error message

---

## Expected Timeline

- **0-3 min:** Build stage (compiling dependencies)
- **3-5 min:** Upload and deployment
- **5-7 min:** Container startup
- **7-10 min:** Application initialization
- **10+ min:** Should be responsive

**Current elapsed time from push:** ~20-25 minutes  
**Status:** Taking longer than typical (may indicate build issue)

---

## Environment Variables to Verify (Optional)

If you see connection errors, check that these are set:

Click **api** service → **Variables** tab:
- `STORAGE_BACKEND` (should be "local" or "s3")
- `REDIS_URL` (can be blank if local)
- `DATABASE_URL` (PostgreSQL URL set by Railway)
- `ENVIRONMENT` (should be "production")

Most should be auto-set by Railway, but if you see database errors, this is a good place to check.

---

**Once you've checked the dashboard, come back and report:**
- API deployment status
- Any error messages
- Current timestamp
- What services are showing

I'll help diagnose the issue or confirm production is live!
