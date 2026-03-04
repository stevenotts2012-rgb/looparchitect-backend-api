# Style Engine V2 Smoke Testing Guide

**Purpose**: Comprehensive manual testing procedure for LLM-powered natural language style input feature.

**Prerequisites**:
- Backend running with `FEATURE_LLM_STYLE_PARSING=true`
- `OPENAI_API_KEY` configured in environment
- Database migrated to version 008 (style_profile_json column added)
- Frontend running with updated UI components
- At least one test loop uploaded to system

---

## Test Environment Setup

### 1. Environment Variables Check

**Backend (.env)**:
```bash
# Verify these are set
echo $OPENAI_API_KEY
echo $FEATURE_LLM_STYLE_PARSING
echo $OPENAI_MODEL

# Expected output
sk-proj-...
true
gpt-4
```

**Frontend**:
```bash
# Verify backend connection
curl http://localhost:8000/health
# Expected: {"status": "healthy"}
```

### 2. Database Migration Check

```bash
cd looparchitect-backend-api
alembic current
# Expected: 008 (head) or later
```

```sql
-- Check new columns exist
sqlite3 looparchitect.db "PRAGMA table_info(arrangements);"
# Should show: style_profile_json | TEXT
# Should show: ai_parsing_used | BOOLEAN
```

### 3. Upload Test Loop

```bash
# Upload a test loop
curl -X POST http://localhost:8000/loops/upload \
  -F "file=@test_assets/trap_loop_135bpm.wav"

# Expected response:
{
  "loop_id": 1,
  "play_url": "/api/download/uploads/...",
  "download_url": "/api/download/uploads/...",
  "analysis": {
    "bpm": 135,
    "key": "A Minor",
    "bars": 4,
    "duration": 7.1
  }
}

# Save loop_id for later tests
export TEST_LOOP_ID=1
```

---

## Test Suite

### Test 1: Basic Natural Language Input

**Test Case**: Simple style description without overrides

**Steps**:
1. Open frontend: `http://localhost:3000/generate?loopId=1`
2. Toggle to "Natural Language 🤖" mode
3. Enter style text: `"Southside type, aggressive"`
4. Ensure "Use AI Parsing" is checked
5. Set duration: 30 seconds
6. Click "Generate Arrangement"

**Expected Results**:
- ✅ Request succeeds (202 Accepted)
- ✅ Response shows `ai_parsing_used: true`
- ✅ `style_profile_summary` shows archetype like "atl_aggressive"
- ✅ `confidence` score is between 0.7 - 1.0
- ✅ `structure_preview` shows sections (intro, hook, verse, etc.)
- ✅ Progress bar starts at 0%
- ✅ Status polls every 2 seconds
- ✅ After 10-30 seconds, status changes to "done"
- ✅ Download button appears
- ✅ Audio file plays in waveform viewer
- ✅ Before/After comparison shows both original loop and arrangement

**API Verification**:
```bash
# Manual API test
curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 30,
    "style_text_input": "Southside type, aggressive",
    "use_ai_parsing": true
  }'

# Response example:
{
  "arrangement_id": 5,
  "loop_id": 1,
  "status": "queued",
  "created_at": "2025-01-15T12:00:00Z",
  "ai_parsing_used": true,
  "style_profile_summary": {
    "archetype": "atl_aggressive",
    "confidence": 0.92,
    "sections_count": 5
  },
  "structure_preview": [
    {"name": "intro", "bars": 4, "energy": 0.35},
    {"name": "hook", "bars": 8, "energy": 0.85},
    {"name": "verse", "bars": 8, "energy": 0.70}
  ]
}

# Check status
curl http://localhost:8000/arrangements/5

# Expected after completion:
{
  "id": 5,
  "status": "done",
  "progress": 100.0,
  "progress_message": "Generation complete",
  "output_url": "https://s3.amazonaws.com/...",
  ...
}
```

**Database Verification**:
```sql
-- Check arrangement record
SELECT id, loop_id, status, ai_parsing_used, style_profile_json 
FROM arrangements 
WHERE id = 5;

-- Expected:
-- id: 5
-- loop_id: 1
-- status: done
-- ai_parsing_used: 1 (true)
-- style_profile_json: {"intent": {"archetype": "atl_aggressive", ...}, ...}
```

**S3 Verification** (if using S3):
```bash
# Check S3 file exists
aws s3 ls s3://looparchitect-prod/arrangements/5.wav

# Expected:
# 2025-01-15 12:00:30  2048576 5.wav
```

