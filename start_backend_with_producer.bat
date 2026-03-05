@echo off
REM Start backend with FEATURE_PRODUCER_ENGINE enabled
setlocal enabledelayedexpansion

cd /d %~dp0

REM Set the feature flag
set FEATURE_PRODUCER_ENGINE=true

REM Print confirmation
echo.
echo ============================================
echo Starting LoopArchitect Backend
echo FEATURE_PRODUCER_ENGINE=%FEATURE_PRODUCER_ENGINE%
echo ============================================
echo.

REM Run uvicorn
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info

pause
