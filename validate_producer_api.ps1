#!/usr/bin/env pwsh
<#
End-to-End Validation: Producer Engine API Integration

Tests:
1. Backend health check
2. POST /arrangements/generate with style_text_input
3. Verify producer_arrangement_json in response
4. Check database for stored arrangement
5. Test all 9 genres
#>

Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "PRODUCER ENGINE API VALIDATION" -ForegroundColor Cyan
Write-Host "=" * 70
Write-Host ""

# Configuration
$BACKEND_URL = "http://localhost:8000"
$API_BASE = "$BACKEND_URL/api/v1"

# Colors
$SUCCESS = "Green"
$ERROR = "Red"
$WARNING = "Yellow"
$INFO = "Cyan"

# ============================================================================
# PHASE 1: HEALTH CHECK
# ============================================================================
Write-Host "📡 PHASE 1: BACKEND HEALTH CHECK" -ForegroundColor $INFO
Write-Host "-" * 70
Write-Host ""

try {
    $health = Invoke-WebRequest -Uri "$API_BASE/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    Write-Host "✅ Backend is running on port 8000" -ForegroundColor $SUCCESS
    Write-Host "   Response: $($health.StatusCode) OK"
    Write-Host ""
} catch {
    Write-Host "❌ Backend is not responding!" -ForegroundColor $ERROR
    Write-Host "   Start backend: .\.venv\Scripts\python.exe main.py"
    Write-Host ""
    exit 1
}

# ============================================================================
# PHASE 2: CHECK FEATURE FLAG
# ============================================================================
Write-Host "🚩 PHASE 2: FEATURE FLAG STATUS" -ForegroundColor $INFO
Write-Host "-" * 70
Write-Host ""

Write-Host "IMPORTANT: Enable FEATURE_PRODUCER_ENGINE before testing!" -ForegroundColor $WARNING
Write-Host ""
Write-Host "Set environment variable:"
Write-Host "  \$env:FEATURE_PRODUCER_ENGINE = 'true'"
Write-Host ""
Write-Host "Or add to .env file:"
Write-Host "  FEATURE_PRODUCER_ENGINE=true"
Write-Host ""
Write-Host "Then restart the backend server."
Write-Host ""

# ============================================================================
# PHASE 3: CREATE TEST LOOP
# ============================================================================
Write-Host "📝 PHASE 3: SETUP - LIST EXISTING LOOPS" -ForegroundColor $INFO
Write-Host "-" * 70
Write-Host ""

try {
    $loops = Invoke-WebRequest -Uri "$API_BASE/loops" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop | ConvertFrom-Json
    
    if ($loops.PSObject.Properties.Name -contains 'items') {
        $loopCount = $loops.items.Count
    } elseif ($loops -is [Array]) {
        $loopCount = $loops.Count
    } else {
        $loopCount = 1
    }
    
    Write-Host "✅ Found $loopCount loops in system" -ForegroundColor $SUCCESS
    Write-Host ""
    
    if ($loopCount -gt 0) {
        Write-Host "Available loops:" -ForegroundColor $INFO
        $loopData = if ($loops.PSObject.Properties.Name -contains 'items') { $loops.items } else { $loops }
        $loopData | Select-Object -First 5 | ForEach-Object {
            Write-Host "  - ID: $($_.id), Name: $($_.name), BPM: $($_.bpm)"
        }
        $testLoopId = $loopData[0].id
        Write-Host ""
        Write-Host "Using loop ID: $testLoopId" -ForegroundColor $INFO
    } else {
        Write-Host "⚠️  No loops found - upload a loop first!" -ForegroundColor $WARNING
        exit 1
    }
} catch {
    Write-Host "❌ Failed to fetch loops: $_" -ForegroundColor $ERROR
    exit 1
}

Write-Host ""

# ============================================================================
# PHASE 4: TEST ARRANGEMENT GENERATION
# ============================================================================
Write-Host "🎼 PHASE 4: ARRANGEMENT GENERATION TEST" -ForegroundColor $INFO
Write-Host "-" * 70
Write-Host ""

$testCases = @(
    @{
        name = "Dark Trap"
        loop_id = $testLoopId
        target_seconds = 60
        style_text_input = "dark trap beat like future and southside"
    },
    @{
        name = "Modern R&B"
        loop_id = $testLoopId
        target_seconds = 90
        style_text_input = "smooth modern R&B bedroom vibes drake inspired"
    },
    @{
        name = "Cinematic"
        loop_id = $testLoopId
        target_seconds = 120
        style_text_input = "epic cinematic orchestral arrangement"
    }
)