---

### Test 2: Natural Language with Beat Switch

**Test Case**: User requests beat switch at specific bar

**Steps**:
1. Frontend: Natural Language mode
2. Style text: `"Metro Boomin type, dark, beat switch after hook"`
3. Duration: 60 seconds
4. Click Generate

**Expected Results**:
- ✅ LLM parses "beat switch after hook"
- ✅ `transitions` array includes `{"type": "beat_switch", "bar": <calculated>}`
- ✅ Section plan shows "beat_switch" or "drop" section after hook
- ✅ Audio audibly changes at beat switch point (listen manually)
- ✅ Beat switch occurs around bar 12-16 (depending on section lengths)

**Manual Listening Check**:
- Download generated audio
- Listen at ~15-20 second mark
- Should hear noticeable transition: percussion drop, bass change, or energy shift

**API Verification**:
```bash
curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 60,
    "style_text_input": "Metro Boomin type, dark, beat switch after hook",
    "use_ai_parsing": true
  }'

# Response should show transitions in structure_preview:
{
  "structure_preview": [
    {"name": "intro", "bars": 4, ...},
    {"name": "hook", "bars": 8, ...},
    {"name": "beat_switch", "bars": 4, ...},  # ← NEW SECTION
    {"name": "drop", "bars": 8, ...}
  ]
}
```

---

### Test 3: Natural Language with Manual Overrides

**Test Case**: LLM parsing + slider overrides

**Steps**:
1. Frontend: Natural Language mode
2. Style text: `"Melodic trap, Lil Baby vibe"`
3. Expand "Advanced Controls" accordion
4. Adjust sliders:
   - Aggression: 0.30 (low)
   - Darkness: 0.20 (low)
   - Bounce: 0.70 (high)
   - Melody Complexity: 0.90 (high)
5. Duration: 45 seconds
6. Click Generate

**Expected Results**:
- ✅ LLM parses "melodic trap" → archetype "melodic_trap"
- ✅ Slider overrides take precedence over LLM attributes
- ✅ `style_profile_summary` reflects overrides
- ✅ Audio is melodic (high melody_complexity)
- ✅ Audio is smooth (low aggression, low darkness)
- ✅ Audio has groove (high bounce)

**API Verification**:
```bash
curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 45,
    "style_text_input": "Melodic trap, Lil Baby vibe",
    "use_ai_parsing": true,
    "style_overrides": {
      "aggression": 0.30,
      "darkness": 0.20,
      "bounce": 0.70,
      "melody_complexity": 0.90
    }
  }'

# Check database for overrides
SELECT style_profile_json FROM arrangements WHERE id = <new_id>;

# Expected JSON structure:
{
  "intent": {
    "archetype": "melodic_trap",
    "attributes": {...}  # Original LLM values
  },
  "overrides": {
    "aggression": 0.30,
    "darkness": 0.20,
    "bounce": 0.70,
    "melody_complexity": 0.90
  },
  "resolved_params": {
    "aggression": 0.30,  # ← Override applied
    "melody_complexity": 0.90  # ← Override applied
  }
}
```

---

### Test 4: Producer Name Mapping

**Test Case**: LLM understands producer names

**Test Inputs**:

| Input | Expected Archetype | Expected Attributes |
|-------|-------------------|---------------------|
| "Southside type" | atl_aggressive | aggression > 0.7 |
| "Metro Boomin vibe" | dark_drill or atl_aggressive | darkness > 0.6 |
| "Lil Baby style" | melodic_trap | melody_complexity > 0.7 |
| "Pierre Bourne type" | melodic_trap | melody_complexity > 0.6 |
| "Tay Keith style" | dark_drill | aggression > 0.7 |
| "Wheezy type" | atl_melodic | melody_complexity > 0.6 |

**Steps** (for each input):
1. Frontend: Natural Language mode
2. Enter test input
3. Click Generate
4. Check `style_profile_summary.archetype`
5. Download and listen to verify style matches

**Expected Results**:
- ✅ Each input maps to appropriate archetype
- ✅ Audio characteristics match expected style
- ✅ No errors in backend logs

