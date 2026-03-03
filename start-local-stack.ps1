param(
    [switch]$DryRun
)

Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "Starting LoopArchitect Local Stack" -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

$backendRoot = $PSScriptRoot
$workspaceRoot = Split-Path -Parent $backendRoot
$frontendRoot = Join-Path $workspaceRoot "looparchitect-frontend"

if (-not (Test-Path $frontendRoot)) {
    Write-Host "❌ Frontend folder not found: $frontendRoot" -ForegroundColor Red
    exit 1
}

$backendPython = Join-Path $backendRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $backendPython)) {
    Write-Host "❌ Backend Python not found: $backendPython" -ForegroundColor Red
    Write-Host "   Create venv first: python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

# Clear stale backend listener on 8000
$backendPids = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

if ($backendPids) {
    Write-Host "Stopping stale backend process(es) on port 8000..." -ForegroundColor Yellow
    foreach ($processId in $backendPids) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

$backendCommand = "Set-Location '$backendRoot'; & '$backendPython' -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info"
$frontendCommand = "Set-Location '$frontendRoot'; npm run dev:stable"

Write-Host "Backend command:" -ForegroundColor Gray
Write-Host "  $backendCommand" -ForegroundColor Gray
Write-Host "Frontend command:" -ForegroundColor Gray
Write-Host "  $frontendCommand" -ForegroundColor Gray
Write-Host ""

if ($DryRun) {
    Write-Host "✅ Dry run complete (no terminals launched)." -ForegroundColor Green
    exit 0
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCommand
Start-Sleep -Seconds 1
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCommand

Write-Host "✅ Local stack launch started." -ForegroundColor Green
Write-Host "   Backend:  http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "   Frontend: http://localhost:3001" -ForegroundColor Green
Write-Host ""
Write-Host "Tip: use Ctrl+C in each opened terminal to stop services." -ForegroundColor Yellow
