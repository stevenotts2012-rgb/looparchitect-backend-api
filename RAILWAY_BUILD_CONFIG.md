# Railway Deployment Configuration

## Overview
This repository is configured for clean, deterministic builds on Railway without relying on committed virtualenvs or local Python installations.

## Build Configuration

### nixpacks.toml
The `nixpacks.toml` file configures Railway's Nixpacks builder for Python:

```toml
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

**Key features:**
- ✅ Clean Python 3.11 build (not relying on committed `.venv/`)
- ✅ Fresh pip installation for compatibility
- ✅ Standard Uvicorn startup command with `$PORT`
- ✅ No hardcoded paths or virtualenv references

### Procfile
The `Procfile` is a fallback configuration if Nixpacks is not used:

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Requirements Management

- `.gitignore` - Excludes `.venv/`, `__pycache__/`, and other build artifacts
- `requirements.txt` - Pinned dependencies installed in clean environment
- `pyproject.toml` - Project metadata and build configuration

## Environment Variables

Railway automatically provides:
- `PORT` - Dynamic port for the web service (Railway injected)
- `RAILWAY_ENVIRONMENT_NAME` - Environment identifier

Your app should set:
- `DATABASE_URL` - PostgreSQL connection string (from Railway Postgres plugin)
- `DEBUG=false` - Production mode
- `ENVIRONMENT=production` - Runtime environment

**Important:** Do NOT set `PYTHONHOME` or hardcode virtualenv paths in Railway Variables.

## Build Process

When you push to the main branch:

1. **Railway detects** `nixpacks.toml` → Uses Nixpacks builder
2. **Nixpacks builds** clean Python 3.11 environment with system stdlib
3. **Installs dependencies** from `requirements.txt`
4. **Starts service** with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

## Local Development

For local development, create and activate a virtual environment:

```bash
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (macOS/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn app.main:app --reload --port 8000
```

The local `.venv/` is **NOT committed** to git (see `.gitignore`).

## Troubleshooting

### Error: `ModuleNotFoundError: No module named 'encodings'`
**Cause:** Railway is using a broken or stale Python environment.  
**Solution:** 
1. Check that `.venv/` is not committed (use `git rm --cached .venv`)
2. Ensure `.gitignore` includes `.venv/`
3. Delete any hardcoded `/app/.venv` references
4. Verify `nixpacks.toml` exists and is correct
5. Trigger a fresh Railway redeploy

### Error: `uvicorn: command not found`
**Cause:** Dependencies not installed or installed in wrong location.  
**Solution:**
1. Check `requirements.txt` has `uvicorn[standard]==0.29.0`
2. Verify `nixpacks.toml` has correct install commands
3. Check Railway logs for pip install errors

### Port binding errors
**Cause:** Start command uses hardcoded port instead of `$PORT`.  
**Solution:**
1. Update `Procfile` and `nixpacks.toml` to use `--port $PORT`
2. Don't hardcode `--port 8000` in production configs

## CI/CD Integration

If you add GitHub Actions CI:

```yaml
- name: Check Python version
  run: python -m venv test_env && test_env/bin/python --version

- name: Install dependencies
  run: |
    python -m venv test_env
    test_env/bin/pip install -r requirements.txt

- name: Run tests
  run: test_env/bin/pytest
```

Do NOT commit the `test_env/` directory.

## Files NOT Committed

The following are in `.gitignore` and should NOT be committed:
- `.venv/` - Local virtual environment
- `__pycache__/` - Python bytecode cache
- `.pytest_cache/` - Test cache
- `.mypy_cache/` - Type checking cache
- `*.db` - SQLite databases
- `uploads/` - User-uploaded files
- `renders/` - Generated audio files
- `.env` - Local environment variables
- `.env.*.local` - Environment overrides

## Railway Service Configuration

### Recommended Settings
1. **Build Command:** Leave blank (Nixpacks auto-detects)
2. **Start Command:** Leave blank (Nixpacks uses `nixpacks.toml`)
3. **Root Directory:** Blank or `.` (repo root)
4. **Python Version:** 3.11.9 (inherited from nixpacks.toml)

### Environment Variables
- `DEBUG=false`
- `ENVIRONMENT=production`
- `DATABASE_URL=postgresql://...` (from Railway Postgres plugin)

Do NOT set:
- `PYTHONHOME`
- `PYTHONPATH`
- `VIRTUAL_ENV`
- Any hardcoded `/app/.venv` references

## Verification Checklist

After deployment:

- [ ] Rails logs show: `Uvicorn running on http://0.0.0.0:<port>`
- [ ] No mention of `/app/.venv/bin/python` in logs
- [ ] No `ModuleNotFoundError: encodings` errors
- [ ] Health endpoint responds: `curl https://your-app.railway.app/health`
- [ ] API docs available: `https://your-app.railway.app/docs`

## Related Files
- `nixpacks.toml` - Railway build configuration (NEW)
- `Procfile` - Fallback start command
- `.gitignore` - Files to exclude from git (UPDATED)
- `requirements.txt` - Dependency pinning
- `pyproject.toml` - Project build config
