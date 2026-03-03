# Terminal Commands - Copy & Paste Ready

## One-Command Full Local Stack (Backend + Frontend)

```powershell
# From backend folder
cd c:\Users\steve\looparchitect-backend-api

# Launches two terminals:
# - Backend on http://127.0.0.1:8000
# - Frontend on http://localhost:3001
.\start-local-stack.ps1
```

Optional dry-run (prints commands only):

```powershell
.\start-local-stack.ps1 -DryRun
```

---

## Start Backend Locally

### Step 1: Set Up Environment (First Time Only)
```powershell
# Navigate to project
cd c:\Users\steve\looparchitect-backend-api

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install/update dependencies
pip install -r requirements.txt
```

### Step 2: Start Server
```powershell
# With hot-reload (development)
uvicorn main:app --reload --port 8000

# Or without hot-reload
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

### Step 3: Test Connection
Open new terminal/PowerShell and run:
```powershell
# Test health endpoint
curl http://localhost:8000/health

# This should return:
# {"ok":true}
```

---

## Frontend Connection

### If Frontend is on localhost:3000
```
✅ No changes needed! CORS already configured for localhost:3000
✅ Frontend can call http://localhost:8000/api/v1/...
```

### Example Frontend Fetch Calls
```javascript
// Get all loops
fetch('http://localhost:8000/api/v1/loops')
  .then(r => r.json())
  .then(console.log)

// Get single loop  
fetch('http://localhost:8000/api/v1/loops/1')
  .then(r => r.json())
  .then(console.log)

// Play loop (returns presigned URL)
fetch('http://localhost:8000/api/v1/loops/1/play')
  .then(r => r.json())  
  .then(data => {
    // data.url is valid for 1 hour
    const audio = new Audio(data.url);
    audio.play();
  })

// Upload new loop
const formData = new FormData();
formData.append('file', audioFileInput.files[0]);
fetch('http://localhost:8000/api/v1/loops/upload', {
  method: 'POST',
  body: formData
})
  .then(r => r.json())
  .then(loop => console.log('Created:', loop))
```

---

## Common Issues & Fixes

### Issue: "Port 8000 already in use"
```powershell
# Use a different port
uvicorn main:app --reload --port 8001
```

### Issue: "ModuleNotFoundError"
```powershell
# Activate venv and reinstall
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Issue: CORS error from frontend
Check that:
1. Frontend is on `localhost:3000` ← This is preconfigured
2. Frontend calls `http://localhost:8000/api/...` 
3. Backend console shows no CORS warnings

If frontend is on different port, edit `app/config.py`:
```python
@property
def allowed_origins(self) -> list[str]:
    origins = [
        "http://localhost:3000",      # your frontend port here
        "http://localhost:5173",      
        ...
    ]
```

### Issue: "connection refused" from frontend
```powershell
# Make sure backend is running!
uvicorn main:app --reload --port 8000

# Check it's listening
curl http://localhost:8000/health
```

---

## Stop Backend Server

```powershell
# Press Ctrl+C in the terminal where Uvicorn is running
```

---

## Check What's Running

```powershell
# See if anything is listening on port 8000
netstat -ano | findstr :8000

# Kill process if needed (replace PID with actual number)
taskkill /PID <PID> /F
```

---

## Full Integration Test

Run this in backend terminal:
```powershell
# Start backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000
```

Then in frontend terminal (separate window):
```bash
# Your frontend start command (e.g., React/Vue/Next.js)
npm start  # or `npm run dev` or your command
```

Then in backend terminal, you should see logs:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

And in frontend browser console, no CORS errors! ✅

---

## Production Deployment (Railway/Render)

### No Code Changes Needed!
Just push to GitHub and Railway/Render will:
1. Detect Procfile
2. Run: `pip install -r requirements.txt`
3. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Your API is live!

### Required Environment Variables
Set in Railway/Render dashboard:
```
DATABASE_URL=postgresql://user:pass@host/db
FRONTEND_ORIGIN=https://yourdomain.com
```

---

## Database Setup

If you get database errors:
```powershell
# Run migrations manually
python migrate.py

# Or verify database
python verify_db.py
```

---

## Useful URLs (When Running Locally)

```
API Root:           http://localhost:8000/api/v1/
Health:             http://localhost:8000/health
API Status:         http://localhost:8000/api/v1/status
Swagger Docs:       http://localhost:8000/docs
ReDoc Docs:         http://localhost:8000/redoc
```

Open `http://localhost:8000/docs` in browser to interactively test all endpoints!

---

## That's It! 🎉

```powershell
# Just run these 2 commands everytime you develop:

.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000
```

Your API is ready. Your frontend can call it. Deploy whenever ready! 🚀