**Batch API Test**:
```bash
#!/bin/bash
# Test all producer mappings

for input in "Southside type" "Metro Boomin vibe" "Lil Baby style"; do
  echo "Testing: $input"
  
  curl -X POST http://localhost:8000/arrangements/generate \
    -H "Content-Type: application/json" \
    -d "{
      \"loop_id\": 1,
      \"target_seconds\": 30,
      \"style_text_input\": \"$input\",
      \"use_ai_parsing\": true
    }" | jq '.style_profile_summary.archetype'
  
  sleep 2
done
```

---

### Test 5: Variations System (Multiple Outputs)

**Test Case**: Generate 3 variations with "remix" mode

**Steps**:
1. Frontend: Natural Language mode
2. Style text: `"ATL trap, bouncy"`
3. Variations dropdown: Select "3 variations"
4. Variation mode: Select "Remix (different sections)"
5. Duration: 60 seconds
6. Click Generate

**Expected Results** (Note: Variations fully implemented in later phase):
- ✅ Request creates 3 separate arrangement records
- ✅ All 3 use same `StyleProfile` but different section orders
- ✅ Response includes `render_job_ids: ["arr_1", "arr_2", "arr_3"]`
- ✅ Frontend shows 3 progress bars
- ✅ All 3 complete successfully
- ✅ User can download all 3 variations
- ✅ Audio files differ in structure but same style

**API Verification**:
```bash
curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 60,
    "style_text_input": "ATL trap, bouncy",
    "use_ai_parsing": true,
    "variation_count": 3,
    "variation_mode": "remix"
  }'

# Response should include:
{
  "arrangement_id": 10,
  "render_job_ids": ["arr_10", "arr_11", "arr_12"],
  ...
}

# Check all 3 arrangements created
curl http://localhost:8000/arrangements?loop_id=1 | jq 'length'
# Expected: At least 3 new arrangements
```

---

### Test 6: Fallback to Rule-Based Parsing

**Test Case**: LLM fails or returns low confidence, system falls back gracefully

**Setup**:
```bash
# Simulate LLM failure by setting invalid API key
export OPENAI_API_KEY=sk-invalid-key
# Restart backend
```

**Steps**:
1. Frontend: Natural Language mode
2. Style text: `"dark aggressive"`
3. Click Generate

**Expected Results**:
- ✅ Request succeeds (does not return 500 error)
- ✅ Response shows `ai_parsing_used: false`
- ✅ Rule-based parser extracts keywords: "dark", "aggressive"
- ✅ Maps to "dark" preset with high aggression
- ✅ Warning logged in backend: "LLM parsing failed, falling back to rule-based"
- ✅ Audio still generates successfully

**Backend Logs Verification**:
```bash
# Check logs for fallback message
tail -f logs/uvicorn.log | grep "fallback"

# Expected:
# WARNING: LLM parsing failed, falling back to rule-based: AuthenticationError: Invalid API key
# INFO: Using rule-based parser for style input: "dark aggressive"
# INFO: Mapped keywords ['dark', 'aggressive'] to archetype: dark
```

**Restore API Key**:
```bash
export OPENAI_API_KEY=sk-proj-...
# Restart backend
```

---

### Test 7: Legacy Preset Mode Still Works

**Test Case**: Existing preset-based generation is not broken by V2

**Steps**:
1. Frontend: Toggle to "Preset Mode"
2. Select preset: "DARK / Aggressive"
3. Duration: 30 seconds
4. Click Generate

**Expected Results**:
- ✅ Request succeeds
- ✅ Response shows `ai_parsing_used: false` (or null)
- ✅ `style_preset: "dark"` in response
- ✅ Audio generates with dark preset characteristics
- ✅ No `style_profile_json` in database (uses legacy `arrangement_json`)

**API Verification**:
```bash
curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 30,
    "style_preset": "dark"
  }'

# Response should NOT have ai_parsing_used:
{
  "arrangement_id": 15,
  "style_preset": "dark",
  "structure_preview": [...]
}

# Database check
SELECT style_profile_json, arrangement_json FROM arrangements WHERE id = 15;

# Expected:
# style_profile_json: NULL
# arrangement_json: {"seed": 123, "sections": [...]}  # Legacy format
```

---

### Test 8: Determinism with Seeds

**Test Case**: Same input + same seed = identical output

**Steps**:

**Generation 1**:
```bash
curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 30,
    "style_text_input": "ATL style, bouncy",
    "use_ai_parsing": true,
    "seed": 42
  }'

# Save arrangement_id_1
# Download audio: curl <output_url> -o result1.wav
```

