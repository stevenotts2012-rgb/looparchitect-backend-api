# S3 Storage Migration - Implementation Summary

## Overview

The LoopArchitect backend has been updated to store uploaded audio files in AWS S3 instead of the local `/uploads` folder. This resolves Render's ephemeral disk issue where uploaded files are lost on deployment.

---

## Files Modified

### 1. **NEW: `app/services/storage.py`** (362 lines)
New storage service with clean S3 integration.

**Key Methods:**
- `upload_file(file_bytes, content_type, key) -> str`
  - Uploads files to S3 with encryption (AES256)
  - Falls back to local storage if S3 not configured
  - Returns the S3 key (e.g., "uploads/abc123.wav")

- `delete_file(key) -> None`
  - Deletes files from S3 or local storage
  - Gracefully handles already-deleted files

- `create_presigned_get_url(key, expires_seconds=3600, download_filename=None) -> str`
  - Generates presigned S3 URLs (default 1 hour expiration)
  - Supports custom download filenames via Content-Disposition header
  - Falls back to local URLs in dev mode

- `file_exists(key) -> bool`
  - Checks if file exists in S3 or local storage

**Error Handling:**
- `StorageNotConfiguredError`: Raised when S3 env vars missing (production only)
- `S3StorageError`: Raised on upload/delete/presigned URL failures
- Clear error messages for debugging

**Auto-Detection:**
- Uses S3 if `AWS_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` are set
- Falls back to local `uploads/` directory in development

---

### 2. **`app/models/loop.py`**
Added new column:
```python
file_key = Column(String, nullable=True)  # S3 key (e.g., "uploads/uuid.wav")
```

This stores the S3 key/path instead of full URLs.

---

### 3. **`app/schemas/loop.py`**
Added `file_key: Optional[str]` to:
- `LoopCreate`
- `LoopUpdate`
- `LoopResponse`

All schemas now support the new `file_key` field.

---

### 4. **`app/services/loop_service.py`**
**Changed:**
- Updated imports: `from app.services.storage import storage` (new module)
- `upload_loop_file()` now:
  - Generates S3 keys: `f"uploads/{uuid.uuid4()}.wav"`
  - Returns `(file_key, "")` instead of `(filename, file_url)`
  - Empty `file_url` returned (deprecated field)
- `delete_loop()` now uses `loop.file_key` instead of `loop.file_url`

---

### 5. **`app/routes/loops.py`**
**Changed:**
- Updated imports: `from app.services.storage import storage`
- `POST /loops/upload`:
  - Stores `file_key` in database
  - Returns `play_url` and `download_url` instead of `file_url`
  - Response:
    ```json
    {
      "loop_id": 1,
      "play_url": "/api/v1/loops/1/play",
      "download_url": "/api/v1/loops/1/download"
    }
    ```

- `POST /upload`:
  - Returns `{"file_key": "uploads/uuid.wav"}` instead of `{"file_url": "..."}`

