# Deployment Checklist

## Pre-Deployment

### 1. Code Review ✅
- [x] Storage service created and tested
- [x] Audio service created and tested
- [x] Task service created and tested
- [x] Audio router created and mounted
- [x] Loops router refactored to use storage_service
- [x] Database migration created and applied
- [x] Schemas updated with new fields
- [x] Type hints added
- [x] Docstrings added

### 2. Database Migration ✅
- [x] Migration file created: `003_add_task_fields.py`
- [x] Migration applied locally: `alembic upgrade head`
- [x] Verify migration status: `alembic current` shows `003_add_task_fields`

### 3. Dependencies ✅
All required packages in requirements.txt:
- [x] boto3>=1.34.0 (AWS S3)
- [x] librosa>=0.10.0 (audio analysis)
- [x] pydub>=0.25.1 (audio manipulation)
- [x] fastapi>=0.110.0
- [x] sqlalchemy>=2.0
- [x] alembic (migrations)

### 4. Environment Variables
Review `.env.example` for all required variables:
- [x] DATABASE_URL
- [x] AWS_S3_BUCKET (optional, enables S3)
- [x] AWS_ACCESS_KEY_ID (if using S3)
- [x] AWS_SECRET_ACCESS_KEY (if using S3)
- [x] AWS_REGION (optional, defaults to us-east-1)

---

## Render.com Deployment

### Step 1: Set Environment Variables

In Render Dashboard → Environment:

```bash
# Database (Render auto-provides this for PostgreSQL service)
DATABASE_URL=<provided-by-render-postgres>

# AWS S3 Configuration (REQUIRED for production)
AWS_S3_BUCKET=looparchitect-audio-files
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# These are auto-set by Render
RENDER=true
RENDER_EXTERNAL_URL=<auto-set>
```

### Step 2: AWS S3 Setup

1. **Create S3 Bucket:**
   ```bash
   # Via AWS Console or CLI
   aws s3 mb s3://looparchitect-audio-files --region us-east-1
   ```

2. **Configure Bucket CORS:**
   ```json
   [
     {
       "AllowedHeaders": ["*"],
       "AllowedMethods": ["GET", "PUT", "POST", "DELETE"],
       "AllowedOrigins": ["*"],
       "ExposeHeaders": ["ETag"]
     }
   ]
   ```

3. **Create IAM User:**
   - User name: `looparchitect-s3-user`
   - Permissions: Attach policy below

4. **IAM Policy:**
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "s3:PutObject",
           "s3:GetObject",
           "s3:DeleteObject",
           "s3:ListBucket"
         ],
         "Resource": [
           "arn:aws:s3:::looparchitect-audio-files",
           "arn:aws:s3:::looparchitect-audio-files/*"
         ]
       }
     ]
   }
   ```

5. **Get Access Keys:**
   - Save `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
   - Add to Render environment variables

### Step 3: Database Migration

**Option A: Automatic (Recommended)**  
Migrations run automatically on startup via `main.py:run_migrations()`

**Option B: Manual**
```bash
# Via Render Shell
alembic current  # Check current revision
alembic upgrade head  # Apply migrations
```

### Step 4: Verify Deployment

1. **Health Check:**
   ```bash
   curl https://your-app.onrender.com/api/v1/health
   ```

   Expected response:
   ```json
   {
     "status": "healthy",
     "message": "API is running"
   }
   ```

2. **Database Health:**
   ```bash
   curl https://your-app.onrender.com/api/v1/db-health
   ```

   Expected response:
   ```json
   {
     "status": "healthy",
     "database": "connected",
     "migration_version": "003_add_task_fields"
   }
   ```

3. **Test Upload:**
   ```bash
   curl -X POST https://your-app.onrender.com/api/v1/loops/upload \
     -F "file=@test-loop.wav"
   ```

   Expected response:
   ```json
   {
     "loop_id": 1,
     "file_url": "https://looparchitect-audio-files.s3.amazonaws.com/..."
   }
   ```

4. **Test Download:**
   ```bash
   curl https://your-app.onrender.com/api/v1/loops/1/download
   ```

   Should redirect to S3 presigned URL.

5. **Test Analysis:**
   ```bash
   curl -X POST https://your-app.onrender.com/api/v1/analyze-loop/1
   ```

   Expected response:
   ```json
   {
     "loop_id": 1,
     "status": "pending",
     "check_status_at": "/api/v1/loops/1"
   }
   ```

---

