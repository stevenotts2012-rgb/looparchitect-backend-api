#!/usr/bin/env pwsh
# LoopArchitect local development dependency checks (Windows)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "LoopArchitect Local Dev Setup Check" -ForegroundColor Cyan
Write-Host "===================================" -ForegroundColor Cyan

$hasIssues = $false

# --- FFmpeg check ---
$ffmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpegCmd) {
    Write-Host "[OK] FFmpeg detected: $($ffmpegCmd.Source)" -ForegroundColor Green
} else {
    $hasIssues = $true
    Write-Host "[MISSING] FFmpeg not found in PATH" -ForegroundColor Red
    Write-Host "  Install options:" -ForegroundColor Yellow
    Write-Host "  1) winget install --id Gyan.FFmpeg -e" -ForegroundColor Gray
    Write-Host "  2) Download: https://www.gyan.dev/ffmpeg/builds/" -ForegroundColor Gray
}

# --- Redis installation check ---
$redisServerCmd = Get-Command redis-server -ErrorAction SilentlyContinue
$redisCliCmd = Get-Command redis-cli -ErrorAction SilentlyContinue

if ($redisServerCmd -or $redisCliCmd) {
    $redisPath = if ($redisServerCmd) { $redisServerCmd.Source } else { $redisCliCmd.Source }
    Write-Host "[OK] Redis binaries detected: $redisPath" -ForegroundColor Green
} else {
    $hasIssues = $true
    Write-Host "[MISSING] Redis binary not found (redis-server/redis-cli)" -ForegroundColor Red
    Write-Host "  Install options:" -ForegroundColor Yellow
    Write-Host "  1) Docker: docker run --name looparchitect-redis -p 6379:6379 -d redis:7" -ForegroundColor Gray
    Write-Host "  2) Memurai (Windows Redis-compatible): https://www.memurai.com/get-memurai" -ForegroundColor Gray
    Write-Host "  3) WSL2 + Redis: sudo apt install redis-server" -ForegroundColor Gray
}

# --- Redis runtime check (non-blocking) ---
$redisListening = Get-NetTCPConnection -LocalPort 6379 -State Listen -ErrorAction SilentlyContinue
if ($redisListening) {
    Write-Host "[OK] Redis appears to be running on localhost:6379" -ForegroundColor Green
} else {
    Write-Host "[WARN] Redis is not currently listening on localhost:6379" -ForegroundColor Yellow
    Write-Host "  Dev mode can still run without Redis for non-queue routes." -ForegroundColor Gray
}

Write-Host ""
if ($hasIssues) {
    Write-Host "[WARN] Some optional local dependencies are missing." -ForegroundColor Yellow
    Write-Host "  You can still start API dev mode, but queue/audio features may be limited." -ForegroundColor Gray
} else {
    Write-Host "[OK] Local dependency checks passed." -ForegroundColor Green
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  Backend: .\\dev.ps1" -ForegroundColor White
Write-Host "  Frontend: cd ..\\looparchitect-frontend; npm run dev" -ForegroundColor White
