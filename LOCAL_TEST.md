# Local Development Testing Guide

## Quick Start

### Step 1: Activate Virtual Environment (Windows)

```powershell
# PowerShell
.\.venv\Scripts\Activate.ps1

# Expected output:
# (.venv) PS C:\Users\steve\looparchitect-backend-api>
```

If you get an execution policy error, run:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Step 2: Install Dependencies

```powershell
pip install -r requirements.txt

# Expected output:
# Successfully installed fastapi-0.110.0 uvicorn[standard]-0.29.0 ... librosa-0.10.0 ... (30+ packages)
# 
# Verify key packages:
pip list | findstr librosa
# librosa                    0.10.0
```

### Step 3: Run FastAPI Development Server

```powershell
python -m uvicorn app.main:app --reload

# Expected output:
# INFO:     Uvicorn running on http://127.0.0.1:8000
# INFO:     Application startup complete
# INFO:     Uvicorn running with 1 worker process
```

The `--reload` flag enables hot-reload when you edit files.

### Step 4: Verify API is Running

Open your browser or use curl:

```powershell
# Health check
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health"

# Expected output:
# status  message
# ------  -------
# ok      Service is healthy
```

### Step 5: View Interactive API Docs

Open in browser:
```
http://127.0.0.1:8000/docs
```

You should see:
- ✅ All endpoints listed
- ✅ "render" tag with render endpoints
- ✅ POST /api/v1/render-pipeline/{loop_id}
- ✅ POST /api/v1/renders/{filename}
- ✅ GET /api/v1/renders/{filename}

### Step 6: Verify Render Endpoints Exist

In Swagger UI (/docs), search for "render" and verify:

| Endpoint | Method | Tags | Status |
|----------|--------|------|--------|
| `/api/v1/render/{loop_id}` | POST | render | ✅ |
| `/api/v1/render-pipeline/{loop_id}` | POST | render | ✅ |
| `/api/v1/render-simulated/{loop_id}` | POST | render | ✅ |
| `/api/v1/renders/{filename}` | GET | render | ✅ |

---

## Testing Render Endpoints

### Test 1: Create a Loop (Required First)

```powershell
$loopData = @{
    name = "Test Loop"
    tempo = 140
    key = "C Major"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/v1/loops" `
  -Method Post `
  -Body $loopData `
  -ContentType "application/json"

# Expected output:
# {
#   "id": 1,
#   "name": "Test Loop",
#   "tempo": 140.0,
#   "key": "C Major",
#   "filename": null,
#   "file_url": null,
#   ...
# }
```

Record the `id` (usually 1 for first loop).

### Test 2: Test Render Endpoint (Simple)

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/v1/render/1" `
  -Method Post `
  -Body '{}' `
  -ContentType "application/json"

# Expected output:
# {
#   "render_url": "/api/v1/renders/render_1_abc12345.wav",
#   "loop_id": 1
# }
```

### Test 3: Test New Render Pipeline (Advanced)

```powershell
$pipelineRequest = @{
    length_seconds = 180
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/v1/render-pipeline/1" `
  -Method Post `
  -Body $pipelineRequest `
  -ContentType "application/json"

# Expected output:
# {
#   "status": "completed",
#   "render_id": "a7f3b2c1",
#   "loop_id": 1,
#   "download_url": "/renders/a7f3b2c1_instrumental.wav",
#   "analysis": {
#     "bpm": 140.0,
#     "key": "C Major",
#     "duration_seconds": 8.0,
#     "confidence": 0.85
#   },
#   "arrangement": {
#     "sections": [...],
#     "total_bars": 96,
#     "total_seconds": 192.0
#   }
# }
```

### Test 4: Verify Render File (Simulated)

```powershell
# The rendered file should be available to download
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/v1/renders/render_1_abc12345.wav" `
  -Method Get

# Expected output:
# (Binary WAV file content)
```

---

## cURL Examples (Windows PowerShell)

All these work in PowerShell - no special conversion needed.

### Health Check
```powershell
curl.exe -X GET "http://127.0.0.1:8000/api/v1/health"
```

### List All Loops
```powershell
curl.exe -X GET "http://127.0.0.1:8000/api/v1/loops"
```

### Create Loop
```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/loops" `
  -H "Content-Type: application/json" `
  -d '{"name":"Test","tempo":140}'
```

### Render Loop (Pipeline)
```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/render-pipeline/1" `
  -H "Content-Type: application/json" `
  -d '{"length_seconds":180}'
```

---

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'librosa'"

**Solution:** Install dependencies
```powershell
pip install -r requirements.txt
```

### Issue: Port 8000 already in use

**Solution:** Use different port
```powershell
python -m uvicorn app.main:app --reload --port 8001
# Then access at http://127.0.0.1:8001/docs
```

### Issue: "Cannot find Python executable"

**Solution:** Activate venv first
```powershell
.\.venv\Scripts\Activate.ps1
# Then try again
python -m uvicorn app.main:app --reload
```

### Issue: Render endpoints not appearing in /docs

**Solution:** Restart the server
```powershell
# Ctrl+C to stop
# Then restart:
python -m uvicorn app.main:app --reload
```

---

## Success Checklist

When testing locally, you should see:

✅ Virtual environment activated (`.venv` in prompt)  
✅ Dependencies installed (pip list shows 30+ packages)  
✅ Server running (http://127.0.0.1:8000 accessible)  
✅ Health endpoint responds (status: ok)  
✅ Swagger UI loads (/docs)  
✅ Render endpoints visible in /docs  
✅ New endpoint: `/api/v1/render-pipeline/{loop_id}` is listed  
✅ Loop creation returns 201 status  
✅ Render returns JSON with download_url  
✅ Analysis data present (BPM, key, confidence)  
✅ Arrangement structure complete (8+ sections)  

---

## Development Workflow

### Making Changes

1. Edit code in your IDE
2. Server auto-reloads (thanks to `--reload`)
3. Test changes in browser or curl
4. Check `/docs` for updated endpoints

Example:
```powershell
# 1. Edit app/services/render_service.py
# 2. Save file
# 3. Server auto-restarts (you'll see "Reloading" in terminal)
# 4. Test immediately - no manual restart needed
```

### Running Tests (Optional)

```powershell
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/services/test_render_service.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
```

---

## Advanced: Database & Migrations

### Check Database Health

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/db-health"

# Expected output:
# {
#   "database_url": "sqlite:///./test.db",
#   "connection": "ok",
#   "tables": ["loops", "test_items"],
#   "status": "healthy"
# }
```

### Run Migrations Manually

```powershell
# The app runs migrations automatically on startup
# But you can run manually:
alembic upgrade head
```

---

## Next Steps

1. ✅ Activate venv: `.\.venv\Scripts\Activate.ps1`
2. ✅ Start server: `python -m uvicorn app.main:app --reload`
3. ✅ Open /docs: http://127.0.0.1:8000/docs
4. ✅ Test render endpoint
5. 🔜 Upload real audio file (next phase)
6. 🔜 Test with actual WAV file in /uploads

---

## Additional Resources

- FastAPI docs: https://fastapi.tiangolo.com
- Librosa docs: https://librosa.org
- SQLAlchemy docs: https://docs.sqlalchemy.org
- Render deployment: See [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md)
- Render pipeline architecture: See [RENDER_PIPELINE.md](RENDER_PIPELINE.md)
