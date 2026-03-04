# PHASE 4: Style Slider Integration - Test Guide

**Status**: ✅ IMPLEMENTATION COMPLETE  
**Test Environment**: ✅ READY (Both servers running)

---

## Quick Test Procedure

### 1️⃣ Verify Backend Integration

Test that the backend properly receives and maps style parameters:

```powershell
# Test arrangement generation with style parameters
$payload = @{
    loop_id = 1
    target_seconds = 30
    style_text_input = "dark aggressive trap"
    use_ai_parsing = $true
    style_params = @{
        energy = 0.85
        darkness = 0.92
        bounce = 0.55
        warmth = 0.25
        texture = "gritty"
    }
} | ConvertTo-Json -Depth 10

try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/arrangements/generate" -Method POST -ContentType "application/json" -Body $payload -UseBasicParsing
    Write-Host "✅ Request successful: $($response.StatusCode)" -ForegroundColor Green
    $response.Content | ConvertFrom-Json | ConvertTo-Json -Depth 5
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    $responseBody = $reader.ReadToEnd()
    Write-Host "❌ Request failed: $statusCode" -ForegroundColor Red
    Write-Host $responseBody
}
```

**Expected Backend Logs**:
```
INFO: Parsing style text: dark aggressive trap
INFO: Applying style overrides from sliders: {'aggression': 0.85, 'darkness': 0.92, 'bounce': 0.55, 'melody_complexity': 0.25, 'fx_density': 0.8}
```

---

### 2️⃣ Frontend UI Test

**Manual Test Steps**:

1. **Open Frontend**:
   ```
   http://localhost:3000/generate
   ```

2. **Select Loop**:
   - Enter Loop ID: `1` (or any valid loop in your database)
   - Click "Load Loop"

3. **Configure Style** (Natural Language Mode):
   - Switch to "Natural Language" input mode
   - Enter: `"dark aggressive trap with heavy bass"`

4. **Adjust Style Sliders**:
   - **Energy**: Slide to 85%
   - **Darkness**: Slide to 92%
   - **Bounce**: Slide to 55%
   - **Warmth**: Slide to 25%
   - **Texture**: Select "Gritty"

5. **Generate Arrangement**:
   - Set duration: `120` seconds
   - Click "Generate Arrangement"

6. **Verify Backend Logs**:
   - Check terminal running backend
   - Should see log: `Applying style overrides from sliders: {...}`

7. **Expected Behavior**:
   - Request succeeds (202 Accepted)
   - Arrangement ID returned
   - Audio generation starts in background
   - Slider values influence final audio output

---

### 3️⃣ Field Mapping Verification

Test the field mapping function:

```powershell
cd c:\Users\steve\looparchitect-backend-api
.\.venv\Scripts\python.exe test_phase4_integration.py
```

**Expected Output**:
```
================================================================================
🎉 PHASE 4 INTEGRATION TEST: ALL TESTS PASSED
================================================================================

Mapping Rules:
  Frontend 'energy' (0-1)      → Backend 'aggression' (0-1)
  Frontend 'darkness' (0-1)    → Backend 'darkness' (0-1)
  Frontend 'bounce' (0-1)      → Backend 'bounce' (0-1)
  Frontend 'warmth' (0-1)      → Backend 'melody_complexity' (0-1)
  Frontend 'texture' (string)  → Backend 'fx_density' (0.3/0.5/0.8)

Integration Status:
  ✅ Frontend sends styleProfile as styleParams
  ✅ API client supports Record<string, number | string>
  ✅ Backend receives style_params dict
  ✅ Backend maps to StyleOverrides object
  ✅ LLM parser receives overrides parameter
  ✅ Audio rendering will use slider values
```

---

### 4️⃣ Check Database for Loops

Verify you have a loop to test with:

```powershell
cd c:\Users\steve\looparchitect-backend-api
.\.venv\Scripts\python.exe -c "from app.db import SessionLocal; from app.models.loop import Loop; db = SessionLocal(); loops = db.query(Loop).limit(5).all(); print('Available Loops:'); [print(f'  ID: {l.id}, Name: {l.name}, BPM: {l.bpm}') for l in loops]; db.close()"
```

**If no loops exist**, upload one via frontend:
```
http://localhost:3000
- Click "Upload New Loop"
- Select audio file (<100MB)
- Enter loop details
```

---

## A/B Comparison Test

To verify sliders actually affect output, test with SAME text but DIFFERENT slider values:

### Test A: High Energy + Dark
```json
{
  "style_text_input": "trap beat",
  "style_params": {
    "energy": 0.9,
    "darkness": 0.9,
    "bounce": 0.5,
    "warmth": 0.3,
    "texture": "gritty"
  }
}
```

### Test B: Low Energy + Bright
```json
{
  "style_text_input": "trap beat",
  "style_params": {
    "energy": 0.2,
    "darkness": 0.1,
    "bounce": 0.5,
    "warmth": 0.7,
    "texture": "smooth"
  }
}
```

