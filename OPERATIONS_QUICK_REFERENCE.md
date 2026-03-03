# LoopArchitect Operations Quick Reference

## 🚀 Quick Start

### Local Development
```bash
# Terminal 1: Backend API
cd looparchitect-backend-api
.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd looparchitect-frontend
npm run dev
```

**Services:**
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API Docs: http://localhost:8000/docs

### Run Tests
```bash
cd looparchitect-backend-api
pytest -q                    # Run all tests
pytest tests/test_smoke.py   # Run smoke tests only
pytest -v                    # Verbose output
```

---

## 🔍 Debugging & Troubleshooting

### Backend Issues

**Port 8000 already in use:**
```powershell
netstat -ano | Select-String ":8000"
Stop-Process -Id <PID> -Force
```

**Import module errors:**
```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Redis connection failed:**
```bash
# Check installation
python -c "import redis; print('OK')"

# Redis not needed for local tests (has fallback)
# But required for async render jobs in production
```

### Frontend Issues

**Port 3000 in use:**
```powershell
netstat -ano | Select-String ":3000"
Stop-Process -Id <PID> -Force
```

**Dependencies outdated:**
```bash
npm install
npm run dev
```

---

## 📊 Monitoring Production

### Health Checks
```bash
# Backend health
curl https://web-production-3afc5.up.railway.app/api/v1/health

# Database health
curl https://web-production-3afc5.up.railway.app/api/v1/db-health

# Frontend (should redirect)
curl -I https://web-production-3afc5.up.railway.app
```

### Production Logs
```bash
# Via Railway CLI
railroad logs --service api
railroad logs --service web
railroad logs --service worker

# Or check Railway Dashboard:
# railway.app → LoopArchitect → Deployments → View Logs
```

### Common Production Errors
| Error | Cause | Fix |
|-------|-------|-----|
| 502 Bad Gateway | Backend not responsive | Check Railway CPU/memory, restart service |
| 503 Service Unavailable | Cold start | Wait 2-5 minutes |
| CORS errors | Origin not allowed | Update FRONTEND_ORIGIN env var |
| Async render hangs | Redis unavailable | Check REDIS_URL, restart worker |

---

## 🔧 Common Tasks

### Deploy New Changes
```bash
# Backend
cd looparchitect-backend-api
git add .
git commit -m "feat: description"
git push  # Triggers Railway rebuild automatically

# Frontend
cd looparchitect-frontend
git add .
git commit -m "feat: description"
git push  # Triggers Railway rebuild automatically
```

### Rollback to Previous Version
```bash
# Show recent commits
git log --oneline -10

# Revert to specific commit
git revert <commit-hash>
git push  # Triggers rebuild

# Or reset hard (use with caution)
git reset --hard <commit-hash>
git push --force
```

### Update Environment Variables
1. Go to railway.app
2. Select LoopArchitect project
3. Select API service
4. Click Variables
5. Add/edit variables
6. Redeploy service

### Database Migrations
```bash
# Create migration
alembic revision --autogenerate -m "add new column"

# Apply migrations (automatic on deploy)
alembic upgrade head

# Rollback
alembic downgrade -1
```

---

## 📁 Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app initialization |
| `app/routes/` | API endpoint definitions |
| `app/services/` | Business logic |
| `app/models/` | SQLAlchemy + Pydantic schemas |
| `tests/` | Test suite |
| `Dockerfile` | Container image definition |
| `Procfile` | Railway service definitions |
| `.env.example` | Environment variable template |

---

## 📞 Support & Links

| Resource | Link |
|----------|------|
| GitHub Backend | https://github.com/stevenotts2012-rgb/looparchitect-backend-api |
| GitHub Frontend | https://github.com/stevenotts2012-rgb/looparchitect-frontend |
| Production App | https://web-production-3afc5.up.railway.app |
| Railway Dashboard | https://railway.app |
| API Docs (Local) | http://localhost:8000/docs |
| OpenAPI Schema | http://localhost:8000/openapi.json |

---

## 🎯 Performance Optimization

### Caching
- Loops list: Implement Redis caching for frequently accessed loops
- Static assets: Frontend uses Next.js built-in caching

### Database
- Add indexes to frequently queried columns: `loop_id`, `status`
- Monitor slow queries: Check Railway database logs

### Background Jobs
- Queue depth: Monitor via Redis CLI: `LLEN looparchitect:queue`
- Worker count: Scale worker service in Railway dashboard

---

## ✅ Health Check Script

```powershell
# Save as health-check.ps1
$backend = @{}
$frontend = @{}

try {
    $r = Invoke-WebRequest "http://localhost:8000/api/v1/health" -TimeoutSec 3
    $backend.Status = "✅"
    $backend.Code = $r.StatusCode
} catch {
    $backend.Status = "❌"
    $backend.Code = "Error"
}

try {
    $r = Invoke-WebRequest "http://localhost:3000" -TimeoutSec 3
    $frontend.Status = "✅"
    $frontend.Code = $r.StatusCode
} catch {
    $frontend.Status = "❌"
    $frontend.Code = "Error"
}

Write-Host "Backend: $($backend.Status) ($($backend.Code))"
Write-Host "Frontend: $($frontend.Status) ($($frontend.Code))"
```

---

## 📚 Documentation Index

- [Full Deployment Report](./DEPLOYMENT_FINAL_REPORT.md)
- [API Reference](./API_REFERENCE.md)
- [Implementation Guide](./IMPLEMENTATION_COMPLETE.md)
- [Backend Pipeline](./IMPLEMENTATION_COMPLETE_BACKEND_PIPELINE.md)

---

Last updated: 2026-03-03
