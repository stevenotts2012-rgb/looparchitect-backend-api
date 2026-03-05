#!/usr/bin/env pwsh
<#
Enable Producer Engine Feature Flag and Start Validation

This script:
1. Sets FEATURE_PRODUCER_ENGINE=true
2. Starts the backend server
3. Provides instructions for API testing
#>

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   PRODUCER ENGINE VALIDATION SETUP                            ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Step 1: Enable feature flag
Write-Host "Step 1: Enabling FEATURE_PRODUCER_ENGINE..." -ForegroundColor Yellow
$env:FEATURE_PRODUCER_ENGINE = 'true'

# Verify it's set
$flagValue = [System.Environment]::GetEnvironmentVariable("FEATURE_PRODUCER_ENGINE")
if ($flagValue -eq 'true') {
    Write-Host "✅ Environment variable set in current session" -ForegroundColor Green
} else {
    Write-Host "⚠️  Environment variable not persisted" -ForegroundColor Yellow
    Write-Host "   (Will be lost when PowerShell closes)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Step 2: Backend status check..." -ForegroundColor Yellow

# Check if backend is running
$backendPid = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique

if ($backendPid) {
    Write-Host "✅ Backend is already running (PID: $backendPid)" -ForegroundColor Green
    Write-Host ""
    Write-Host "Since backend is running with old config, you need to:" -ForegroundColor Yellow
    Write-Host "  1. Stop the current process (it will be restarted)" -ForegroundColor Cyan
    Write-Host "  2. Start a new instance with the feature flag enabled" -ForegroundColor Cyan
    Write-Host ""
    
    $restart = Read-Host "Restart backend with FEATURE_PRODUCER_ENGINE=true? (y/n)"
    if ($restart -eq 'y') {
        Write-Host "Stopping backend process..." -ForegroundColor Yellow
        Stop-Process -Id $backendPid -Force
        Start-Sleep -Seconds 2
        Write-Host "✅ Backend stopped" -ForegroundColor Green
    }
} else {
    Write-Host "ℹ️  Backend is not currently running" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Step 3: Starting backend with FEATURE_PRODUCER_ENGINE=true..." -ForegroundColor Yellow
Write-Host ""

# Ensure we're in the right directory
Set-Location c:\Users\steve\looparchitect-backend-api

# Start backend
Write-Host "Launching: .\.venv\Scripts\python.exe main.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "Backend will be available at: http://localhost:8000" -ForegroundColor Cyan
Write-Host "API docs at: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server when done testing." -ForegroundColor Yellow
Write-Host ""

# Start backend
& .\.venv\Scripts\python.exe main.py

Write-Host ""
Write-Host "Backend stopped." -ForegroundColor Yellow
