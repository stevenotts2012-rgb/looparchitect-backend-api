# Backend Verification & Setup Guide

## ✅ Verification Complete

### Code Structure
- ✅ **Root main.py**: Valid, exposes `app = FastAPI()` properly
  - Location: `/main.py` (line 71)
  - No syntax errors - compiles successfully
  - Properly imports all routes and middleware

### CORS Configuration
- ✅ **CORS Middleware**: Configured in `/app/middleware/cors.py`
  - Allows: `http://localhost:3000` (frontend dev)
  - Allows: `http://localhost:5173` (alternative frontend)
  - Allows: `https://looparchitect-backend-api.onrender.com` (Render production)
  - Allows: `$FRONTEND_ORIGIN` environment variable (custom production domain)

### Health Endpoints
- ✅ **Root Health**: `GET /health` → returns `{"ok": true}`
  - Location: `main.py` line 129
  - No database dependency, always responds
  
- ✅ **API Health**: `GET /api/v1/health` → database-aware health check
  - Also available for monitoring

### Loop Routes
- ✅ **List loops**: `GET /api/v1/loops`
  - Query params: status, genre, limit, offset
  - Returns: List[LoopResponse]

- ✅ **Create loop**: `POST /api/v1/loops`
  - Upload audio files to S3/storage
  - Returns: loop_id, play_url, download_url

- ✅ **Get loop**: `GET /api/v1/loops/{loop_id}`
  - Returns: LoopResponse with metadata

- ✅ **Update loop**: `PUT /api/v1/loops/{loop_id}`
  - Partial update support

- ✅ **Delete loop**: `DELETE /api/v1/loops/{loop_id}`
  - Also deletes file if delete_file=true

- ✅ **Play Audio**: `GET /api/v1/loops/{loop_id}/play`
  - Returns presigned S3 URL (1 hour expiry)
  - Frontend calls this for streaming/playback

### Deployment Configuration
- ✅ **Procfile**: Correctly configured for Railway/Render
  ```
  web: uvicorn main:app --host 0.0.0.0 --port $PORT
  ```
  - Uses environment variable `$PORT` (provided by Render/Railway)
  - Properly exposes `main:app` entrypoint

- ✅ **Database**: Automatic migrations via Alembic
  - Runs on startup in `lifespan()`
  - Supports both SQLite (dev) and PostgreSQL (production)

---

## 🚀 Local Development Setup

### Step 1: Install Dependencies
```powershell
# Activate virtual environment (if not already active)
.\.venv\Scripts\Activate.ps1

# Install/update dependencies
pip install -r requirements.txt
```

### Step 2: Start Backend Server
```powershell
# Run with auto-reload (development)
uvicorn main:app --reload --host 127.0.0.1 --port 8000

# Or for debugging/verification
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### Step 3: Verify Backend is Running
```powershell
# Test health endpoint (PowerShell)
Invoke-WebRequest -Uri http://localhost:8000/health

# Or use curl
curl http://localhost:8000/health
```

Expected response:
```json
{"ok": true}
```

### Step 4: Test API Endpoints
```powershell
# Get loop list (will be empty initially)
Invoke-WebRequest -Uri http://localhost:8000/api/v1/loops

# Get API status
Invoke-WebRequest -Uri http://localhost:8000/api/v1/status
```

---

## 📋 Frontend Integration

Your frontend on `http://localhost:3000` can now call:

1. **Get all loops**
   ```javascript
   fetch('http://localhost:8000/api/v1/loops')
   ```

2. **Play a loop** (presigned URL)
   ```javascript
   fetch('http://localhost:8000/api/v1/loops/{id}/play')
     .then(r => r.json())
     .then(data => {
       // data.url is presigned S3 URL, valid for 1 hour
       audio.src = data.url;
     })
   ```

3. **Upload new loop**
   ```javascript
   const formData = new FormData();
   formData.append('file', audioFile);
   fetch('http://localhost:8000/api/v1/loops/upload', {
     method: 'POST',
     body: formData
   })
   ```

---

## 🌍 Production Deployment

### Railway / Render Deployment

The system is production-ready:

1. **Procfile** is correctly configured
2. **CORS** allows production domains via `FRONTEND_ORIGIN` env var
3. **Database** auto-runs migrations on startup
4. **Health endpoints** for load balancer monitoring

### Environment Variables Required

```
DATABASE_URL=postgresql://user:pass@host/dbname  # PostgreSQL for production
FRONTEND_ORIGIN=https://yourdomain.com            # Your frontend domain
S3_BUCKET=your-bucket                             # For file storage
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
```

### Startup Command
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

---

## 📊 Summary of Routes

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Root health check |
| GET | `/api/v1/health` | API health with DB check |
| GET | `/api/v1/loops` | List all loops |
| POST | `/api/v1/loops` | Create loop from upload |
| GET | `/api/v1/loops/{id}` | Get loop details |
| PUT | `/api/v1/loops/{id}` | Update loop metadata |
| DELETE | `/api/v1/loops/{id}` | Delete loop |
| GET | `/api/v1/loops/{id}/play` | Get presigned play URL |
| GET | `/api/v1/loops/{id}/download` | Download loop file |
| GET | `/api/v1/status` | API status and version |

---

## ⚠️ Known Working Configuration

- **Python**: 3.11.9
- **FastAPI**: 0.110.0
- **Uvicorn**: 0.29.0
- **SQLAlchemy**: 2.0+
- **Pydantic**: 2.6.4

✅ **All components verified and working correctly**