**Generation 2**:
```bash
curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 30,
    "style_text_input": "ATL style, bouncy",
    "use_ai_parsing": true,
    "seed": 42
  }'

# Save arrangement_id_2
# Download audio: curl <output_url> -o result2.wav
```

**Verification**:
```bash
# Compare audio files
diff result1.wav result2.wav
# Expected: Files are identical (exit code 0)

# Or check file hashes
md5sum result1.wav result2.wav
# Expected: Same hash
# a3b2c1d4e5f6... result1.wav
# a3b2c1d4e5f6... result2.wav

# Compare StyleProfiles
sqlite3 looparchitect.db "SELECT style_profile_json FROM arrangements WHERE id IN (<id1>, <id2>);"
# Expected: Both have same sections array (order and energy values)
```

**Expected Results**:
- ✅ Both arrangements have identical `resolved_params`
- ✅ Both have identical `sections` array
- ✅ Both WAV files are byte-for-byte identical
- ✅ Seed appears in both `style_profile_json` records

---

### Test 9: Invalid Input Handling

**Test Case**: Graceful handling of edge cases

#### 9.1: Empty Style Text
```bash
curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 30,
    "style_text_input": "",
    "use_ai_parsing": true
  }'

# Expected: 400 Bad Request
# Error: "style_text_input cannot be empty when use_ai_parsing is true"
```

#### 9.2: Exceeds Max Length (500 chars)
```bash
curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d "{
    \"loop_id\": 1,
    \"target_seconds\": 30,
    \"style_text_input\": \"$(python3 -c 'print("a" * 501)')\",
    \"use_ai_parsing\": true
  }"

# Expected: 422 Unprocessable Entity
# Error: "style_text_input exceeds maximum length of 500 characters"
```

#### 9.3: Invalid Loop ID
```bash
curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 99999,
    "target_seconds": 30,
    "style_text_input": "ATL style",
    "use_ai_parsing": true
  }'

# Expected: 404 Not Found
# Error: "Loop with ID 99999 not found"
```

#### 9.4: LLM Enabled But No API Key
```bash
# Remove API key from environment
unset OPENAI_API_KEY
# Restart backend

curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 30,
    "style_text_input": "ATL style",
    "use_ai_parsing": true
  }'

# Expected: 400 Bad Request
# Error: "LLM style parsing not configured. Set OPENAI_API_KEY."
```

**Expected Results**:
- ✅ All invalid inputs return appropriate HTTP status codes
- ✅ Error messages are clear and actionable
- ✅ No 500 Internal Server Errors
- ✅ Backend logs contain warnings, not exceptions

---

### Test 10: Performance & Latency

**Test Case**: Verify acceptable response times

**Metrics to Track**:
- Generate endpoint initial response: < 5 seconds
- LLM parsing time: < 30 seconds (95th percentile)
- Total arrangement generation: < 60 seconds (for 60s audio)

**Steps**:
```bash
# Test with timing
time curl -X POST http://localhost:8000/arrangements/generate \
  -H "Content-Type: application/json" \
  -d '{
    "loop_id": 1,
    "target_seconds": 60,
    "style_text_input": "Southside type, aggressive, beat switch after hook",
    "use_ai_parsing": true
  }'

# Expected: < 5 seconds (should return 202 immediately)

# Monitor full generation time
arrangement_id=<from_response>
start_time=$(date +%s)

while true; do
  status=$(curl -s http://localhost:8000/arrangements/$arrangement_id | jq -r '.status')
  if [ "$status" = "done" ] || [ "$status" = "failed" ]; then
    break
  fi
  sleep 2
done

end_time=$(date +%s)
duration=$((end_time - start_time))
echo "Total generation time: ${duration}s"

# Expected: < 60 seconds for 60s audio
```

**Backend Logs**:
```bash
# Check for timing logs
tail -f logs/uvicorn.log | grep "timing"

# Expected logs:
# INFO: LLM parsing completed in 3.2s
# INFO: Arrangement rendering completed in 12.5s
# INFO: S3 upload completed in 1.8s
# INFO: Total generation time: 17.5s
```

**Expected Results**:
- ✅ Generate endpoint responds in < 5s
- ✅ LLM parsing completes in < 30s (p95)
- ✅ Total generation < 60s for 60s audio
- ✅ No timeouts or hanging requests

---

### Test 11: Railway Production Deployment

**Test Case**: Verify feature works in Railway production environment

