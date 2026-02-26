# Quick Start - Backend Setup

## TL;DR - Get Running in 3 Commands

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start server (with auto-reload for development)
uvicorn main:app --reload --port 8000

# 3. Test it works
Invoke-WebRequest http://localhost:8000/health
```

**Expected output for step 3:**
```json
{"ok": true}
```

---

## For Frontend Developers

Your frontend can now call these endpoints:

### Get current loops
```
GET http://localhost:8000/api/v1/loops
```

### Play a loop
```
GET http://localhost:8000/api/v1/loops/{loop_id}/play
# Returns JSON: { "url": "https://s3.../presigned-url" }
# Use that URL in <audio> tag or fetch
```

### Check if backend is alive
```
GET http://localhost:8000/health
# Returns: { "ok": true }
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'fastapi'`
- Run: `pip install -r requirements.txt`
- Make sure virtualenv is activated: `.\.venv\Scripts\Activate.ps1`

### Port 8000 already in use
```powershell
# Use different port
uvicorn main:app --reload --port 8001
```

### CORS errors in frontend console
The backend CORS is configured for:
- `http://localhost:3000` ✓
- `http://localhost:5173` ✓

If you use a different port, either:
1. Change frontend to use port 3000 or 5173, OR
2. Add your origin to `app/config.py` line in `allowed_origins`

### Database connection errors
First run and automatic migration should handle setup. If issues persist:
```powershell
python migrate.py
python verify_db.py
```

---

## Full Command Reference

### Development (with auto-reload)
```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### Production (Railway/Render)
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```
*(Procfile already has this)*

### With Python module path
```powershell
python -m uvicorn main:app --reload --port 8000
```

### Check available routes
```powershell
python -c "from main import app; print([r.path for r in app.routes if '/api' in str(r.path)])"
```

### Production startup (requires ENV vars)
```powershell
$env:DATABASE_URL = "postgresql://..."
$env:FRONTEND_ORIGIN = "https://yourdomain.com"
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## Your Project is Ready ✅

✅ All routes are configured  
✅ CORS is enabled for localhost:3000  
✅ Health check `/health` is working  
✅ Production Procfile is correct  
✅ Database migrations auto-run  
✅ Code has no syntax errors  

**Just run the 3 commands above and you're good to go!**
