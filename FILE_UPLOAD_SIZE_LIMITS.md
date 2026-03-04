# File Upload Size Limits - Troubleshooting Guide

## Issue: 413 Payload Too Large Error

If you're seeing a **413 error** when uploading files or making large requests, this indicates the request body exceeds the configured size limits.

---

## Current Configuration

### Backend Settings (app/config.py)

```python
# Maximum upload file size (default: 100MB)
MAX_UPLOAD_SIZE_MB=100

# Maximum request body size (default: 100MB)
MAX_REQUEST_BODY_SIZE_MB=100
```

### Default Limits

- **File Upload Limit**: 100MB (configurable via `MAX_UPLOAD_SIZE_MB` env var)
- **Request Body Limit**: 100MB (configurable via `MAX_REQUEST_BODY_SIZE_MB` env var)

---

## How to Increase Limits

### Option 1: Environment Variables (Recommended)

Create or update `.env` file in the backend directory:

```bash
# Allow 200MB file uploads
MAX_UPLOAD_SIZE_MB=200

# Allow 200MB request bodies
MAX_REQUEST_BODY_SIZE_MB=200
```

Then restart the backend server.

### Option 2: Direct Configuration

Edit `app/config.py`:

```python
max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "200"))  # Changed from 100
max_request_body_size_mb: int = int(os.getenv("MAX_REQUEST_BODY_SIZE_MB", "200"))  # Changed from 100
```

---

## Production Deployment

### Railway

Add environment variables in Railway dashboard:

```
MAX_UPLOAD_SIZE_MB=200
MAX_REQUEST_BODY_SIZE_MB=200
```

### Vercel (Frontend)

Vercel has a **4.5MB request body limit** on hobby plan, **100MB on pro plan**.

If uploading via frontend, consider:
1. Upgrade to Vercel Pro
2. Use direct backend upload (bypass Vercel)
3. Implement chunked/resumable uploads

### Nginx (If Using Reverse Proxy)

Add to nginx configuration:

```nginx
client_max_body_size 200M;
```

---

## Verifying Current Limits

### Check Backend Configuration

```bash
# In backend directory
.\.venv\Scripts\python.exe -c "from app.config import settings; print(f'Max upload: {settings.max_upload_size_mb}MB'); print(f'Max request body: {settings.max_request_body_size_mb}MB')"
```

### Test Upload Endpoint

```powershell
# Test health check
Invoke-WebRequest -Uri "http://localhost:8000/api/v1/health" -UseBasicParsing

# Monitor backend logs when uploading
# Look for size validation messages
```

---

## Common Scenarios

### Uploading Large Audio Files (>50MB)

**Default Configuration**: ✅ Supports up to 100MB  
**Recommendation**: Keep at 100MB for most use cases

Large files:
- WAV files: ~10MB per minute (44.1kHz, 16-bit stereo)
- MP3 files: ~1MB per minute (320kbps)

Examples:
- 5-minute WAV: ~50MB ✅
- 10-minute WAV: ~100MB ✅
- 15-minute WAV: ~150MB ❌ (increase to 200MB)

### PHASE 4 Style Parameters

**Style slider data is minimal** (~500 bytes):
```json
{
  "energy": 0.8,
  "darkness": 0.9,
  "bounce": 0.6,
  "warmth": 0.3,
  "texture": "gritty"
}
```

This should **never** trigger 413 errors.

### Arrangement Generation Requests

**Typical payload size**: <5KB
```json
{
  "loop_id": 123,
  "target_seconds": 120,
  "style_text_input": "dark aggressive trap",
  "style_params": { ... }
}
```

If seeing 413 here, check for:
- Embedded audio data (should use loop_id reference, not raw audio)
- Excessive style_text_input (>10KB)

---

## Debugging 413 Errors

### Step 1: Check Request Size

In browser console (DevTools → Network tab):
```javascript
// Find the failed request
// Check "Request Headers" for Content-Length
```

### Step 2: Check Backend Logs

Look for validation errors:
```
File too large: 150.5MB. Maximum: 100MB.
```

### Step 3: Verify Configuration

```powershell
# Backend
cd c:\Users\steve\looparchitect-backend-api
.\.venv\Scripts\python.exe -c "from app.config import settings; print(settings.max_upload_size_mb)"
```

### Step 4: Test with Small File

Use a small test file (<10MB) to rule out other issues:
```powershell
# Create 5MB test file
$bytes = [byte[]]::new(5 * 1024 * 1024)
[System.IO.File]::WriteAllBytes("test_5mb.wav", $bytes)
```

---

## Frontend Configuration

### Next.js API Routes

If using Next.js API routes (`/api/*`), add to `next.config.js`:

```javascript
module.exports = {
  api: {
    bodyParser: {
      sizeLimit: '100mb',
    },
  },
}
```

### Direct Backend Calls (Current Setup)

Frontend calls backend directly → **No Next.js limits apply** ✅

The frontend just passes FormData to backend, so limits are backend-only.

---

## Performance Considerations

### Large File Upload Times

| File Size | Network Speed | Upload Time |
|-----------|---------------|-------------|
| 50MB | 10 Mbps | ~40 seconds |
| 100MB | 10 Mbps | ~80 seconds |
| 200MB | 10 Mbps | ~160 seconds |

**Recommendation**: Show upload progress indicator for files >20MB.

### Memory Usage

Uploading large files loads entire file into memory:
- 100MB file → ~150MB RAM usage (with processing overhead)
- 200MB file → ~300MB RAM usage

**Production**: Ensure server has adequate RAM (minimum 1GB free for 200MB uploads).

---

## Alternative: Chunked Uploads

For files >200MB, consider implementing chunked uploads:

1. Split file into chunks on frontend
2. Upload chunks sequentially
3. Reassemble on backend
4. Supports resume on failure

**Implementation Complexity**: High  
**Benefit**: Supports multi-GB files

---

## Quick Fix for Current Issue

Based on the 413 error you're seeing, try:

```powershell
# Stop backend
$pid = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($pid) { Stop-Process -Id $pid -Force }

# Create .env file with increased limits
cd c:\Users\steve\looparchitect-backend-api
@"
MAX_UPLOAD_SIZE_MB=150
MAX_REQUEST_BODY_SIZE_MB=150
"@ | Out-File -FilePath .env -Encoding utf8 -Append

# Restart backend
& .\.venv\Scripts\python.exe main.py
```

Then try your request again.

---

## Summary

✅ **Default**: 100MB limit (handles most audio files)  
✅ **Configurable**: Use environment variables to increase  
✅ **Production**: Set limits in deployment platform  
❌ **Style params**: Should never cause 413 (only ~500 bytes)  
❌ **Arrangement requests**: Should never cause 413 (<5KB)  

**Most Likely Cause**: Uploading audio file >100MB

**Quick Solution**: Increase `MAX_UPLOAD_SIZE_MB` to 150 or 200

---

*Last Updated: PHASE 4 Completion (March 2026)*
