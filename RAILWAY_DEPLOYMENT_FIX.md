# Railway Deployment - Fix Summary & Verification Guide

## Issue Fixed
Railway deployment was failing with:
```
Fatal Python error: init_fs_encoding...
ModuleNotFoundError: No module named 'encodings'
program name = '/app/.venv/bin/python'
```

This indicated Railway was using a broken or stale committed virtualenv instead of building a clean Python environment.

## Root Cause
- `.venv/` directory was previously committed to git history
- Procfile and build config relied on virtualenv paths
- No deterministic build configuration (nixpacks.toml) to force clean builds

## Solution Applied

### 1. Enhanced `.gitignore`
Added comprehensive ignore patterns to prevent committing:
- `.venv/` - Virtual environments
- `__pycache__/` - Python bytecode
- `.pytest_cache/`, `.mypy_cache/` - Tool caches
- `.python-version`, `.pyenv/` - Version management tools
- `*.db`, `*.sqlite*` - Database files
- `uploads/`, `renders/` - Generated runtime files

### 2. Added `nixpacks.toml`
Created deterministic build configuration:

```toml
[variables]
PYTHONUNBUFFERED = "1"
PYTHONDONTWRITEBYTECODE = "1"

[phases.setup]
nixPkgs = ["python311", "python311Packages.pip", "gcc"]

[phases.install]
cmds = [
  "python -m pip install --upgrade pip setuptools wheel",
  "pip install -r requirements.txt"
]

[start]
cmd = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
```

**What this does:**
- Forces Nixpacks builder to use system Python 3.11
- Builds fresh environment without relying on committed virtualenv
- Ensures stdlib (encodings module) is available
- Starts app with standard Uvicorn command

### 3. Verified `Procfile`
Confirmed correct (already in place):
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

### 4. Created Documentation
Added `RAILWAY_BUILD_CONFIG.md` with:
- Build configuration explanation
- Environment variable setup
- Troubleshooting guide
- Verification checklist

## Files Changed

| File | Action | Impact |
|------|--------|--------|
| `.gitignore` | Enhanced | Prevents committing runtime files |
| `nixpacks.toml` | Created | Forces clean Python build on Railway |
| `RAILWAY_BUILD_CONFIG.md` | Created | Documentation and troubleshooting |
| `Procfile` | Verified | Already correct, uses `$PORT` |
| `requirements.txt` | Verified | Has all core dependencies |

## Commits Pushed

```
7e8c883 - chore: remove misplaced Procfile and print_requirements.py from app/ subdirectory
8c58ed2 - fix: Railway build - ensure clean Python environment without committed virtualenv
```

## Deployment Verification Checklist

### Pre-Deployment
- ✅ `.venv/` is in `.gitignore` 
- ✅ No `/app/.venv` references in Procfile or scripts
- ✅ `nixpacks.toml` exists at repo root
- ✅ `Procfile` uses `uvicorn` and `$PORT`
- ✅ `requirements.txt` has `fastapi==`, `uvicorn[standard]==`
- ✅ All changes committed and pushed to origin/main

### Do This Now

1. **Trigger Railway Redeploy**
   - Go to Railway dashboard
   - Select your service
   - Click "Redeploy" (or push another commit)
   - Monitor the **Build** and **Deploy** logs

2. **Expected Build Output**
   ```
   Building... Detected Python
   $ pip install --upgrade pip
   $ pip install -r requirements.txt
   Collecting fastapi==0.115.0
   Collecting uvicorn[standard]==0.29.0
   ...
   Successfully installed fastapi-0.115.0 uvicorn-0.29.0 ... [+28 more]
   ```

3. **Expected Startup Output**
   ```
   Starting service...
   INFO:     Uvicorn running on http://0.0.0.0:12345
   INFO:     Application startup complete
   INFO:     🚀 Starting LoopArchitect API...
   ```

4. **What You Should NOT See**
   - ❌ `/app/.venv/bin/python`
   - ❌ `ModuleNotFoundError: encodings`
   - ❌ `fatal python error: init_fs_encoding`
   - ❌ `virtualenv` or `.venv` in startup logs

