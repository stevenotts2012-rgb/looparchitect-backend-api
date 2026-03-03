# Production Rollback Plan

## Quick Reference: When to Rollback

### 🔴 CRITICAL - Rollback Immediately
- ❌ API service crash (continuous restart loops)
- ❌ Database connection lost
- ❌ All endpoints returning 500 errors
- ❌ Memory leak (constantly increasing usage)
- ❌ Data corruption detected

### 🟡 MAJOR - Consider Rollback
- ⚠️ Specific feature broken in production
- ⚠️ Performance degraded significantly
- ⚠️ Authentication/authorization broken
- ⚠️ Critical business logic failing

### 🟢 MINOR - Monitor, Don't Rollback
- ℹ️ Single endpoint issue fixable with patch
- ℹ️ Non-critical feature broken
- ℹ️ Warning messages (operating normally)

---

## Rollback Decision Tree

```
Is production completely down?
├─ YES → CRITICAL - Use Option 1 (Immediate Revert)
│
Is a specific feature broken?
├─ YES → 
│  ├─ Can be fixed in <30 min? → Use Option 2 (Targeted Fix)
│  └─ Takes >30 min? → Use Option 1 (Immediate Revert)
│
Is performance degraded?
├─ YES → Use Option 3 (Staged Rollback)
│
Is service degraded but operational?
└─ WAIT → Monitor for 5 minutes, then decide
```

---

## Rollback Options

### ✅ Option 1: IMMEDIATE FULL REVERT (Fastest)
**Time to rollback:** 2-3 minutes  
**Data safety:** ✅ Safe (no data modified)  
**Best for:** Critical failures, complete outage

**Steps:**

1. **Revert to last stable commit:**
   ```bash
   cd looparchitect-backend-api
   git revert HEAD~13
   git push
   ```

2. **Why HEAD~13?**
   - Current HEAD: 3e97f2c (operations guide)
   - Last stable before deployment: 5aeae1e
   - 13 commits = 5d173e1 + 3e97f2c + ... back to 5aeae1e

3. **What this does:**
   - Creates a new commit that undoes the last 14 commits
   - Railway automatically detects the push
   - Builds and deploys previous version (2-5 min)
   - No data loss (only code reverted)

4. **Verify rollback:**
   ```bash
   git log --oneline -5
   # Should show a new commit with "Revert" message
   ```

5. **Monitor after:**
   - Check Railway deployment status
   - Test health endpoint: https://web-production-3afc5.up.railway.app/api/v1/health
   - Verify services starting normally

---

### ✅ Option 2: TARGETED FIX (If specific feature broken)
**Time:** 10-20 minutes  
**Data safety:** ✅ Safe  
**Best for:** Bug in specific endpoint, non-critical feature

**Steps:**

1. **Identify the issue:**
   - Which endpoint/feature is broken?
   - When did it break? (during which commit?)
   - What's the error message?

2. **Fix locally:**
   ```bash
   cd looparchitect-backend-api
   # Edit the problematic file
   # Run local tests to verify fix
   pytest tests/ -v
   ```

3. **Commit and push:**
   ```bash
   git add .
   git commit -m "fix: brief description of fix"
   git push
   ```

4. **Monitor deployment:**
   - Railway builds (2-3 min)
   - Services restart
   - Test the fixed endpoint

---

### ✅ Option 3: STAGED ROLLBACK (Cautious approach)
**Time:** 5-10 minutes  
**Data safety:** ✅ Safe  
**Best for:** Performance issues, need to test before full rollback

**Steps:**

1. **Stop the problematic service:**
   - Go to Railway dashboard
   - Select API service
   - Click "Stop"
   - Wait 10 seconds

2. **Choose a previous deployment:**
   - Go to API service → Deployments
   - Find the deployment marked "001_add_missing_loop_columns" (last stable)
   - Click "Redeploy"

3. **Monitor startup:**
   - Check logs for errors
   - Wait 30 seconds for startup
   - Test health endpoint

