# 🚀 Quick Test Reference Card

## Local Development

**Start the dev server:**
```powershell
.\dev.ps1
```

Then open: **http://127.0.0.1:8000/docs**

---

## One-Minute Testing Guide

### In Swagger UI (`/docs`)

```
1. POST /api/v1/loops
   Input: {"name":"Test","tempo":140}
   Output: {"id":5,...}
   
2. POST /api/v1/render-simulated/5
   Input: (none)
   Output: {"render_url":"/api/v1/renders/instrumental_5.wav",...}
   
3. GET /api/v1/renders/instrumental_5.wav
   Input: (none)
   Output: Download WAV file
```

### In Browser

```
https://looparchitect-backend-api.onrender.com/api/v1/renders/instrumental_5.wav
```

### With cURL

```bash
curl -O https://looparchitect-backend-api.onrender.com/api/v1/renders/instrumental_5.wav
```

---

## Expected Results

✅ **File Downloads:** Yes  
✅ **File Type:** RIFF WAV audio  
✅ **Duration:** 1 second  
✅ **Content:** Silence (placeholder)  
✅ **Playable:** Yes, in any audio player  

---

## Security Tests (Should All Fail as Expected)

| Test | URL | Expected | Status |
|------|-----|----------|--------|
| Path traversal | `../../../etc/passwd` | 400 error | ✅ |
| Directory access | `subfolder/file.wav` | 400 error | ✅ |
| Missing file | `nonexistent.wav` | 404 error | ✅ |
| Encoded traversal | `..%2F..%2Fconfig` | 400 error | ✅ |

---

## Implementation Files

| File | Change | Status |
|------|--------|--------|
| `main.py` | Directory creation | ✅ |
| `app/services/instrumental_renderer.py` | WAV generation | ✅ |
| `app/routes/render.py` | Download endpoint | ✅ |

---

## Key Features

✅ **No External Dependencies** - Uses Python's built-in `wave` module  
✅ **Secure** - Path traversal protection  
✅ **Fast** - Direct file serving via FileResponse  
✅ **Compatible** - Works in browser, curl, Swagger UI  
✅ **Tested** - All edge cases handled  

---

## What's Next

The system is ready for:
1. Real audio processing (replace 1-second silence)
2. Audio effects and mixing
3. Multiple format support (MP3, FLAC, etc.)
4. Streaming/chunked downloads for large files
5. Progress tracking for long renders

---

**TL;DR:** Everything works. Test it now in Swagger at `/docs` 🎉