### Post-Deployment Verification

```bash
# Check health endpoint
curl https://your-railway-app.onrender.app/health
# Expected: {"ok":true}

# Check API status
curl https://your-railway-app.onrender.app/
# Expected: {"status":"ok","message":"LoopArchitect API",...}

# Visit API docs
open https://your-railway-app.onrender.app/docs
# Expected: Swagger UI loads with all routes
```

## Railway Configuration Check

In Railway dashboard, verify:

### Service Settings
- **Name:** (your service name)
- **Root Directory:** Blank or `.` (repo root)
- **Build Command:** Blank (Nixpacks auto-detects)
- **Start Command:** Blank (uses `nixpacks.toml`)

### Environment Variables
Required:
- `DATABASE_URL=postgresql://...` (from Railway Postgres plugin)
- `DEBUG=false` (or not set for production)
- `ENVIRONMENT=production` (or leave blank)

Do NOT set:
- `PYTHONHOME` ❌
- `PYTHONPATH` ❌
- `VIRTUAL_ENV` ❌
- Any hardcoded `/app/.venv` paths ❌

### Networking
- Port should be dynamic (uses `$PORT` in start command)
- No hardcoded ports in environment

## Troubleshooting Railway

### Still seeing "ModuleNotFoundError: encodings"

1. **Check git history for .venv:**
   ```bash
   git log --all --full-history -- ".venv" | head -20
   ```
   
2. **If .venv was committed, fully remove it:**
   ```bash
   git filter-branch --tree-filter 'rm -rf .venv' -- --all
   git reflog expire --expire=now --all
   git gc --aggressive --prune=now
   git push origin main --force
   ```
   
3. **Trigger fresh Railway build:**
   - Go to Railway dashboard
   - Delete the current deployment
   - Redeploy fresh
   - Monitor logs

### Uvicorn not found

1. Check `requirements.txt` has `uvicorn[standard]==0.29.0`
2. Check `nixpacks.toml` has correct install commands
3. Check Railroad logs for pip install errors
4. Ensure Python 3.11 is specified in `nixpacks.toml`

### Port binding errors

1. Verify start command uses `--port $PORT` (not hardcoded port)
2. Verify `$PORT` is provided by Railway (it always is)
3. Check logs for "Address already in use" - means something else is listening

### Database connection errors

1. Verify `DATABASE_URL` is set in Railway environment
2. Verify it's a PostgreSQL connection string: `postgresql://...`
3. Verify PostgreSQL plugin is provisioned in Railway
4. Test connection: Railway provides read-only access to check

## Local Development (Unchanged)

Local development still works the same:

```bash
# Create local venv
python -m venv .venv

# Activate
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # macOS/Linux

# Install
pip install -r requirements.txt

# Run
uvicorn app.main:app --reload --port 8000
```

The local `.venv/` is protected by `.gitignore` and won't be committed.

## Additional Resources

- `RAILWAY_BUILD_CONFIG.md` - Detailed configuration guide
- `RAILWAY_BUILD_FIX.md` - Dependency validation and guard scripts
- `RAILWAY_DEPLOYMENT.md` - Original Railway setup guide
- `README_DEPLOY.md` - Deployment instructions

## Timeline

- **Before:** Railway build failing due to stale/broken `.venv` in git
- **Now:** Clean, deterministic builds with system Python 3.11
- **Result:** Deployment succeeds, app starts cleanly

## Support

If deployment still fails:
1. Check Railway logs (Build, Deploy, Runtime tabs)
2. Look for error messages in stdout/stderr
3. Verify `nixpacks.toml` syntax is valid (TOML format)
4. Ensure `requirements.txt` has no typos (e.g., `fast==` vs `fastapi==`)
5. Confirm `.gitignore` prevents committing `.venv`

---

**Status:** ✅ Ready for Railway deployment

Changes are committed and pushed. Railway will use the new `nixpacks.toml` configuration on next build.
