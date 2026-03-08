param(
    [switch]$BackendOnly
)

$ErrorActionPreference = "Stop"

Write-Host "LoopArchitect Full-Stack Dev Startup" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendRoot = Join-Path (Split-Path -Parent $backendRoot) "looparchitect-frontend"
$backendPython = Join-Path $backendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $backendPython)) {
    Write-Host "ERROR: Backend venv python not found: $backendPython" -ForegroundColor Red
    Write-Host "Create it first: python -m venv .venv (inside backend)" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $frontendRoot)) {
    Write-Host "ERROR: Frontend folder not found: $frontendRoot" -ForegroundColor Red
    exit 1
}

Set-Location $backendRoot

function Stop-Ports {
    param([int[]]$Ports)

    $conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in $Ports }

    if ($conns) {
        $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($processId in $pids) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
    }
}

Write-Host "Cleaning stale listeners on 8000 and 3000-3005..." -ForegroundColor Yellow
Stop-Ports -Ports @(8000, 3000, 3001, 3002, 3003, 3004, 3005)
Write-Host "Port cleanup complete" -ForegroundColor Green
Write-Host ""

$ffmpegBin = "C:\Users\steve\Desktop\ffmpeg-8.0.1-essentials_build\ffmpeg-8.0.1-essentials_build\bin"
$env:FEATURE_PRODUCER_ENGINE = "true"

if (Test-Path $ffmpegBin) {
    if (-not ($env:Path -split ';' | Where-Object { $_ -eq $ffmpegBin })) {
        $env:Path = "$env:Path;$ffmpegBin"
    }
    Write-Host "FFmpeg path configured" -ForegroundColor Green
} else {
    Write-Host "WARNING: FFmpeg path not found at expected location:" -ForegroundColor Yellow
    Write-Host "  $ffmpegBin" -ForegroundColor DarkYellow
}

if (-not $BackendOnly) {
    Write-Host "Starting frontend in separate terminal..." -ForegroundColor Yellow
    $frontendCmd = "Set-Location '$frontendRoot'; npm run dev"
    Start-Process powershell -ArgumentList @("-NoExit", "-Command", $frontendCmd) | Out-Null
    Start-Sleep -Seconds 2
}

Write-Host "" 
Write-Host "Frontend: http://localhost:3000" -ForegroundColor White
Write-Host "Backend:  http://127.0.0.1:8000" -ForegroundColor White
Write-Host "Docs:     http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host ""

Write-Host "Starting backend in this terminal..." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop backend" -ForegroundColor Gray
& $backendPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
