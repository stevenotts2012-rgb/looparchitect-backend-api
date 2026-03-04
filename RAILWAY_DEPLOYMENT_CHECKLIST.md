# Railway Deployment Checklist - Producer Engine System

**Version:** 1.0  
**Date:** March 4, 2026  
**Status:** Ready for Deployment  
**Target Environment:** Railway.app  

## Pre-Deployment (48 hours before)

### Code Review & Approval ✓

- [ ] Review IMPLEMENTATION_REPORT.md
  - Architecture diagram understood
  - All 12 systems mapped to 6 modules
  - Data models complete
  - 40+ test cases cover all systems
  
- [ ] Review PRODUCER_ENGINE_ARCHITECTURE.md
  - Module specifications clear
  - Integration points validated
  - Performance characteristics acceptable
  - Error handling strategy approved

- [ ] Code review of 6 service modules
  - [ ] `app/services/producer_models.py` (240 lines, 14 dataclasses)
  - [ ] `app/services/producer_engine.py` (420 lines, main orchestrator)
  - [ ] `app/services/style_direction_engine.py` (280 lines, NLP parser)
  - [ ] `app/services/render_plan.py` (130 lines, conversion layer)
  - [ ] `app/services/arrangement_validator.py` (220 lines, validation rules)
  - [ ] `app/services/daw_export.py` (310 lines, export metadata)
  - No security vulnerabilities found
  - No breaking changes to existing code
  - All imports valid

- [ ] Code review of 2 data model changes
  - [ ] `app/models/arrangement.py` (2 new columns added)
  - [ ] Columns properly nullable
  - [ ] No migration conflicts

- [ ] Code review of API route enhancements
  - [ ] `app/routes/arrangements.py` (imports + 2 endpoints added)
  - [ ] New helper function `_generate_producer_arrangement()`
  - [ ] Backward compatibility confirmed
  - [ ] Existing /generate endpoint still works

- [ ] Frontend component review
  - [ ] `src/components/ProducerControls.tsx` (150 lines)
  - [ ] `src/components/ArrangementTimeline.tsx` (175 lines)
  - [ ] Tailwind styling complete
  - [ ] Props interfaces correct

- [ ] Test suite review
  - [ ] `tests/test_producer_system.py` (700+ lines, 40+ tests)
  - [ ] 8 test classes cover all systems
  - [ ] No external dependencies (pytest only)

**Sign-off:** [ ] Code review approved by team lead

### Local Testing (Development Machine)

- [ ] Run test suite locally
  ```bash
  cd c:\Users\steve\looparchitect-backend-api
  pytest tests/test_producer_system.py -v
  ```
  - Expected: All 40+ tests pass (green)
  - Time: ~3 minutes
  - Acceptable failure rate: 0%

- [ ] Run backend locally
  ```bash
  python main.py
  ```
  - Service starts without errors
  - No import errors
  - Port 8000 accessible

- [ ] Test POST /generate endpoint
  ```bash
  curl -X POST http://localhost:8000/api/v1/arrangements/generate \
    -H "Content-Type: application/json" \
    -d {'loop_id': 1, 'target_seconds': 120, 'style_text_input': 'Lil Baby trap'}
  ```
  - Status 202 (Accepted)
  - Response includes arrangement_id
  - producer_arrangement_json populated
  - render_plan_json populated

- [ ] Test GET /metadata endpoint
  ```bash
  curl http://localhost:8000/api/v1/arrangements/42/metadata
  ```
  - Status 200
  - Returns producer_arrangement
  - Returns render_plan
  - Returns validation_summary

- [ ] Test GET /daw-export endpoint
  ```bash
  curl http://localhost:8000/api/v1/arrangements/42/daw-export
  ```
  - Status 200
  - Returns export metadata
  - Returns supported_daws list
  - Returns stems and midi arrays

- [ ] Test database integrity
  ```bash
  sqlite3 dev.db "SELECT producer_arrangement_json FROM arrangements LIMIT 1;"
  ```
  - producer_arrangement_json is valid JSON
  - render_plan_json is valid JSON
  - Both are properly stored

- [ ] Test backward compatibility
  ```bash
  # Verify existing arrangements still load
  curl http://localhost:8000/api/v1/arrangements/1
  ```
  - No errors
  - Existing fields present
  - New fields optional (can be null)

**Sign-off:** [ ] All local tests pass

### Database Schema Preparation

- [ ] Generate Alembic migration
  ```bash
  alembic revision --autogenerate -m "add_producer_arrangement_fields"
  ```
  - Migration file created in `alembic/versions/`
  - Migration checks for existing columns (safe idempotent)
  - SQL verified for correctness

