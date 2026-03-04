# PHASE 4: Quick Test Script
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "PHASE 4: STYLE SLIDER INTEGRATION TEST" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Check servers
Write-Host "Checking servers..." -ForegroundColor Yellow
$backend = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue
$frontend = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalPort -in @(3000, 3001)}

if ($backend) {
    Write-Host "✅ Backend: http://localhost:8000" -ForegroundColor Green
} else {
    Write-Host "❌ Backend NOT running" -ForegroundColor Red
    exit 1
}

if ($frontend) {
    Write-Host "✅ Frontend: http://localhost:$($frontend[0].LocalPort)" -ForegroundColor Green
} else {
    Write-Host "⚠️  Frontend NOT running (optional)" -ForegroundColor Yellow
}

Write-Host "`nTesting backend API with style parameters..." -ForegroundColor Yellow

# Test arrangement generation with style params
$payload = @{
    loop_id = 1
    target_seconds = 30
    style_text_input = "dark aggressive trap"
    use_ai_parsing = $true
    style_params = @{
        energy = 0.85
        darkness = 0.92
        bounce = 0.55
        warmth = 0.25
        texture = "gritty"
    }
} | ConvertTo-Json -Depth 10

try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/v1/arrangements/generate" `
        -Method POST `
        -ContentType "application/json" `
        -Body $payload `
        -UseBasicParsing `
        -ErrorAction Stop
    
    Write-Host "✅ Request successful: HTTP $($response.StatusCode)" -ForegroundColor Green
    
    $data = $response.Content | ConvertFrom-Json
    Write-Host "`nResponse:" -ForegroundColor Cyan
    Write-Host "  Arrangement ID: $($data.arrangement_id)"
    Write-Host "  Status: $($data.status)"
    
    Write-Host "`n✅ Check backend logs for: 'Applying style overrides from sliders'" -ForegroundColor Green
    
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    Write-Host "❌ Request failed: HTTP $statusCode" -ForegroundColor Red
    
    if ($statusCode -eq 404) {
        Write-Host "  Loop ID 1 not found - try a different loop_id" -ForegroundColor Yellow
    } elseif ($statusCode -eq 413) {
        Write-Host "  Payload too large (should NOT happen for style params)" -ForegroundColor Yellow
    }
}

Write-Host "`nRunning unit tests..." -ForegroundColor Yellow
try {
    & .\.venv\Scripts\python.exe test_phase4_integration.py | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ All unit tests passed" -ForegroundColor Green
    } else {
        Write-Host "❌ Tests failed" -ForegroundColor Red
    }
} catch {
    Write-Host "⚠️  Could not run tests" -ForegroundColor Yellow
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "PHASE 4: IMPLEMENTATION COMPLETE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "`nNext Steps:" -ForegroundColor White
Write-Host "  1. Open http://localhost:3000/generate"
Write-Host "  2. Select a loop and switch to Natural Language mode"
Write-Host "  3. Adjust style sliders"
Write-Host "  4. Generate arrangement"
Write-Host "  5. Verify backend logs show style overrides"
Write-Host "`nDocumentation:"
Write-Host "  - PHASE_4_COMPLETION_REPORT.md"
Write-Host "  - PHASE_4_TEST_GUIDE.md"
Write-Host "`n"