4. **Validate:**
   ```bash
   # From local machine
   curl https://web-production-3afc5.up.railway.app/api/v1/health
   ```

---

## Step-by-Step: Option 1 (Most Likely Scenario)

### Prerequisites
- Access to git command line
- Push permissions to GitHub repository

### Execute Rollback

**Step 1: Navigate to backend:**
```bash
cd C:\Users\steve\looparchitect-backend-api
```

**Step 2: Check current status:**
```bash
git log --oneline -3
# Should show current commits
# Example output:
# 3e97f2c docs: add operations quick...
# 5d173e1 docs: add comprehensive...
# 9400d37 fix: finalize backend compat...
```

**Step 3: Revert last 13 commits (reverts to 5aeae1e):**
```bash
git revert --no-edit HEAD~13
# Creates a revert commit automatically
```

**Step 4: Push to trigger rebuild:**
```bash
git push
```

**Step 5: Monitor the rollback:**
- Watch Railway deployment (2-5 minutes)
- Check service status in dashboard
- Services should show "Building" then "Success"

**Step 6: Verify it's working:**
Wait 2 minutes, then test:
```bash
# Test 1: Health check
Invoke-WebRequest "https://web-production-3afc5.up.railway.app/api/v1/health" -UseBasicParsing

# Test 2: Check logs
# Go to Railway → API → Logs
# Should see normal startup messages, no errors
```

---

## Post-Rollback Actions

### ✅ Immediate (After rollback completes)

1. **Verify all services running:**
   - [ ] Health endpoint responding
   - [ ] Frontend loads at main URL
   - [ ] Database connected (check logs)
   - [ ] No ERROR messages in logs

2. **Test critical paths:**
   - [ ] Can access API endpoints
   - [ ] Can upload a file
   - [ ] Can create a loop
   - [ ] Can view existing data

3. **Check for data issues:**
   - [ ] Existing loops still present
   - [ ] User data intact
   - [ ] Database not corrupted

### 📋 Follow-up (Within 1 hour)

1. **Document what went wrong:**
   - Which deploy caused the issue?
   - What was the specific failure?
   - Error messages or logs?

2. **Communicate status:**
   - Let users know service is restored
   - Estimate when fix will be ready
   - Provide status updates

3. **Plan the fix:**
   - Create a bug report
   - Identify root cause from logs
   - Plan the fix locally
   - Test thoroughly before re-deploying

### 🔄 Re-deployment (After fix verified)

```bash
# In looparchitect-backend-api directory:
git add .
git commit -m "fix: description of issue and fix"
git push
# Wait for Rails to rebuild (2-5 min)
# Test thoroughly before using in production
```

---

## Safety Checks Before Deployment

**Always verify locally before pushing:**

```bash
# 1. Run full test suite
pytest -q
# Must show: 133 passed

# 2. Check for syntax errors
python -c "from app.main import app; print('✓ App imports successfully')"

# 3. Start locally and test
python -m uvicorn app.main:app --reload

# 4. Test critical endpoints
# In another terminal:
# curl http://localhost:8000/api/v1/health
# curl http://localhost:8000/api/v1/loops
```

**Never push if:**
- ❌ Tests are failing locally
- ❌ Import errors in Python
- ❌ Uncommitted changes in critical files
- ❌ Haven't tested the changes

---

## Comparing Deploy Commits

### Safe baseline (last known stable):
**Commit: 5aeae1e**
- Message: "fix: defer RQ import for Windows-compatible test collection"
- This version has been running in production before
- All 133 tests pass
- No file locking or async issues

### Recent commits (from this session):
1. **59259ed** - Upload response + BPM (added float BPM support)
2. **0654887** - SQLite threading (added StaticPool)
3. **b2e0294** - Async render compatibility (restored schema defaults)
4. **fba4e98** - Loop update routes (PUT/PATCH behavior)
5. **9400d37** - Final compatibility (Windows paths, WAV decode)
6. **5d173e1** - Deployment final report (docs only)
7. **3e97f2c** - Operations guide (docs only)