- [ ] Test migration locally
  ```bash
  alembic upgrade head
  ```
  - Migration applies without errors
  - Schema updated with 2 new columns
  - No data loss
  - Downgrade tested: `alembic downgrade -1`

- [ ] Verify migration reversibility
  ```bash
  alembic downgrade -1
  ```
  - Columns successfully removed
  - No orphaned data
  - `alembic upgrade head` still works

**Sign-off:** [ ] Migration tested and validated

### Dependency Check

- [ ] All imports exist
  ```bash
  python -c "from app.services.producer_models import ProducerArrangement"
  python -c "from app.services.producer_engine import ProducerEngine"
  python -c "from app.services.style_direction_engine import StyleDirectionEngine"
  python -c "from app.services.render_plan import RenderPlanGenerator"
  python -c "from app.services.arrangement_validator import ArrangementValidator"
  python -c "from app.services.daw_export import DAWExporter"
  ```
  - No ModuleNotFoundError
  - No ImportError

- [ ] No new external dependencies required
  - producer_engine.py uses only stdlib
  - style_direction_engine.py uses only stdlib
  - No new pip packages needed
  - requirements.txt unchanged

**Sign-off:** [ ] All imports valid, no new dependencies

### Git Preparation

- [ ] All changes committed
  ```bash
  git status  # Should show "working tree clean"
  ```

- [ ] Commit message follows convention
  ```
  feat: Add producer engine system with 12 subsystems
  
  - Add producer_models, producer_engine, style_direction_engine
  - Add render_plan, arrangement_validator, daw_export services
  - Add ProducerControls and ArrangementTimeline components
  - Add 40+ test cases for all systems
  - Update Arrangement model with producer_arrangement_json and render_plan_json
  - Add /metadata and /daw-export endpoints
  - Backward compatible (new fields optional)
  ```

- [ ] Create feature branch (if not already on main)
  ```bash
  git checkout main
  git pull origin main
  ```

- [ ] All uncommitted changes saved

**Sign-off:** [ ] Git ready for push

---

## Deployment to Staging (24 hours before production)

### Railway Configuration

- [ ] Log into Railway.app dashboard
  - Team project selected
  - Environment: staging-producer-test
  - Preview environment enabled

- [ ] Verify environment variables
  - DATABASE_URL = staging PostgreSQL
  - AWS_BUCKET = staging S3 bucket
  - LOG_LEVEL = DEBUG (for troubleshooting)
  - FEATURE_PRODUCER_ENGINE = true

- [ ] Create feature branch deployment
  ```bash
  git push origin feature/producer-engine
  ```
  - Railway auto-detects new branch
  - Builds staging image
  - Deploys to staging environment

- [ ] Wait for build completion
  - Expected time: 3-5 minutes
  - Build log checked for errors
  - "Deployment successful" message visible

**Sign-off:** [ ] Staging deployment complete

### Staging Validation (1-2 hours)

- [ ] Verify deployment health
  - [ ] Service is running (check Railway dashboard)
  - [ ] No error logs in production tab
  - [ ] HTTP endpoints responding

- [ ] Test health check endpoint
  ```bash
  curl https://staging-producer-test.railway.app/health
  ```
  - Status 200
  - Response: `{"status": "ok"}`

- [ ] Test arrangement generation on staging
  ```bash
  curl -X POST https://staging-producer-test.railway.app/api/v1/arrangements/generate \
    -H "Content-Type: application/json" \
    -d {'loop_id': 1, 'target_seconds': 120}
  ```
  - Status 202
  - Response includes arrangement_id

- [ ] Check database migration applied
  ```bash
  # Via database client or Railway console
  SELECT COUNT(*) FROM arrangement WHERE producer_arrangement_json IS NOT NULL;
  ```
  - Query executes without error
  - New columns exist

- [ ] Monitor logs for errors
  ```bash
  # In Railway dashboard, Logs tab
  ```
  - No ERROR or CRITICAL logs
  - INFO logs show arrangement generation working
  - No import errors
  - No database errors

- [ ] Performance check
  - Arrangement generation time < 500ms
  - API response time < 200ms
  - Database queries efficient

- [ ] Run smoke tests
  - [ ] Create test arrangement via API
  - [ ] Verify metadata endpoint
  - [ ] Verify daw-export endpoint
  - [ ] Check database for stored JSON

**Sign-off:** [ ] Staging validation passed (no issues found)

### Staging Issues (If Found)

- [ ] Log all issues found
  ```
  Issue 1: [Description]
  Severity: [Critical/High/Medium/Low]
  Resolution: [Fix applied and tested]
  
  Issue 2: ...
  ```

- [ ] For each issue: Fix locally and re-test
  ```bash
  # Fix code locally
  pytest tests/test_producer_system.py -v
  # Commit fix
  git add .
  git commit -m "fix: [Issue description]"
  git push origin feature/producer-engine
  # Wait for Railway to redeploy staging
  ```

