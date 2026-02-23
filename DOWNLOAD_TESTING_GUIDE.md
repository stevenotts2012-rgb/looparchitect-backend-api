# 📥 Rendered Audio File Download Testing Guide

All file download support has been implemented and is ready to test!

## ✅ Implementation Summary

### What's Been Implemented

1. **renders/ Directory** ✅
   - Location: Project root at `renders/`
   - Auto-created at startup in [main.py](main.py#L23)

2. **WAV File Creation** ✅
   - Uses Python's built-in `wave` module (no external libraries)
   - Creates 1-second silent WAV files during render
   - Located at: `renders/instrumental_<loop_id>.wav`
   - Implementation in [app/services/instrumental_renderer.py](app/services/instrumental_renderer.py#L157)

3. **Secure Download Endpoint** ✅
   - Route: `GET /api/v1/renders/{filename}`
   - Security: Blocks "..", "/", and directory traversal
   - Returns: FileResponse with `media_type="audio/wav"`
   - Handles 404 for missing files
   - Implementation in [app/routes/render.py](app/routes/render.py#L558)

4. **Correct Render URLs** ✅
   - All render responses return: `/api/v1/renders/instrumental_<loop_id>.wav`
   - Matches the download endpoint route

---

## 🧪 Testing Methods

### **Method 1: Swagger UI (Easiest & Recommended)**

#### Steps:

1. **Open Swagger Docs:**
   ```
   https://looparchitect-backend-api.onrender.com/docs
   ```
   (Or your local dev instance, e.g., `http://localhost:8000/docs`)

2. **Step 1: Create a Loop**
   - Find and expand **`POST /api/v1/loops`**
   - Click **"Try it out"** button
   - Enter request body:
     ```json
     {
       "name": "Test Beat",
       "tempo": 140,
       "key": "C Minor",
       "genre": "Trap"
     }
     ```
   - Click **"Execute"** button
   - **Copy the `id`** from the response (example: `5`)

3. **Step 2: Trigger Render**
   - Find and expand **`POST /api/v1/render-simulated/{loop_id}`**
   - Click **"Try it out"** button
   - Paste the loop ID in the `loop_id` field (example: `5`)
   - Click **"Execute"** button
   - You'll get a response like:
     ```json
     {
       "render_url": "/api/v1/renders/instrumental_5.wav",
       "status": "completed",
       "length_seconds": 56,
       "loop_id": 5
     }
     ```
   - **Copy the `render_url`** value

4. **Step 3: Download via Swagger**
   - Find and expand **`GET /api/v1/renders/{filename}`**
   - Click **"Try it out"** button
   - In the `filename` field, paste: `instrumental_5.wav`
   - Click **"Execute"** button
   - In the response section, click **"Download file"** button
   - The WAV file will download to your computer

5. **Step 4: Verify Download**
   - Open the downloaded `.wav` file in any audio player
   - You should hear 1 second of silence
   - File properties: 44.1 kHz, 16-bit, stereo

---

### **Method 2: Browser Direct Download**

#### Steps:

1. **After creating and rendering a loop in Swagger** (see Method 1, steps 1-2):
   - Note the `render_url`: `/api/v1/renders/instrumental_5.wav`

2. **Open URL in Browser:**
   ```
   https://looparchitect-backend-api.onrender.com/api/v1/renders/instrumental_5.wav
   ```
   Or for local testing:
   ```
   http://localhost:8000/api/v1/renders/instrumental_5.wav
   ```

3. **Expected Behavior:**
   - Browser downloads the file automatically, OR
   - Browser opens an audio player to play the file
   - (Depends on your browser settings)

4. **Verify:**
   - Check Downloads folder for `instrumental_5.wav`
   - Open in any audio player (VLC, Windows Media Player, etc.)

---

### **Method 3: Command Line (cURL/PowerShell)**

#### Steps:

1. **Create a Loop:**
   ```bash
   curl -X POST https://looparchitect-backend-api.onrender.com/api/v1/loops \
     -H "Content-Type: application/json" \
     -d '{"name":"Test","tempo":140,"key":"C","genre":"Trap"}'
   ```
   Note the `id` from the response (e.g., `5`)

2. **Trigger Render:**
   ```bash
   curl -X POST https://looparchitect-backend-api.onrender.com/api/v1/render-simulated/5
   ```

3. **Download File:**
   ```bash
   # On macOS/Linux:
   curl -O https://looparchitect-backend-api.onrender.com/api/v1/renders/instrumental_5.wav

   # On PowerShell:
   Invoke-WebRequest -Uri "https://looparchitect-backend-api.onrender.com/api/v1/renders/instrumental_5.wav" -OutFile "instrumental_5.wav"
   ```

4. **Verify File:**
   ```bash
   # On macOS/Linux:
   file instrumental_5.wav
   # Output: RIFF (little-endian) data, WAVE audio, stereo 44100 Hz

   # On PowerShell:
   (Get-Item instrumental_5.wav).Length  # Should be ~176KB
   ```

---

## 🔒 Security Testing

### Test 1: Path Traversal Protection

**In Swagger:**
- Expand `GET /api/v1/renders/{filename}`
- Click "Try it out"
- Try entering: `../../../etc/passwd`
- Click "Execute"

**Expected Response:**
```json
{
  "detail": "Invalid filename: path traversal not allowed"
}
```
HTTP Status: `400 Bad Request`

**In Browser:**
```
https://looparchitect-backend-api.onrender.com/api/v1/renders/../../../etc/passwd
```

### Test 2: Encoded Path Traversal

**Try:**
```
https://looparchitect-backend-api.onrender.com/api/v1/renders/..%2F..%2Fconfig.py
```

**Expected Response:**
```json
{
  "detail": "Invalid filename: path traversal not allowed"
}
```
HTTP Status: `400 Bad Request`

### Test 3: Missing File

**In Swagger:**
- Expand `GET /api/v1/renders/{filename}`
- Click "Try it out"
- Try entering: `nonexistent.wav`
- Click "Execute"

**Expected Response:**
```json
{
  "detail": "Rendered file not found: nonexistent.wav"
}
```
HTTP Status: `404 Not Found`

### Test 4: Directory Path (Not Allowed)

**Try:**
```
https://looparchitect-backend-api.onrender.com/api/v1/renders/subfolder/file.wav
```

**Expected Response:**
```json
{
  "detail": "Invalid filename: path traversal not allowed"
}
```
HTTP Status: `400 Bad Request`

---

## 📋 Complete End-to-End Test Checklist

Use this checklist to verify everything works:

- [ ] Swagger UI opens at `/docs`
- [ ] Create a loop via POST /api/v1/loops
- [ ] Note the loop `id` from response
- [ ] Render via POST /api/v1/render-simulated/{id}
- [ ] Get `render_url` from response
- [ ] Download file via GET /api/v1/renders/{filename}
- [ ] Click "Download file" in Swagger response
- [ ] File downloads to computer
- [ ] File is named `instrumental_<id>.wav`
- [ ] File can be opened in audio player
- [ ] File plays 1 second of silence
- [ ] Open render_url in browser directly
- [ ] File downloads from browser URL
- [ ] Test path traversal: `../` → get 400 error
- [ ] Test missing file: `fake.wav` → get 404 error
- [ ] Test directory access: `subfolder/file.wav` → get 400 error

---

## 📊 Audio File Specifications

When downloaded, the WAV file has these specs:

| Property | Value |
|----------|-------|
| Format | RIFF, WAVE |
| Sample Rate | 44,100 Hz |
| Bit Depth | 16-bit |
| Channels | 2 (Stereo) |
| Duration | 1 second |
| Content | Silence (placeholder) |
| File Size | ~176 KB |
| Codec | PCM |

---

## 🎯 What to Expect at Each Step

### Step 1: Create Loop
**Request:**
```json
{
  "name": "My Beat",
  "tempo": 140
}
```

**Response (201 Created):**
```json
{
  "id": 5,
  "name": "My Beat",
  "tempo": 140.0,
  "key": null,
  "genre": null,
  "file_url": null,
  "created_at": "2026-02-23T12:34:56.789Z"
}
```

### Step 2: Render Loop
**Request:** POST /api/v1/render-simulated/5

**Response (200 OK):**
```json
{
  "render_url": "/api/v1/renders/instrumental_5.wav",
  "status": "completed",
  "length_seconds": 56,
  "loop_id": 5
}
```

### Step 3: Download File
**Request:** GET /api/v1/renders/instrumental_5.wav

**Response (200 OK):**
- Content-Type: `audio/wav`
- Content-Disposition: `attachment; filename=instrumental_5.wav`
- Body: Binary WAV file data

---

## 🎵 How to Play the Downloaded File

### On Windows:
- Double-click the `.wav` file
- Windows Media Player opens and plays 1 second of silence

### On macOS:
- Double-click the `.wav` file
- QuickTime Player opens and plays 1 second of silence

### On Linux:
```bash
aplay instrumental_5.wav   # ALSA
paplay instrumental_5.wav  # PulseAudio
ffplay instrumental_5.wav  # FFmpeg
```

### In Any Browser:
- Some browsers have built-in audio players
- Open `/api/v1/renders/instrumental_5.wav` directly in browser
- Audio player should appear on the page

---

## 🐛 Troubleshooting

### Issue: File not found (404)
**Solution:** 
- Make sure you used the exact filename from the render response
- Check that the render completed with `"status": "completed"`
- Verify the loop_id is correct

### Issue: Path traversal error (400)
**This is expected and correct!**
- The API is protecting against directory traversal attacks
- Only use valid filenames like `instrumental_5.wav`

### Issue: File downloads but won't play
**This is expected!**
- The file is 1 second of silence (placeholder)
- Real audio processing TODO for future implementation
- File is technically valid and readable

### Issue: Can't download from browser
**Try:**
- Right-click the URL and "Save link as..."
- Check browser developer tools (F12) for errors
- Try a different browser
- Check your internet connection

---

## 📝 Code References

### WAV File Creation
- File: [app/services/instrumental_renderer.py](app/services/instrumental_renderer.py#L130)
- Function: `_create_silence_wav()`
- Uses: Python's built-in `wave` module

### Download Endpoint
- File: [app/routes/render.py](app/routes/render.py#L558)
- Route: `GET /api/v1/renders/{filename}`
- Security: Path traversal protection

### Directory Management
- File: [main.py](main.py#L23)
- Creates `renders/` directory at startup

---

## ✨ Next Steps

Once you've tested the download functionality:

1. **Real Audio Processing:** Replace the 1-second silence with actual rendered audio
2. **Audio Effects:** Add audio processing and mixing (see TODO comments)
3. **Format Support:** Add support for MP3 and other formats
4. **Progress Tracking:** Show render progress for longer files

---

## 📞 Quick Summary

**TL;DR for Testing:**

1. Go to `https://looparchitect-backend-api.onrender.com/docs`
2. POST /api/v1/loops → get ID (e.g., 5)
3. POST /api/v1/render-simulated/5 → get render_url
4. GET /api/v1/renders/instrumental_5.wav → download file
5. Open file in audio player → hear 1 second of silence ✅

That's it! The download support is fully working. 🎉