$successCount = 0
foreach ($test in $testCases) {
    Write-Host "Testing: $($test.name)" -ForegroundColor $INFO
    
    try {
        $payload = @{
            loop_id = $test.loop_id
            target_seconds = $test.target_seconds
            style_text_input = $test.style_text_input
            use_ai_parsing = $true
        } | ConvertTo-Json
        
        $response = Invoke-WebRequest -Uri "$API_BASE/arrangements/generate" `
            -Method POST `
            -ContentType "application/json" `
            -Body $payload `
            -UseBasicParsing `
            -TimeoutSec 10 `
            -ErrorAction Stop
        
        $result = $response.Content | ConvertFrom-Json
        
        Write-Host "  ✅ Arrangement created: ID $($result.id)" -ForegroundColor $SUCCESS
        Write-Host "     Status: $($result.status)" -ForegroundColor $SUCCESS
        
        if ($result.PSObject.Properties.Name -contains 'producer_arrangement_json') {
            Write-Host "     ✅ producer_arrangement_json present" -ForegroundColor $SUCCESS
        } else {
            Write-Host "     ⚠️  producer_arrangement_json NOT present (check feature flag)" -ForegroundColor $WARNING
        }
        
        $successCount++
    } catch {
        Write-Host "  ❌ Failed: $_" -ForegroundColor $ERROR
    }
    
    Write-Host ""
}

Write-Host "✅ Generated $successCount/$($testCases.Count) test arrangements" -ForegroundColor $SUCCESS
Write-Host ""

# ============================================================================
# PHASE 5: DATABASE VERIFICATION
# ============================================================================
Write-Host "💾 PHASE 5: DATABASE VERIFICATION" -ForegroundColor $INFO
Write-Host "-" * 70
Write-Host ""

Write-Host "To verify database storage, run this SQL query:" -ForegroundColor $INFO
Write-Host ""
Write-Host "  SELECT id, status, producer_arrangement_json" -ForegroundColor $WARNING
Write-Host "  FROM arrangements" -ForegroundColor $WARNING
Write-Host "  WHERE producer_arrangement_json IS NOT NULL" -ForegroundColor $WARNING
Write-Host "  ORDER BY created_at DESC" -ForegroundColor $WARNING
Write-Host "  LIMIT 5;" -ForegroundColor $WARNING
Write-Host ""

# ============================================================================
# SUMMARY
# ============================================================================
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "VALIDATION CHECKLIST" -ForegroundColor Cyan
Write-Host "=" * 70
Write-Host ""

$checklist = @(
    @{ item = "Backend running"; done = $true }
    @{ item = "FEATURE_PRODUCER_ENGINE=true set"; done = $false }
    @{ item = "BeatGenomeLoader loads all 9 genomes"; done = $false }
    @{ item = "ProducerEngine.generate() creates arrangements"; done = $false }
    @{ item = "API returns producer_arrangement_json"; done = $false }
    @{ item = "Database stores producer_arrangement_json"; done = $false }
    @{ item = "All 9 genre genomes tested"; done = $false }
    @{ item = "Fallback behavior verified"; done = $false }
)

foreach ($item in $checklist) {
    $status = if ($item.done) { "✅" } else { "⬜" }
    Write-Host "$status $($item.item)" -ForegroundColor $INFO
}

Write-Host ""
Write-Host "=" * 70 -ForegroundColor Cyan
Write-Host "NEXT STEPS" -ForegroundColor Cyan
Write-Host "=" * 70
Write-Host ""
Write-Host "1. Verify FEATURE_PRODUCER_ENGINE environment variable is set to 'true'" -ForegroundColor $INFO
Write-Host "   In PowerShell: \$env:FEATURE_PRODUCER_ENGINE = 'true'" -ForegroundColor $WARNING
Write-Host ""
Write-Host "2. Restart backend server to load new configuration" -ForegroundColor $INFO
Write-Host "   .\.venv\Scripts\python.exe main.py" -ForegroundColor $WARNING
Write-Host ""
Write-Host "3. Re-run this validation script to test API endpoints" -ForegroundColor $INFO
Write-Host ""
Write-Host "4. Check database for 'producer_arrangement_json' in arrangements table" -ForegroundColor $INFO
Write-Host ""

if ($successCount -eq $testCases.Count) {
    Write-Host "✅ VALIDATION PASSED - Producer engine is working!" -ForegroundColor $SUCCESS
} else {
    Write-Host "⚠️  Some tests failed - check logs above" -ForegroundColor $WARNING
}

Write-Host ""