- [ ] Repeat staging validation until 0 issues

- [ ] Document issues and resolutions for team

**Sign-off:** [ ] All staging issues resolved

---

## Production Deployment (Final Go/No-Go)

### Pre-Production Decision Gate

- [ ] Stakeholder approval
  - [ ] Engineering lead approves code
  - [ ] QA confirms staging tests passed
  - [ ] Product approves feature set
  
- [ ] Production readiness checklist
  - [ ] Database migration tested
  - [ ] Performance acceptable
  - [ ] Error handling validated
  - [ ] Rollback plan approved (see below)
  - [ ] Monitoring alerts configured
  - [ ] Team available for support (next 4 hours)

- [ ] Stakeholder sign-off: [ ] **GO for production deployment**

### Production Deployment Steps

**Step 1: Create production branch**
```bash
git checkout -b release/producer-engine-v1.0
git push origin release/producer-engine-v1.0
```

**Step 2: Monitor Railway build for production**
- In Railway dashboard, select main environment (production)
- Trigger deployment from `main` branch
  ```bash
  git checkout main
  git merge release/producer-engine-v1.0
  git push origin main
  ```
- Wait for build to complete (3-5 minutes)
- Check build logs for errors

**Step 3: Database migration on production**
Ensure migration runs before code takes effect:
```bash
# Via Railway console or pre-deployment script
alembic upgrade head
```
- Migration completes successfully
- 2 new columns added to Arrangement table
- No data loss
- Existing arrangements unaffected

**Step 4: Verify deployment**
```bash
curl https://looparchitect-api.railway.app/health
```
- Status 200
- Service healthy

**Step 5: Monitor logs (first 10 minutes)**
- Check Railway dashboard → Logs
- Watch for any ERROR, CRITICAL, or WARNING logs
- expected INFO logs:
  - "Service started"
  - "Database connected"
  - No import errors

**Step 6: Smoke test on production**
```bash
# Create test arrangement
curl -X POST https://looparchitect-api.railway.app/api/v1/arrangements/generate \
  -H "Content-Type: application/json" \
  -d {
    'loop_id': 1,
    'target_seconds': 120,
    'style_text_input': 'Drake R&B'
  }

# Get arrangement ID from response
# Check metadata endpoint
curl https://looparchitect-api.railway.app/api/v1/arrangements/[ID]/metadata

# Check daw-export endpoint
curl https://looparchitect-api.railway.app/api/v1/arrangements/[ID]/daw-export
```
- All 3 endpoints return 200
- Responses include expected fields
- No errors in logs

**Sign-off:** [ ] Production deployment complete and validated

---

## Post-Deployment (First 24 Hours)

### Monitoring & Alerting

- [ ] Set up monitoring alerts
  - [ ] HTTP 5xx error rate > 0.1% → Alert
  - [ ] API response time > 500ms → Alert
  - [ ] Database connection errors → Alert
  - [ ] Worker process errors → Alert

- [ ] Check production logs hourly
  - No unexpected ERROR logs
  - Arrangement generation working
  - No failed database operations

- [ ] Monitor database growth
  - producer_arrangement_json column populating
  - render_plan_json column populating
  - Database size growing as expected

- [ ] Track production metrics
  - [ ] Arrangement generation success rate (target: >99%)
  - [ ] Average generation time (target: <500ms)
  - [ ] API response time (target: <200ms)
  - [ ] Worker task completion rate (target: >99%)

### User Communication

- [ ] Announce new features to users
  - "Producer Engine system now live"
  - "New /metadata and /daw-export endpoints"
  - "Enhanced arrangement generation with natural language input"

- [ ] Monitor support channels for issues
  - Slack alerts enabled
  - Response plan for critical issues
  - Escalation path established

### Documentation Updates

- [ ] Update API documentation
  - Add GET /metadata endpoint
  - Add GET /daw-export endpoint
  - Add style_text_input parameter to POST /generate

- [ ] Update user-facing docs
  - "How to use producer engine"
  - "Supported genres and styles"
  - "DAW export configuration"

### Team Debrief (within 24 hours)

- [ ] Deployment retrospective
  - What went well
  - What could be improved
  - Issues encountered and resolutions

- [ ] Lessons learned documented
- [ ] Process improvements identified

**Sign-off:** [ ] Post-deployment monitoring complete

---

## Rollback Plan (If Issues)

### Trigger Conditions for Rollback

- [ ] > 1% error rate in production
- [ ] Database corruption detected
- [ ] Critical security vulnerability found
- [ ] Service unavailable for > 5 minutes
- [ ] Major performance regression