**Prerequisites**:
- Railway service deployed with latest code
- Environment variables set in Railway dashboard:
  ```
  OPENAI_API_KEY=sk-proj-...
  FEATURE_LLM_STYLE_PARSING=true
  OPENAI_MODEL=gpt-4
  STORAGE_BACKEND=s3
  AWS_S3_BUCKET=looparchitect-prod
  ```

**Steps**:
1. Get Railway URL: `https://web-production-<hash>.up.railway.app`
2. Test health endpoint:
   ```bash
   curl https://web-production-<hash>.up.railway.app/health
   # Expected: {"status": "healthy"}
   ```
3. Upload test loop:
   ```bash
   curl -X POST https://web-production-<hash>.up.railway.app/loops/upload \
     -F "file=@test_loop.wav"
   ```
4. Generate with LLM:
   ```bash
   curl -X POST https://web-production-<hash>.up.railway.app/arrangements/generate \
     -H "Content-Type: application/json" \
     -d '{
       "loop_id": 1,
       "target_seconds": 30,
       "style_text_input": "Southside type, aggressive",
       "use_ai_parsing": true
     }'
   ```
5. Check Railway logs:
   ```bash
   railway logs
   # Expected: No errors, see "LLM parsing completed" logs
   ```
6. Verify S3 upload:
   ```bash
   aws s3 ls s3://looparchitect-prod/arrangements/
   # Expected: See new .wav files
   ```

**Expected Results**:
- ✅ All endpoints respond successfully
- ✅ LLM parsing works with production API key
- ✅ Files uploaded to S3 correctly
- ✅ Presigned URLs work and expire after 1 hour
- ✅ Database migrations applied successfully
- ✅ No 500 errors in Railway logs
- ✅ Frontend can connect and use LLM features

---

## Troubleshooting Guide

### Issue: "LLM style parsing not configured"

**Symptoms**:
- 400 error when trying to use AI parsing
- Error message: "LLM style parsing not configured. Set OPENAI_API_KEY."

**Diagnosis**:
```bash
# Check environment variables
echo $OPENAI_API_KEY
echo $FEATURE_LLM_STYLE_PARSING

# Check backend startup logs
tail -f logs/uvicorn.log | grep "FEATURE_LLM_STYLE_PARSING"
```

**Solution**:
1. Set `OPENAI_API_KEY` in `.env` file
2. Set `FEATURE_LLM_STYLE_PARSING=true`
3. Restart backend: `./dev.ps1` or `uvicorn main:app --reload`

---

### Issue: "Authentication failed with OpenAI API"

**Symptoms**:
- Request returns 400 or 500 error
- Backend logs show: "AuthenticationError: Invalid API key"

**Diagnosis**:
```bash
# Test API key directly
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# Expected: List of models
# If error: API key is invalid
```

**Solution**:
1. Verify API key is correct (starts with `sk-proj-` or `sk-`)
2. Check API key has sufficient credits
3. Verify API key has access to specified model (gpt-4)
4. Replace with new key if expired

---

### Issue: Arrangements stuck in "processing" state

**Symptoms**:
- Arrangement status never changes to "done"
- Progress bar stuck at 0% or partial value

**Diagnosis**:
```bash
# Check backend logs for worker errors
tail -f logs/uvicorn.log | grep "arrangement_job"

# Check database
sqlite3 looparchitect.db "SELECT id, status, error_message FROM arrangements WHERE status = 'processing';"
```

**Common Causes**:
1. Worker crashed (check for exceptions in logs)
2. S3 upload failed (check AWS credentials)
3. Audio synthesis error (check loop file exists)

**Solution**:
1. Check error_message in database
2. Restart backend to re-trigger worker
3. Manually mark failed: `UPDATE arrangements SET status='failed' WHERE id=<id>;`
4. Debug specific error from logs

---

### Issue: Generated audio is silent or corrupted

**Symptoms**:
- WAV file downloads but has no audio
- Audio player shows waveform but no sound
- File size is smaller than expected

**Diagnosis**:
```bash
# Check file metadata
ffprobe result.wav

# Expected output:
# Duration: 00:00:30.00
# Stream #0:0: Audio: pcm_s16le, 44100 Hz, stereo, s16, 1411 kb/s

# Listen manually
ffplay result.wav
```

**Common Causes**:
1. Loop audio is corrupted/invalid
2. Audio synthesis module errors
3. WAV export failed