**If rolling back:** Revert all 7 commits (or 14 from HEAD~13)

---

## Monitoring After Rollback

### 🟢 Green Light Indicators
- ✅ Health endpoint: 200 OK
- ✅ API responding to requests
- ✅ No ERROR in logs
- ✅ CPU usage normal (<50%)
- ✅ Memory stable (not growing)
- ✅ User reports: "It works!"

### 🟡 Yellow Light Indicators
- ⚠️ Occasional warnings in logs
- ⚠️ Slightly elevated CPU (50-75%)
- ⚠️ Response times slower than usual
- ⚠️ **Action:** Monitor for 5-10 minutes

### 🔴 Red Light Indicators (Rollback Failed)
- ❌ Health endpoint still timing out
- ❌ ERROR messages in logs
- ❌ Memory constantly growing
- ❌ Services crashing/restarting
- ❌ **Action:** Check railway.app dashboard, may need to:
  - Go back one more version
  - Manually stop/restart service
  - Contact Railway support

---

## Alternative: Hard Reset (Nuclear Option)

If normal rollback doesn't work:

```bash
# Find the stable commit
git log --oneline -20
# Find commit 5aeae1e in the list

# Hard reset to that point
git reset --hard 5aeae1e

# Force push (warning: overwrites history)
git push --force

# Railway will rebuild with the older version
```

**⚠️ Warning:** `--force` rewrites git history. Only use if normal rollback fails.

---

## Rollback Checklist

```
BEFORE ROLLBACK:
[ ] Confirmed service is actually broken (not just slow)
[ ] Checked logs for specific error messages
[ ] Attempted refresh (sometimes just a cache issue)
[ ] Verified local environment works (to confirm issue is production)

DURING ROLLBACK:
[ ] Executed git revert or git reset command
[ ] Pushed to GitHub
[ ] Watched Railway rebuild (don't interrupt!)
[ ] Waited full 2-5 minutes for startup

AFTER ROLLBACK:
[ ] Tested health endpoint
[ ] Checked logs for "Uvicorn running" message
[ ] Verified no ERROR in logs
[ ] Tested critical user workflow locally
[ ] Confirmed data still present/intact

FINAL VERIFICATION:
[ ] Production endpoints responding
[ ] Frontend loads without errors
[ ] User data visible and accessible
[ ] No ongoing service restarts
```

---

## Quick Contact Reference

**If you need help:**
- Local logs: Check `C:\Users\steve\looparchitect-backend-api` directory
- Production logs: Railway dashboard → API service → Logs
- Git history: `git log --oneline -20`
- Revert command: `git revert HEAD~13 && git push`

---

## Timeline Expectations

| Action | Time | Notes |
|--------|------|-------|
| Git revert command | <1 min | Local operation |
| Git push | 1-2 min | Upload to GitHub |
| Railway build | 2-3 min | Compiling dependencies |
| Service startup | 1-2 min | Initializing app |
| **Total time** | **5-8 min** | From decision to live |

---

## Testing After Rollback

Once rollback is complete and service responds:

```bash
# Test 1: Health check
curl https://web-production-3afc5.up.railway.app/api/v1/health
# Expected: {"status":"ok","message":"..."}

# Test 2: Loops list
curl https://web-production-3afc5.up.railway.app/api/v1/loops
# Expected: JSON array of loops

# Test 3: Frontend
# Visit: https://web-production-3afc5.up.railway.app
# Expected: LoopArchitect UI loads
```

---

## Never Needed? Keep This File

This rollback plan documents:
- ✅ How and when to rollback
- ✅ What each option does
- ✅ How to verify success
- ✅ What to check after rollback

**Save this file** in your documentation for future reference. The commands here will work for any future deployment.

---

**Status:** Ready to execute  
**Last Updated:** 2026-03-03  
**Rollback Time Estimate:** 5-8 minutes from decision to online
