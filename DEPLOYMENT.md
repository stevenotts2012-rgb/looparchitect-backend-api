# Deployment Workflow Checklist

This document outlines the deployment process for the LoopArchitect FastAPI backend API.

## Running Tests

The project ships with a minimal smoke-test suite that exercises the main API endpoints
using an in-process SQLite database (no real server required).

### Install test dependencies

```bash
pip install -r requirements.txt
```

### Run smoke tests

```bash
pytest tests/test_smoke.py -v
```

Expected output: all 15 tests pass.

### What the tests cover

| Test | Endpoint |
|------|----------|
| `test_health` | `GET /api/v1/health` |
| `test_status` | `GET /api/v1/status` |
| `test_create_loop` | `POST /api/v1/loops` |
| `test_list_loops` | `GET /api/v1/loops` |
| `test_get_loop_not_found` | `GET /api/v1/loops/{id}` (404) |
| `test_upload_audio` | `POST /api/v1/loops/upload` |
| `test_upload_file_only` | `POST /api/v1/upload` |
| `test_upload_invalid_mime` | `POST /api/v1/loops/upload` (400) |
| `test_create_loop_with_file_success` | `POST /api/v1/loops/with-file` ✅ primary fix |
| `test_create_loop_with_file_invalid_json` | `POST /api/v1/loops/with-file` (422) |
| `test_create_loop_with_file_missing_required_field` | `POST /api/v1/loops/with-file` (422) |
| `test_create_loop_with_file_invalid_mime` | `POST /api/v1/loops/with-file` (400) |
| `test_arrange_loop` | `POST /api/v1/loops/{id}/arrange` |
| `test_arrange_endpoint` | `POST /api/v1/arrange/{id}` |
| `test_delete_loop` | `DELETE /api/v1/loops/{id}` |

---

## Verifying POST /api/v1/loops/with-file in Swagger UI

The primary bug (422 "Input should be a valid dictionary") has been fixed.
The endpoint now accepts `loop_in` as a **JSON string** form field.

To test in Swagger UI at `https://<render-url>/docs`:

1. Open `POST /api/v1/loops/with-file` → click **Try it out**
2. In the **loop_in** field, enter a JSON string such as:
   ```
   {"name": "My Loop", "tempo": 140, "key": "C", "genre": "Trap"}
   ```
3. Upload a WAV or MP3 file in the **file** field
4. Click **Execute** — you should receive a **201 Created** response

---

## Pre-Deployment Checklist
- [ ] Environment variables are documented in `.env.example` (if new variables added)
- [ ] Dependencies are updated in `requirements.txt` (if new packages added)

## Deployment Steps

### 1. Stage Files

```bash
git add .
```

**What this does:** Stages all modified and new files for commit.

**Verify staging:**
```bash
git status
```

### 2. Commit Changes

```bash
git commit -m "TYPE: Description of changes"
```

#### Recommended Commit Message Format

Follow this format for clear, semantic commits:

```
TYPE: Brief description (50 chars max)

Optional longer explanation (wrap at 72 chars)
- Bullet point for additional context
- Another related change
```

**Commit Types:**
- `feat:` - New feature
- `fix:` - Bug fix
- `refactor:` - Code refactoring without feature changes
- `docs:` - Documentation updates
- `test:` - Test additions or modifications
- `chore:` - Dependency updates, configuration changes
- `perf:` - Performance improvements

**Example Commits:**
```bash
git commit -m "feat: Add loop_id support to arrange endpoint"
git commit -m "fix: DATABASE_URL environment variable handling"
git commit -m "refactor: Update loops upload endpoint with db persistence"
git commit -m "chore: Add python-dotenv configuration"
```

### 3. Push to GitHub

```bash
git push origin main
```

**Verify the push:**
- Check GitHub repository for new commits
- Confirm branch is up-to-date with remote

### 4. Trigger Render Deployment

**Automatic Deployment (Recommended):**
- Render is configured to auto-deploy when changes are pushed to `main`
- No manual action required
- Monitor deployment status in Render Dashboard: https://dashboard.render.com

**Manual Deployment (If Needed):**
1. Go to Render Dashboard
2. Select "looparchitect-backend-api" service
3. Click "Deploy latest commit" or "Redeploy"
4. Wait for deployment to complete (typically 2-5 minutes)
5. Verify API health at: `https://<render-url>/api/v1/health`

## Deployment Verification

After deployment, verify the application is running:

```bash
# Check API health
curl https://<render-url>/api/v1/health

# Check database connection
curl https://<render-url>/api/v1/db-health

# View recent logs (in Render Dashboard)
# Deployment → Logs tab
```

## Rollback Procedure

If deployment fails or introduces issues:

1. **Identify the problematic commit:**
   ```bash
   git log --oneline -n 5
   ```

2. **Revert to previous commit:**
   ```bash
   git revert <commit-hash>
   git push origin main
   ```

3. **Monitor Render deployment** for the revert

4. **Investigate the issue** before pushing again

## Environment Variables

**Production (Render):**
- Configured in Render Dashboard → Environment
- `DATABASE_URL` - PostgreSQL connection string
- Other required variables as needed

**Local Development (.env):**
```
DATABASE_URL=sqlite:///./test.db
```

## Useful Git Commands

```bash
# View staged changes
git diff --staged

# View all local changes
git diff

# View commit history
git log --oneline

# Undo last commit (keep changes)
git reset --soft HEAD~1

# View branch status
git status
```

## Common Issues

### Push Rejected
```bash
# Sync with remote before pushing
git pull origin main
git push origin main
```

### Render Deployment Failed
1. Check Render logs for error details
2. Verify environment variables are set
3. Check `requirements.txt` for dependency issues
4. Consider reverting to last known good commit

### Database Connection Issues
- Verify `DATABASE_URL` is correctly set in Render environment
- Check PostgreSQL service availability
- Review migration status (if applicable)

## Resources

- [Render Docs](https://render.com/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Git Best Practices](https://github.com/git-tips/tips)
- [SQLAlchemy Docs](https://docs.sqlalchemy.org/)

---

**Last Updated:** February 22, 2026