**Expected**: Generated audio from Test A should be noticeably louder, darker, and more aggressive than Test B.

---

## Network Debugging (If Issues)

### Check Frontend Network Tab

1. Open DevTools (F12)
2. Go to "Network" tab
3. Click "Generate Arrangement"
4. Find POST request to `/arrangements/generate`
5. Check "Payload" tab - should see `style_params` object

### Check Request Size

```javascript
// In browser console
fetch('http://localhost:8000/api/v1/arrangements/generate', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    loop_id: 1,
    target_seconds: 30,
    style_text_input: "test",
    use_ai_parsing: true,
    style_params: {
      energy: 0.8,
      darkness: 0.9,
      bounce: 0.6,
      warmth: 0.3,
      texture: "gritty"
    }
  })
}).then(r => {
  console.log('Status:', r.status);
  return r.json();
}).then(d => console.log('Response:', d))
.catch(e => console.error('Error:', e));
```

---

## Common Issues

### Issue 1: 413 Payload Too Large
**Cause**: File upload >100MB  
**Fix**: Increase `MAX_UPLOAD_SIZE_MB` in `.env`  
**Note**: Style params (~500 bytes) should NEVER cause 413

### Issue 2: Style params not logged
**Symptom**: No "Applying style overrides from sliders" log  
**Cause**: Either:
- Not using "Natural Language" mode
- Sliders not adjusted (all at default)
- Frontend not sending styleParams

**Debug**:
```powershell
# Check if frontend code includes styleParams
cd c:\Users\steve\looparchitect-frontend
Select-String -Path "src/app/generate/page.tsx" -Pattern "styleParams" -Context 2
```

### Issue 3: Arrangement generation fails
**Symptom**: 500 error or validation error  
**Causes**:
- Invalid loop_id (doesn't exist)
- Missing OpenAI API key (if use_ai_parsing=true)
- Database connection issue

**Check backend logs** for specific error.

### Issue 4: Audio doesn't reflect slider settings
**Symptom**: Generated audio sounds the same regardless of slider values  
**Possible Causes**:
- LLM parser overrides not being applied (check backend logs)
- Audio rendering engine not using style profile
- Need to wait for arrangement to complete processing

**Verify in logs**: Look for "Applying style overrides from sliders"

---

## Key Files Modified (PHASE 4)

### Backend
- ✅ `app/config.py` - Added upload size limits
- ✅ `app/routes/arrangements.py` - Added field mapping + integration
- ✅ `app/routes/loops.py` - Uses configurable upload limit
- ✅ `main.py` - Configured request body size

### Frontend
- ✅ `src/app/generate/page.tsx` - Sends styleProfile as styleParams
- ✅ `api/client.ts` - Type support for Record<string, number | string>

### Testing
- ✅ `test_phase4_integration.py` - Unit tests for mapping function

### Documentation
- ✅ `PHASE_4_COMPLETION_REPORT.md` - Complete implementation details
- ✅ `FILE_UPLOAD_SIZE_LIMITS.md` - Size limit troubleshooting

---

## Success Criteria

- ✅ Backend receives style_params in request
- ✅ Backend logs "Applying style overrides from sliders"
- ✅ Field mapping converts frontend → backend schema
- ✅ LLM parser receives StyleOverrides object
- ✅ Arrangement generation succeeds (202 status)
- ✅ Generated audio reflects slider settings

---

## Next Steps After PHASE 4

Once testing confirms PHASE 4 works:

1. **PHASE 5**: Implement real-time audio preview
2. **PHASE 6**: Add preset system for style combinations
3. **PHASE 7**: Implement slider history/favorites
4. **PHASE 8**: Production deployment with monitoring

---

## Quick Commands Reference

```powershell
# Check server status
Get-NetTCPConnection -State Listen -LocalPort 8000,3000 -ErrorAction SilentlyContinue | Select-Object LocalPort

# View backend logs (watch for "Applying style overrides")
# (Backend terminal shows logs in real-time)

# Check upload limits
cd c:\Users\steve\looparchitect-backend-api
.\.venv\Scripts\python.exe -c "from app.config import settings; print(f'Upload: {settings.max_upload_size_mb}MB')"

# Run integration tests
.\.venv\Scripts\python.exe test_phase4_integration.py

# Check database loops
.\.venv\Scripts\python.exe -c "from app.db import SessionLocal; from app.models.loop import Loop; db = SessionLocal(); print(f'Loops: {db.query(Loop).count()}'); db.close()"

# Restart backend (if needed)
$pid = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($pid) { Stop-Process -Id $pid -Force; Start-Sleep -Seconds 2 }
cd c:\Users\steve\looparchitect-backend-api
& .\.venv\Scripts\python.exe main.py

# Restart frontend (if needed)
Get-Process node -ErrorAction SilentlyContinue | Stop-Process -Force
cd c:\Users\steve\looparchitect-frontend
npm run dev
```

---

**Ready to Test**: Both servers are running! Start with the "Frontend UI Test" section above.

---

*Last Updated: March 4, 2026 - PHASE 4 Complete*
