# Feature Enablement Guide - ProducerEngine & Phase 4 Features

**Date**: March 6, 2026  
**Status**: ✅ Local Working | ⚠️ Production Needs Configuration

---

## Current Status Summary

### ✅ Local Development (WORKING)
- Backend: Running on localhost:8000
- Frontend: Running on localhost:3000
- ProducerEngine: **ENABLED and WORKING**
- Recent test results:
  - Arrangement ID 150: ✅ has producer_arrangement_json (1872 bytes)
  - Arrangement ID 151: ✅ has producer_arrangement_json (1872 bytes)
  - Both arrangements: status=done
  
### ⚠️ Production (NEEDS CONFIGURATION)
- Backend: Running on Railway (web-production-3afc5.up.railway.app)
- Health check: ✅ 200 OK
- ProducerEngine: **LIKELY DISABLED** (environment variable not set)
- Arrangement generation works but may be using fallback system

---

## Problem: Features Not Working Properly

The ProducerEngine and other Phase 4 features require the `FEATURE_PRODUCER_ENGINE=true` environment variable to be set. 

**Root Cause:**
- Local: You must set the environment variable each time you start the backend ✅ (Currently working)
- Production: Railway environment variables must be configured through Railway dashboard ⚠️ (Needs setup)

---

## Solution: Enable ProducerEngine in Production

### Step 1: Set Railway Environment Variable

1. Go to Railway dashboard: https://railway.app
2. Select your project: `looparchitect-backend-api`
3. Click on the `web` service
4. Go to **Variables** tab
5. Click **+ New Variable**
6. Add:
   ```
   FEATURE_PRODUCER_ENGINE=true
   ```
7. Click **Add** and **Deploy**

### Step 2: Verify Deployment

Wait 30-60 seconds for Railway to redeploy, then test:

```powershell
# Test production arrangement generation
$body = @{ 
    loop_id = 1; 
    target_seconds = 30; 
    style_text_input = 'dark trap'; 
    use_ai_parsing = $true 
} | ConvertTo-Json

$resp = Invoke-WebRequest `
    -Uri "https://web-production-3afc5.up.railway.app/api/v1/arrangements/generate" `
    -Method POST `
    -ContentType "application/json" `
    -Body $body `
    -UseBasicParsing `
    -TimeoutSec 30

$result = $resp.Content | ConvertFrom-Json
Write-Host "✓ Arrangement ID: $($result.arrangement_id)"
Write-Host "✓ Status: $($result.status)"
```

### Step 3: Check Railway Logs

1. Go to Railway dashboard
2. Click **View Logs**
3. Look for these indicators of ProducerEngine activation:
   ```
   ProducerEngine enabled: True
   ProducerEngine arrangement generated
   producer_arrangement_json persisted
   ```

If you see these logs, **ProducerEngine is working** in production! ✅

---

## How to Start Local Backend with ProducerEngine

### Method 1: Using cmd.exe (RECOMMENDED)
```powershell
cd c:\Users\steve\looparchitect-backend-api
cmd /c "set FEATURE_PRODUCER_ENGINE=true && .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
```

### Method 2: Using PowerShell Environment Variable
```powershell
cd c:\Users\steve\looparchitect-backend-api
$env:FEATURE_PRODUCER_ENGINE = 'true'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Important Notes:**
- Always use uvicorn to start (NOT `python main.py` - that doesn't work!)
- The environment variable must be set BEFORE starting the server
- Verify it's working by checking logs for "ProducerEngine enabled: True"

---

## Feature Flag Verification

### Check if ProducerEngine is Enabled

**Local:**
```powershell
cd c:\Users\steve\looparchitect-backend-api
.\.venv\Scripts\python.exe -c "import os; from app.config import settings; print('FEATURE_PRODUCER_ENGINE:', settings.feature_producer_engine); print('ENV VAR:', os.getenv('FEATURE_PRODUCER_ENGINE'))"
```

**Expected output when working:**
```
FEATURE_PRODUCER_ENGINE: True
ENV VAR: true
```

**Expected output when NOT working:**
```
FEATURE_PRODUCER_ENGINE: False
ENV VAR: None
```

### Check Database for Producer Data

```powershell
cd c:\Users\steve\looparchitect-backend-api
.\.venv\Scripts\python.exe -c "import sqlite3; db=sqlite3.connect('test.db'); c=db.cursor(); c.execute('SELECT id, status, producer_arrangement_json FROM arrangements ORDER BY id DESC LIMIT 5'); rows=c.fetchall(); [print(f'ID {r[0]}: status={r[1]}, has_producer={r[2] is not None}, json_size={len(r[2]) if r[2] else 0} bytes') for r in rows]; db.close()"
```

**Expected output when working:**
```
ID 151: status=done, has_producer=True, json_size=1872 bytes
ID 150: status=done, has_producer=True, json_size=1872 bytes
```

---

## Troubleshooting

### Issue: "Features are not working properly"

**Symptoms:**
- Arrangements generate but don't use ProducerEngine
- No producer_arrangement_json in database
- Logs don't show "ProducerEngine enabled"

**Solutions:**

1. **Check if backend is running with feature flag:**
   ```powershell
   Invoke-WebRequest http://localhost:8000/api/v1/health -UseBasicParsing
   # If this works, backend is running
   
   # Then check the feature flag (see "Feature Flag Verification" above)
   ```

2. **Restart backend with correct command:**
   ```powershell
   # Stop current backend
   $backend_pid = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
   if ($backend_pid) { Stop-Process -Id $backend_pid -Force; Write-Host "Backend stopped" }
   
   # Wait 2 seconds
   Start-Sleep -Seconds 2
   
   # Start with feature flag (use cmd.exe method)
   cmd /c "set FEATURE_PRODUCER_ENGINE=true && .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
   ```

3. **Check backend logs in terminal:**
   Look for:
   - `✅ Request logging middleware enabled` (startup successful)
   - `ProducerEngine enabled: True` (when generating arrangement)
   - `ProducerEngine arrangement generated` (successful generation)

4. **Test arrangement generation:**
   ```powershell
   $body = @{ loop_id = 1; target_seconds = 30 } | ConvertTo-Json
   Invoke-WebRequest -Uri "http://localhost:8000/api/v1/arrangements/generate" -Method POST -ContentType "application/json" -Body $body -UseBasicParsing
   ```
   
   Check terminal logs - you should see ProducerEngine messages

### Issue: Frontend Not Connecting to Backend

**Symptoms:**
- Frontend shows errors
- API calls failing
- CORS errors

**Solutions:**

1. **Check both are running:**
   ```powershell
   Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalPort -in @(3000, 8000)} | Select-Object LocalPort, State
   ```
   
   Expected: Both 3000 and 8000 should show "Listen"

2. **Check backend CORS configuration:**
   - Backend should allow `http://localhost:3000` origin
   - This is configured in `app/middleware/cors.py`