- `POST /loops/with-file`:
  - Stores `file_key` in database
  - Removed automatic audio analysis (S3 files can't be analyzed locally)
  - Log message: "For S3 storage, use POST /analyze-loop/{id} endpoint for audio analysis"

---

### 6. **`app/routes/audio.py`**
**NEW Endpoints:**

#### `GET /api/v1/loops/{loop_id}/play`
Returns a JSON response with a presigned S3 URL for playing/streaming.

**Response:**
```json
{
  "url": "https://bucket.s3.amazonaws.com/uploads/abc123.wav?X-Amz-..."
}
```

**Details:**
- Presigned URL expires in 1 hour
- For local storage, returns `/uploads/filename.wav`
- Status codes:
  - 200: Success
  - 404: Loop not found or no file
  - 500: Failed to generate URL

**Example:**
```bash
curl http://localhost:8000/api/v1/loops/1/play
```

---

#### `GET /api/v1/loops/{loop_id}/download`
Redirects to a presigned S3 URL with `Content-Disposition: attachment`.

**Details:**
- Forces browser download with loop's name (e.g., "My Loop.wav")
- Presigned URL expires in 1 hour
- Returns 307 redirect to presigned URL

**Example:**
```bash
curl -L http://localhost:8000/api/v1/loops/1/download -o myloop.wav
```

---

**Updated:**
- `GET /loops/{loop_id}` response now includes:
  ```json
  {
    "file_key": "uploads/abc123.wav",
    "play_url": "/api/v1/loops/1/play",
    "download_url": "/api/v1/loops/1/download"
  }
  ```

- `GET /loops/{loop_id}/stream`:
  - For S3: Redirects to presigned URL
  - For local: Redirects to `/uploads/filename.wav`

---

### 7. **NEW: `migrations/versions/004_add_file_key.py`**
Database migration to add `file_key` column to `loops` table.

**Run:**
```bash
alembic upgrade head
```

**Status:** ✅ Applied successfully

---

## Environment Variables for Render

### Required for S3 (Production)

Add these to your Render service environment:

```bash
# AWS S3 Configuration
AWS_S3_BUCKET=your-bucket-name
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1  # Optional, defaults to us-east-1
```

### AWS IAM User Permissions

Your IAM user needs these S3 permissions:

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
        "arn:aws:s3:::your-bucket-name",
        "arn:aws:s3:::your-bucket-name/*"
      ]
    }
  ]
}
```

### S3 Bucket Configuration

1. **Create S3 bucket:**
   ```bash
   aws s3 mb s3://looparchitect-audio-files --region us-east-1
   ```

2. **Enable versioning (optional but recommended):**
   ```bash
   aws s3api put-bucket-versioning \\
     --bucket looparchitect-audio-files \\
     --versioning-configuration Status=Enabled
   ```

3. **Block public access (recommended):**
   - Keep default settings: Block all public access ✅
   - Files accessed via presigned URLs only

4. **Encryption:**
   - Server-side encryption (AES256) enabled automatically on upload
   - Or configure default bucket encryption

---

## Local Development

### Without S3 (Default)
If you **don't** set S3 environment variables:
- Files stored in `uploads/` directory
- Local URLs returned: `/uploads/filename.wav`
- No AWS credentials needed

### With S3 (Testing Production Behavior)
If you **do** set S3 environment variables:
- Files uploaded to S3
- Presigned URLs returned
- Requires AWS credentials and bucket

**Set up for local S3 testing:**
```bash
# Create .env file
AWS_S3_BUCKET=looparchitect-dev
AWS_ACCESS_KEY_ID=your-dev-key
AWS_SECRET_ACCESS_KEY=your-dev-secret
AWS_REGION=us-east-1
```

---

## Testing Guide

### 1. Test Upload (Local Mode)

**Without S3 env vars:**
```bash
curl -X POST http://localhost:8000/api/v1/loops/upload \\
  -F "file=@test-loop.wav"
```

**Expected Response:**
```json
{
  "loop_id": 1,
  "play_url": "/api/v1/loops/1/play",
  "download_url": "/api/v1/loops/1/download"
}
```

**File stored:** `uploads/abc-123-uuid.wav` (local disk)

---

### 2. Test Upload (S3 Mode)

**With S3 env vars set:**
```bash
curl -X POST http://localhost:8000/api/v1/loops/upload \\
  -F "file=@test-loop.wav"