### Immediate Actions (If Rollback Needed)

1. **Stop new deployments**
   ```bash
   # In Railway dashboard
   # Pause new builds/deployments
   ```

2. **Revert to previous version**
   ```bash
   git revert HEAD
   git push origin main
   # Railway auto-deploys previous working version
   ```

3. **Verify rollback**
   ```bash
   curl https://looparchitect-api.railway.app/health
   ```
   - Should return healthy status
   - Should be running previous code version

4. **Check database**
   - Existing arrangements still accessible
   - No data loss
   - Migration remains applied (don't downgrade)

5. **Notify team**
   - Rollback completed
   - Cause of issue identified
   - Plan for fix discussed

### Post-Rollback Investigation

- [ ] Identify root cause
- [ ] Fix issue locally
- [ ] Re-test thoroughly
- [ ] Plan re-deployment for next day

---

## Success Criteria

### Deployment Success = All of:

✓ All 40+ tests pass locally  
✓ Staging environment stable for 2+ hours  
✓ Production endpoints responding 200  
✓ Database migration applied successfully  
✓ Health check returning ok  
✓ No ERROR logs in first 1 hour  
✓ Arrangement generation working  
✓ Existing arrangements unaffected  
✓ /metadata endpoint returning data  
✓ /daw-export endpoint returning data  
✓ User-facing features working  
✓ Performance within acceptable range  
✓ Team confident in production stability  

### Success Metrics (Post-Deployment)

- **Availability:** 99.9% (max 43 seconds downtime / month)
- **Latency:** p95 < 200ms, p99 < 500ms
- **Error Rate:** < 0.1% 5xx errors
- **Worker Success:** > 99% task completion
- **Database:** No corruption, clean backups

---

## Troubleshooting Guide

### Issue: Import errors on deployment

**Symptoms:** 
- ModuleNotFoundError in logs
- Service fails to start

**Solution:**
1. Check Python path in Railway
2. Verify all service files exist
3. Re-verify requirements.txt
4. Redeploy from source

### Issue: Database migration fails

**Symptoms:**
- Migration timeout
- Schema mismatch errors
- "Column already exists" error

**Solution:**
1. Check migration file syntax
2. Ensure idempotent migration (check if column exists first)
3. Manual review of Alembic migration
4. If migration stuck: Recover from backup

### Issue: API returns 500 on /generate

**Symptoms:**
- Status 500 errors
- "ProducerEngine initialization failed"

**Solution:**
1. Check logs for specific error
2. Verify StyleDirectionEngine initialized
3. Verify all service modules imported
4. Restart service in Railway

### Issue: Arrangement validation fails consistently

**Symptoms:**
- All generated arrangements marked invalid
- Validator errors about sections or energy

**Solution:**
1. Check validator rule logic
2. Verify section generation in ProducerEngine
3. Adjust validation thresholds if needed
4. Test with simple arrangement (30s, trap genre)

---

## Rollback Checklist (If Needed)

- [ ] Decide: Rollback necessary?
- [ ] Alert team
- [ ] Execute rollback steps
- [ ] Verify previous version running
- [ ] Confirm health indicators green
- [ ] Update status page
- [ ] Schedule post-mortem
- [ ] Close incident

---

## Final Checklist

Before clicking "Deploy" in Railway:

- [ ] All local tests pass
- [ ] Staging environment validated
- [ ] Database migration tested
- [ ] Team lead approval obtained
- [ ] Rollback plan reviewed
- [ ] Monitoring alerts configured
- [ ] Documentation updated
- [ ] Support team notified
- [ ] Health check endpoint verified

**Final Approval:** [ ] Team lead sign-off

**Deployment Date/Time:** [To be filled]  
**Deployed By:** [Name]  
**Reviewed By:** [Name]  

---

**End of Railway Deployment Checklist**

This document should be printed and used as a physical checklist during deployment. Mark each item as completed. Keep this record for audit and process improvement purposes.

---

## Quick Reference

### Critical Commands
```bash
# Test locally
pytest tests/test_producer_system.py -v

# Deploy to main
git checkout main
git merge release/producer-engine-v1.0
git push origin main

# Rollback (if needed)
git revert HEAD
git push origin main
```

### Critical Endpoints
- Health: `GET /health`
- Generate: `POST /api/v1/arrangements/generate`
- Metadata: `GET /api/v1/arrangements/{id}/metadata`
- DAW Export: `GET /api/v1/arrangements/{id}/daw-export`

### Emergency Contacts
- Engineering Lead: [Name/Phone]
- DevOps: [Name/Phone]
- On-Call: [Name/Phone]

---

**Document Version:** 1.0  
**Last Updated:** March 4, 2026  
**Status:** Ready for Use