**Solution**:
1. Re-upload loop with valid WAV file
2. Check backend logs for audio synthesis errors
3. Test with known-good loop file

---

### Issue: StyleProfile not saved to database

**Symptoms**:
- `style_profile_json` column is NULL
- Worker falls back to legacy `arrangement_json`

**Diagnosis**:
```sql
SELECT id, ai_parsing_used, style_profile_json 
FROM arrangements 
WHERE id = <id>;

-- Expected: ai_parsing_used=1, style_profile_json='{"intent": ...}'
-- Actual: ai_parsing_used=0, style_profile_json=NULL
```

**Common Causes**:
1. LLM parsing failed silently
2. Serialization error
3. Database migration not applied

**Solution**:
1. Check backend logs for parsing errors
2. Verify migration applied: `alembic current`
3. Check `FEATURE_LLM_STYLE_PARSING` is true
4. Test LLM parsing directly:
   ```python
   from app.services.llm_style_parser import llm_style_parser
   profile = await llm_style_parser.parse_style_intent(...)
   print(profile.model_dump_json())
   ```

---

## Success Checklist

After completing all tests, verify:

- [ ] Test 1: Basic natural language input works
- [ ] Test 2: Beat switch transitions appear in audio
- [ ] Test 3: Manual slider overrides are applied
- [ ] Test 4: Producer names map to correct archetypes
- [ ] Test 5: Variations system generates multiple outputs
- [ ] Test 6: Fallback parser works when LLM fails
- [ ] Test 7: Legacy preset mode still functional
- [ ] Test 8: Determinism: same seed = identical output
- [ ] Test 9: All invalid inputs handled gracefully
- [ ] Test 10: Performance meets targets (< 5s endpoint, < 60s total)
- [ ] Test 11: Railway production deployment successful
- [ ] All backend logs show no errors
- [ ] Database has `style_profile_json` populated correctly
- [ ] S3 uploads work correctly (if using S3)
- [ ] Frontend UI is responsive and intuitive
- [ ] Audio quality matches expectations
- [ ] 48 existing tests still pass: `pytest tests/`

---

## Regression Testing

Before deploying to production, run full test suite:

```bash
# Backend tests
cd looparchitect-backend-api
pytest tests/ -v

# Expected: 48+ tests passing (includes new LLM tests)

# Frontend build
cd looparchitect-frontend
npm run build

# Expected: No TypeScript errors

# Manual smoke tests
# Follow Tests 1-11 above
```

---

## Performance Benchmarks

Target metrics for production:

| Metric | Target | Measured | Status |
|--------|--------|----------|--------|
| Generate endpoint response | < 5s | ___s | ⬜ |
| LLM parsing time (p50) | < 10s | ___s | ⬜ |
| LLM parsing time (p95) | < 30s | ___s | ⬜ |
| Total generation (30s audio) | < 30s | ___s | ⬜ |
| Total generation (60s audio) | < 60s | ___s | ⬜ |
| Database query time | < 100ms | ___ms | ⬜ |
| S3 upload time (2MB file) | < 5s | ___s | ⬜ |

Fill in "Measured" column during testing. All metrics should meet targets before production deploy.

---

## Post-Deployment Monitoring

After Railway deployment, monitor for 24 hours:

1. **Error Rate**: Should be < 1% of requests
   ```bash
   railway logs | grep ERROR | wc -l
   ```

2. **LLM Costs**: Monitor OpenAI dashboard for usage
   - Expected: ~$0.01-0.05 per generation
   - Alert if daily spend > $50

3. **Response Times**: Check Railway metrics dashboard
   - p50 latency < 5s
   - p95 latency < 30s

4. **User Feedback**: Check for bug reports
   - Audio quality issues
   - Incorrect style parsing
   - UI/UX confusion

5. **Database Growth**: Monitor arrangements table size
   ```sql
   SELECT COUNT(*), 
          SUM(LENGTH(style_profile_json)) / 1024 / 1024 AS profile_mb
   FROM arrangements;
   ```

---

**End of Smoke Testing Guide**

This guide should be executed in full before merging Style Engine V2 to production. Any test failures should be documented as GitHub issues and resolved before deployment.

**Estimated Testing Time**: 3-4 hours for complete manual smoke test

**Recommended Testing Schedule**:
- Day 1: Tests 1-6 (core functionality)
- Day 2: Tests 7-10 (edge cases and performance)
- Day 3: Test 11 (production deployment)
- Day 4: 24-hour monitoring period