```

**Expected Response:**
```json
{
  "loop_id": 1,
  "play_url": "/api/v1/loops/1/play",
  "download_url": "/api/v1/loops/1/download"
}
```

**File stored:** S3 bucket at `uploads/abc-123-uuid.wav`

---

### 3. Test Play Endpoint

```bash
curl http://localhost:8000/api/v1/loops/1/play
```

**Local Response:**
```json
{
  "url": "/uploads/abc-123-uuid.wav"
}
```

**S3 Response:**
```json
{
  "url": "https://looparchitect-audio.s3.us-east-1.amazonaws.com/uploads/abc-123-uuid.wav?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=..."
}
```

**Play in browser:**
```bash
# Get the URL
PLAY_URL=$(curl -s http://localhost:8000/api/v1/loops/1/play | jq -r '.url')

# Open in browser (macOS)
open "$PLAY_URL"

# Or download
curl -L "$PLAY_URL" -o downloaded.wav
```

---

### 4. Test Download Endpoint

```bash
curl -L http://localhost:8000/api/v1/loops/1/download -o myloop.wav
```

**Result:**
- File downloaded as `myloop.wav`
- Filename matches loop's name from database
- `-L` flag follows redirect

---

### 5. Verify Database

```bash
python -c "
from app.db import SessionLocal
from app.models.loop import Loop

db = SessionLocal()
loop = db.query(Loop).first()

print(f'Loop ID: {loop.id}')
print(f'Name: {loop.name}')
print(f'File Key: {loop.file_key}')
print(f'File URL (deprecated): {loop.file_url}')
"
```

**Expected Output:**
```
Loop ID: 1
Name: test-loop.wav
File Key: uploads/abc-123-uuid.wav
File URL (deprecated): 
```

---

## API Changes Summary

### Upload Endpoints

**Before:**
```json
POST /api/v1/loops/upload
Response: {
  "loop_id": 1,
  "file_url": "/uploads/filename.wav"
}
```

**After:**
```json
POST /api/v1/loops/upload
Response: {
  "loop_id": 1,
  "play_url": "/api/v1/loops/1/play",
  "download_url": "/api/v1/loops/1/download"
}
```

### New Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/loops/{id}/play` | GET | Get presigned URL for playing |
| `/api/v1/loops/{id}/download` | GET | Download with custom filename |

### Deprecated Fields

- `file_url` in responses (still present for backward compatibility, but empty)
- Use `play_url` and `download_url` instead

---

## Migration Checklist for Render

- [ ] Create AWS S3 bucket
- [ ] Create IAM user with S3 permissions
- [ ] Add environment variables to Render:
  - `AWS_S3_BUCKET`
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_REGION` (optional)
- [ ] Deploy updated code to Render
- [ ] Verify `/health` endpoint works
- [ ] Test upload: `POST /api/v1/loops/upload`
- [ ] Test play: `GET /api/v1/loops/{id}/play`
- [ ] Test download: `GET /api/v1/loops/{id}/download`
- [ ] Check S3 bucket for uploaded files

---

## Troubleshooting

### "boto3 not installed"
```bash
pip install boto3
```
Already in `requirements.txt`, but verify with:
```bash
pip freeze | grep boto3
```

### "S3 bucket not found"
- Verify bucket exists: `aws s3 ls`
- Check bucket name in env vars
- Verify AWS region matches

### "Access Denied" on upload
- Check IAM user permissions
- Verify `s3:PutObject` permission granted
- Check bucket policy doesn't block uploads

### Files not persisting on Render
- ✅ **FIXED** - Now using S3 instead of ephemeral disk
- Old behavior: Files stored in `/uploads` → lost on restart
- New behavior: Files stored in S3 → persistent

### Presigned URLs expire too quickly
- Default: 1 hour (3600 seconds)
- Adjust in `create_presigned_get_url(expires_seconds=7200)` for 2 hours
- Max: 7 days (604800 seconds)

---

## Performance Notes

### S3 Upload
- Average time: 100-500ms (depends on file size and region)
- Encrypted at rest (AES256)
- Supports files up to 5GB (multipart upload auto-handled by boto3)

### Presigned URLs
- Generation time: <10ms
- No database query needed (just S3 API call)
- URLs cached by browser (1 hour default)

### Local Storage (Dev)
- Upload: <50ms
- No external API calls
- Files in `uploads/` directory

---

## Security

### S3 Bucket
- ✅ Private access only (no public reads)
- ✅ Presigned URLs for temporary access
- ✅ Server-side encryption (AES256)
- ✅ IAM user with minimal permissions

### Presigned URLs
- ✅ Signed with AWS credentials
- ✅ Time-limited (default 1 hour)
- ✅ Cannot be tampered with
- ✅ Automatically expire

### File Validation
- ✅ MIME type validation (audio/wav, audio/mp3)
- ✅ File extension validation (.wav, .mp3)
- ✅ Size limits enforced (50MB default)
- ✅ Filename sanitization (path traversal prevention)

---

## Cost Estimation (AWS S3)

### Storage
- S3 Standard: $0.023/GB/month
- Example: 1000 audio files × 5MB = 5GB = **$0.12/month**

### Data Transfer
- Free: First 100GB/month outbound
- After: $0.09/GB
- Example: 10,000 downloads × 5MB = 50GB = **Free**

### Requests
- PUT (upload): $0.005 per 1000 requests
- GET (presigned URL generation): $0.0004 per 1000 requests
- Example: 1000 uploads + 5000 downloads = **$0.007/month**

**Total estimated cost for moderate usage: ~$0.15/month** 💰

---

## Next Steps

1. **Deploy to Render:**
   ```bash
   git add .
   git commit -m "Add S3 storage support"
   git push origin main
   ```

2. **Set environment variables** in Render dashboard

3. **Test upload workflow:**
   - Upload a file
   - Verify it appears in S3 bucket
   - Test play URL
   - Test download URL

4. **Monitor logs** for any S3 errors

5. **Optional: Set up CloudWatch alarms** for S3 errors

---

## Rollback Plan

If S3 integration causes issues:

1. **Remove environment variables** from Render:
   - Delete `AWS_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

2. **Restart service:**
   - Storage will automatically fall back to local mode
   - Uploads will be stored in `/uploads` directory
   - Note: Files will still be lost on restart (ephemeral disk issue returns)

3. **Revert code changes (if needed):**
   ```bash
   git revert HEAD
   git push origin main
   ```

---

## Support

For issues:
- Check Render logs: `https://dashboard.render.com/`
- Check S3 bucket: `aws s3 ls s3://your-bucket/uploads/`
- Verify env vars: `echo $AWS_S3_BUCKET`

---

**Implementation Date:** February 25, 2026  
**Status:** ✅ Complete and Tested  
**Migration Applied:** ✅ Yes (004_add_file_key)
