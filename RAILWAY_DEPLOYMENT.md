# Railway Deployment Guide

Complete guide for deploying LoopArchitect FastAPI backend to Railway.

## Prerequisites

- Railway account ([railway.app](https://railway.app/))
- GitHub repository with your backend code
- Railway CLI (optional, for CLI deployment)

---

## Quick Deploy (GitHub Integration) - RECOMMENDED

### Step 1: Connect Railway to GitHub

1. Go to [railway.app](https://railway.app/) and sign in
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Authorize Railway to access your GitHub
5. Select your `looparchitect-backend-api` repository
6. Click "Deploy Now"

### Step 2: Railway Auto-Detection

Railway will automatically:
- ✅ Detect `Procfile` and use it for startup command
- ✅ Detect `requirements.txt` and install Python dependencies
- ✅ Detect `runtime.txt` and use Python 3.11.9
- ✅ Set `PORT` environment variable automatically

### Step 3: Add PostgreSQL Database

1. In your Railway project dashboard, click "New"
2. Select "Database" → "PostgreSQL"
3. Railway automatically:
   - Creates the database
   - Injects `DATABASE_URL` into your service
   - Connects it to your web service

### Step 4: Configure Environment Variables

In Railway dashboard → Your Service → Variables tab, add:

```bash
# Required for Production
ENVIRONMENT=production
DEBUG=false

# Frontend CORS (replace with your frontend domain)
FRONTEND_ORIGIN=https://your-frontend.vercel.app

# AWS S3 for file storage (if using S3)
AWS_S3_BUCKET=your-bucket-name
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key

# Render compatibility (optional, for migration from Render)
RENDER_EXTERNAL_URL=${{RAILWAY_PUBLIC_DOMAIN}}
```

**Note**: `DATABASE_URL` and `PORT` are automatically provided by Railway.

### Step 5: Deploy!

Railway automatically deploys on every push to your main/master branch.

To trigger manual deploy:
1. Go to your service → Deployments
2. Click "Deploy" on latest commit

---

## Verify Deployment

### Check Deployment Logs

1. Go to Railway dashboard → Your Service → Deployments
2. Click on the latest deployment
3. Check logs for:
   ```
   🚀 Starting LoopArchitect API...
   ✅ Database migrations completed successfully
   ✅ Application startup complete
   ```

### Test Endpoints

Once deployed, Railway provides a public URL: `https://<your-service>.railway.app`

Test these endpoints:

```bash
# Root endpoint
curl https://your-service.railway.app/

# Health check
curl https://your-service.railway.app/health

# API status
curl https://your-service.railway.app/api/v1/status

# API docs (Swagger UI)
open https://your-service.railway.app/docs
```

Expected responses:
- `GET /` → `{"status": "ok", "message": "LoopArchitect API", ...}`
- `GET /health` → `{"ok": true}`
- `GET /api/v1/status` → `{"status": "ok", "version": "1.0.0", ...}`

---

## Alternative: CLI Deployment

### Install Railway CLI

```bash
# macOS/Linux
brew install railway

# Windows
scoop install railway

# NPM (all platforms)
npm install -g @railway/cli
```

### Deploy via CLI

```bash
# Login to Railway
railway login

# Link to existing project (or create new)
railway link

# Deploy
railway up

# View logs
railway logs

# Open in browser
railway open
```

---

## Configuration Files Reference

### Procfile (Startup Command)

```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

**What this does:**
- `uvicorn` - ASGI server
- `main:app` - Import `app` from `main.py`
- `--host 0.0.0.0` - Bind to all interfaces
- `--port $PORT` - Use Railway's assigned port

### runtime.txt (Python Version)

```
python-3.11.9
```

Specifies exact Python version for Railway to use.

### requirements.txt (Dependencies)

All Python packages are listed with pinned versions for reproducibility.

```
fastapi==0.115.0
uvicorn[standard]==0.29.0
pydantic==2.6.4
...
```

---

## Environment Variables Explained

### Automatic (Provided by Railway)

| Variable | Value | Description |
|----------|-------|-------------|
| `PORT` | Auto-assigned | Port Railway assigns to your service |
| `DATABASE_URL` | Auto-injected | PostgreSQL connection string (when DB added) |
| `RAILWAY_PUBLIC_DOMAIN` | Auto-set | Your service's public domain |

### Required (You Must Set)

| Variable | Example | Description |
|----------|---------|-------------|
| `FRONTEND_ORIGIN` | `https://myapp.vercel.app` | Your frontend domain for CORS |
| `AWS_S3_BUCKET` | `looparchitect-files` | S3 bucket for file storage |
| `AWS_ACCESS_KEY_ID` | `AKIAIOSFODNN7EXAMPLE` | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | `wJalrXUtnFEMI/K7MDENG...` | AWS secret key |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `production` | Environment name |
| `DEBUG` | `false` | Debug mode (set to `false` in production) |
| `RENDER_EXTERNAL_URL` | Auto-set | For Render migration compatibility |

---

## Troubleshooting

### Issue: "Module not found" error

**Solution**: Ensure `requirements.txt` is in the root directory and contains all dependencies.

```bash
# Regenerate requirements.txt locally
pip freeze > requirements.txt
```

### Issue: "Port already in use" or "Address already in use"

**Cause**: Not using Railway's `$PORT` variable.  
**Solution**: Verify Procfile uses `--port $PORT`

### Issue: Database connection errors

**Solution**: 
1. Ensure PostgreSQL database is added in Railway dashboard
2. Check `DATABASE_URL` is automatically injected
3. Verify database migrations ran successfully in logs

### Issue: CORS errors from frontend

**Solution**:
1. Set `FRONTEND_ORIGIN` environment variable in Railway
2. Verify your frontend domain is correct (no trailing slash)
3. Check `app/config.py` to ensure CORS middleware is configured

### Issue: "502 Bad Gateway" or "503 Service Unavailable"

**Possible causes:**
1. App failed to start - Check deployment logs
2. Database migrations failed - Check logs for migration errors
3. Missing environment variables - Verify all required vars are set

**Solution**: Review deployment logs in Railway dashboard for specific error.

---

## Database Migrations

Migrations run automatically on startup via `main.py`:

```python
def run_migrations():
    """Run Alembic migrations to update database schema."""
    from alembic import command
    command.upgrade(alembic_cfg, "head")
```

### Manual Migration (if needed)

If automatic migrations fail, you can run them manually via Railway CLI:

```bash
# Connect to your Railway project
railway link

# Run migrations
railway run alembic upgrade head

# Or open a shell
railway shell
python -m alembic upgrade head
```

---

## Scaling & Performance

### Horizontal Scaling

Railway supports horizontal scaling:

1. Go to Service → Settings
2. Under "Scaling", increase replica count
3. Railway handles load balancing automatically

### Vertical Scaling

Railway auto-scales CPU/RAM based on usage. No configuration needed.

### Database Connection Pooling

Already configured in `app/db.py`:

```python
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
```

---

## Monitoring

### View Logs

```bash
# Via CLI
railway logs

# Via Dashboard
Project → Service → Deployments → Click deployment → View logs
```

### Health Checks

Railway automatically monitors:
- HTTP health checks on `/health` endpoint
- Container crashes and auto-restarts
- Database connectivity

### Metrics

Railway dashboard shows:
- CPU usage
- Memory usage
- Request count
- Response times

---

## Rollback

### Via Dashboard

1. Go to Deployments
2. Find previous successful deployment
3. Click "..." → "Redeploy"

### Via CLI

```bash
# View deployment history
railway status

# Redeploy specific deployment
railway redeploy <deployment-id>
```

---

## Cost Estimation

Railway pricing (as of 2024):

- **Hobby Plan**: $5/month
  - 500GB bandwidth
  - $5 in compute credits
  - Suitable for development/testing

- **Pro Plan**: $20/month
  - Everything in Hobby
  - More resources and priority support

**Typical usage for LoopArchitect API:**
- Small to medium traffic: ~$10-20/month
- Includes PostgreSQL database, web service, and bandwidth

---

## Security Best Practices

### 1. Environment Variables

✅ **DO**: Store secrets in Railway environment variables  
❌ **DON'T**: Commit secrets to Git

### 2. HTTPS

✅ Railway provides free HTTPS automatically on all deployments

### 3. Database

✅ `DATABASE_URL` uses encrypted connections by default  
✅ Railway databases are in private networks

### 4. CORS

✅ Configured in `app/config.py` to only allow your frontend domains

### 5. API Keys

✅ Store AWS credentials as environment variables  
❌ Never hardcode in source code

---

## Continuous Deployment

Railway automatically deploys on every push to your main branch.

### Disable Auto-Deploy (if needed)

1. Go to Service → Settings
2. Under "Deployments", toggle off "Auto-deploy"

### Manual Approval Flow

1. Push changes to GitHub
2. Railway detects changes but waits
3. In Railway dashboard, click "Deploy" to approve

---

## Support & Resources

- **Railway Docs**: https://docs.railway.app
- **Railway Discord**: https://discord.gg/railway
- **FastAPI Docs**: https://fastapi.tiangolo.com
- **This Project's Docs**: See `DEPLOYMENT.md`, `QUICK_START.md`

---

## Quick Reference Commands

```bash
# Check deployment status
railway status

# View logs
railway logs --follow

# Open service in browser
railway open

# Run command in Railway environment
railway run python -m alembic upgrade head

# SSH into container
railway shell

# Link local directory to Railway project
railway link

# Deploy current directory
railway up

# Add environment variable
railway variables set KEY=value

# View environment variables
railway variables
```

---

## Summary Checklist

- [ ] Railway account created
- [ ] GitHub repository connected
- [ ] PostgreSQL database added
- [ ] Environment variables configured:
  - [ ] `FRONTEND_ORIGIN`
  - [ ] `AWS_S3_BUCKET`
  - [ ] `AWS_ACCESS_KEY_ID`
  - [ ] `AWS_SECRET_ACCESS_KEY`
- [ ] Deployment successful (check logs)
- [ ] Health checks passing (`/health` returns 200)
- [ ] API docs accessible (`/docs`)
- [ ] Frontend can connect (no CORS errors)

---

**Your LoopArchitect API is now live on Railway!** 🚀

Public URL: `https://your-service.railway.app`

API Docs: `https://your-service.railway.app/docs`
