#!/usr/bin/env pwsh
# Run frontend generate visualization/dev flow from backend workspace

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $scriptDir "..\looparchitect-frontend"
$frontendDir = Resolve-Path $frontendDir -ErrorAction SilentlyContinue

if (-not $frontendDir) {
    Write-Host "❌ Frontend directory not found at ..\looparchitect-frontend" -ForegroundColor Red
    exit 1
}

$packageJson = Join-Path $frontendDir.Path "package.json"
if (-not (Test-Path $packageJson)) {
    Write-Host "❌ package.json not found in frontend directory: $($frontendDir.Path)" -ForegroundColor Red
    exit 1
}

if (-not $env:BACKEND_ORIGIN) {
    $env:BACKEND_ORIGIN = "http://localhost:8000"
}

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Starting generatevis from backend" -ForegroundColor Yellow
Write-Host "Frontend: $($frontendDir.Path)" -ForegroundColor Gray
Write-Host "BACKEND_ORIGIN: $env:BACKEND_ORIGIN" -ForegroundColor Gray
Write-Host "=====================================" -ForegroundColor Cyan

npm --prefix $frontendDir.Path run generatevis
exit $LASTEXITCODE