## Local Development Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Create .env File
```bash
cp .env.example .env
```

Edit `.env`:
```bash
DATABASE_URL=sqlite:///./database.db  # or PostgreSQL
# Leave AWS vars commented for local file storage
```

### 3. Run Migrations
```bash
alembic upgrade head
```

### 4. Start Server
```bash
uvicorn main:app --reload --port 8000
```

### 5. Test Locally
```bash
# Open browser
http://localhost:8000/docs

# Upload test file
curl -X POST http://localhost:8000/api/v1/loops/upload \
  -F "file=@test-loop.wav"

# Analyze
curl -X POST http://localhost:8000/api/v1/analyze-loop/1

# Check status
curl http://localhost:8000/api/v1/loops/1

# Download
curl http://localhost:8000/api/v1/loops/1/download -o output.wav
```

---

## Troubleshooting

### Issue: Migration fails
**Solution:**
```bash
# Check current migration
alembic current

# If stuck, downgrade and re-upgrade
alembic downgrade -1
alembic upgrade head
```

### Issue: S3 upload fails
**Check:**
1. AWS_S3_BUCKET env var is set
2. AWS credentials are valid
3. IAM policy allows s3:PutObject
4. Bucket exists and is in correct region

**Debug:**
```bash
# Test AWS credentials
aws s3 ls s3://your-bucket-name --profile default

# Check Render logs
# Dashboard → Logs → Filter "storage_service"
```

### Issue: Audio analysis fails
**Check:**
1. File is valid WAV or MP3
2. librosa is installed
3. File is accessible (local mode only)

**For S3 mode:**
- Analysis requires file download
- Use `/analyze-loop` endpoint instead of immediate analysis

### Issue: Background tasks not running
**Check:**
1. Task service imported correctly
2. Database connection is working
3. Loop record exists

**Debug:**
```bash
# Check logs for task_service
# Look for "Processing" and "Complete" messages
```

### Issue: Download returns 404
**Check:**
1. Loop exists in database
2. file_url field is not null
3. For S3: File exists in bucket
4. For local: File exists in uploads/ directory

---

## Post-Deployment Tasks

### 1. Monitor Logs
```bash
# Render Dashboard → Logs
# Watch for:
# - "Database migrations completed successfully"
# - "✅ App imports successfully"
# - S3 upload/download messages
# - Task completion messages
```

### 2. Test All Endpoints
Use the provided test suite in `API_REFERENCE.md`

### 3. Performance Monitoring
- Monitor task completion times
- Check S3 presigned URL expiration (1 hour)
- Monitor database query performance

### 4. Cost Monitoring
- S3 storage costs
- S3 request costs (GET, PUT)
- Data transfer costs
- Render instance costs

---

## Rollback Plan

### If Issues Arise

1. **Revert Code:**
   ```bash
   git revert HEAD
   git push
   ```

2. **Rollback Migration:**
   ```bash
   alembic downgrade -1  # or specific revision
   ```

3. **Disable S3 (Emergency):**
   ```bash
   # In Render Dashboard, remove AWS_S3_BUCKET env var
   # App will fall back to local storage
   ```

---

## Success Criteria

- [x] All health checks return 200 OK
- [x] File upload works (local and S3)
- [x] File download works (presigned URLs)
- [x] Audio analysis completes successfully
- [x] Beat generation completes successfully
- [x] Background tasks update status correctly
- [x] Database migrations applied
- [x] No critical errors in logs
- [x] API documentation accessible at /docs

---

## Security Reminders

- [ ] Never commit .env file
- [ ] Use IAM user with minimal permissions
- [ ] Rotate AWS credentials periodically
- [ ] Enable S3 bucket versioning
- [ ] Set S3 bucket to private (not public)
- [ ] Use presigned URLs for downloads (not public URLs)
- [ ] Validate file types before upload
- [ ] Limit file sizes (currently 50MB)

---

## Next Steps After Deployment

1. **Monitor for 24 hours:**
   - Check logs for errors
   - Monitor S3 costs
   - Monitor task completion rates

2. **Optimize if needed:**
   - Adjust presigned URL expiration time
   - Tune background task queue size
   - Optimize librosa analysis parameters

3. **Documentation:**
   - Update README with new endpoints
   - Share API_REFERENCE.md with frontend team
   - Document any production-specific behavior

4. **Enhancements (Future):**
   - Add webhook notifications
   - Add task retry logic
   - Add file format conversion
   - Add batch operations
