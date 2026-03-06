# Quick Reference - Start Services with ProducerEngine

## ✅ LOCAL (Currently Working - March 6, 2026 8:20 AM)

### Start Backend (with ProducerEngine enabled)
```powershell
cd c:\Users\steve\looparchitect-backend-api
cmd /c "set FEATURE_PRODUCER_ENGINE=true && .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
```

### Start Frontend (in separate terminal)
```powershell
cd c:\Users\steve\looparchitect-frontend
npm run dev
```

### Verify Everything is Working
```powershell
# Check ports are listening
Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -in @(3000, 8000)} | Select-Object LocalPort

# Check feature flag is enabled
cd c:\Users\steve\looparchitect-backend-api
.\.venv\Scripts\python.exe -c "from app.config import settings; print('ProducerEngine:', settings.feature_producer_engine)"
```

Expected output:
```
LocalPort
---------
     3000  (Frontend)
     8000  (Backend)

ProducerEngine: True
```

---

## ⚠️ PRODUCTION (Needs Railway Configuration)

### Set Environment Variable in Railway
1. Go to https://railway.app
2. Select project `looparchitect-backend-api`
3. Click `web` service → **Variables** tab
4. Add: `FEATURE_PRODUCER_ENGINE=true`
5. Click **Deploy**

### Verify Production (after Railway redeploys)
```powershell
# Test health
Invoke-WebRequest https://web-production-3afc5.up.railway.app/api/v1/health

# Test arrangement generation
$body = @{ loop_id = 1; target_seconds = 30 } | ConvertTo-Json
Invoke-WebRequest -Uri "https://web-production-3afc5.up.railway.app/api/v1/arrangements/generate" -Method POST -ContentType "application/json" -Body $body -UseBasicParsing
```

Check Railway logs for:
- `ProducerEngine enabled: True`
- `ProducerEngine arrangement generated`

---

## 🚨 Common Issues

### Backend starts but exits immediately
❌ **Wrong:** `python main.py` (doesn't work)  
✅ **Right:** `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`

### ProducerEngine not working (shows False)
❌ **Wrong:** Started backend without setting environment variable  
✅ **Right:** Use `cmd /c "set FEATURE_PRODUCER_ENGINE=true && ..."`

### Production not using ProducerEngine
❌ **Wrong:** Railway doesn't have environment variable set  
✅ **Right:** Add `FEATURE_PRODUCER_ENGINE=true` in Railway dashboard Variables tab

---

## 📊 Test Results (Current Session)

```
Local Backend: ✅ WORKING
- Arrangement 150: has producer_arrangement_json (1872 bytes)
- Arrangement 151: has producer_arrangement_json (1872 bytes)
- Feature flag: True
- Status: done

Frontend: ✅ WORKING
- Listening on port 3000
- Can connect to backend

Production: ⚠️ NEEDS RAILWAY ENV VAR
- Backend healthy (200 OK)
- Arrangements generate successfully
- ProducerEngine status: Unknown (env var likely not set)
```

---

## 📝 Stop Services

```powershell
# Stop backend
$backend_pid = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($backend_pid) { Stop-Process -Id $backend_pid -Force }

# Stop frontend
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
```