3. **Restart frontend:**
   ```powershell
   cd c:\Users\steve\looparchitect-frontend
   npm run dev
   ```

### Issue: Production Not Using ProducerEngine

**Symptoms:**
- Local works fine
- Production arrangements don't have producer data
- Railway logs don't show ProducerEngine messages

**Solution:**
1. Add `FEATURE_PRODUCER_ENGINE=true` to Railway environment variables (see "Step 1" above)
2. Railway will auto-redeploy
3. Test production endpoint (see "Step 2" above)
4. Check Railway logs (see "Step 3" above)

---

## Quick Start Checklist

### Local Development
- [ ] Backend running on port 8000 with FEATURE_PRODUCER_ENGINE=true
- [ ] Frontend running on port 3000
- [ ] Can access http://localhost:3000
- [ ] Can generate arrangements that create producer_arrangement_json
- [ ] Both loop and arrangement downloads working

### Production Deployment
- [ ] FEATURE_PRODUCER_ENGINE=true set in Railway variables
- [ ] Railway deployment successful (check logs)
- [ ] Production health check returns 200 OK
- [ ] Can generate arrangements via production API
- [ ] Railway logs show "ProducerEngine enabled: True"

---

## Additional Resources

- **VALIDATION_SESSION_REPORT.md** - Complete validation results from Phase 4
- **VALIDATION_GUIDE.md** - Comprehensive testing procedures
- **PREVIEW_DOWNLOAD_FIX.md** - Recent fix for loop download functionality
- **RAILWAY_AUDIT_REPORT.md** - Railway deployment configuration guide

---

## Current Working Configuration (Local)

**Confirmed Working as of March 6, 2026 8:20 AM:**

```
Backend: http://localhost:8000
Frontend: http://localhost:3000
Feature Flag: FEATURE_PRODUCER_ENGINE=true
Database: test.db (SQLite)

Recent Test Results:
- Arrangement 150: ✅ producer_arrangement_json = 1872 bytes
- Arrangement 151: ✅ producer_arrangement_json = 1872 bytes
- Both status: done
- Backend logs confirm: "ProducerEngine enabled: True"
```

**Start Command (currently working):**
```powershell
cmd /c "set FEATURE_PRODUCER_ENGINE=true && .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
```

---

## Need Help?

If features still aren't working after following this guide:

1. Share the output of:
   ```powershell
   # Check feature flag
   .\.venv\Scripts\python.exe -c "from app.config import settings; print(settings.feature_producer_engine)"
   
   # Check backend logs (last 50 lines from terminal)
   
   # Check database
   .\.venv\Scripts\python.exe -c "import sqlite3; db=sqlite3.connect('test.db'); c=db.cursor(); c.execute('SELECT id,status,producer_arrangement_json IS NOT NULL FROM arrangements ORDER BY id DESC LIMIT 3'); print(c.fetchall())"
   ```

2. Check Railway dashboard:
   - Are environment variables set?
   - Are there errors in logs?
   - Is the service running?

3. Test the specific feature that's not working and share:
   - What you're trying to do
   - Expected behavior
   - Actual behavior
   - Any error messages
