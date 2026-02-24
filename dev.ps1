#!/usr/bin/env pwsh
# LoopArchitect Backend - Development Server Script
# Run with: .\dev.ps1

Write-Host "🚀 LoopArchitect Backend Dev Server" -ForegroundColor Cyan
Write-Host "====================================`n" -ForegroundColor Cyan

# Step 1: Create virtual environment if it doesn't exist
if (-Not (Test-Path ".venv")) {
    Write-Host "📦 Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ Virtual environment created`n" -ForegroundColor Green
} else {
    Write-Host "✅ Virtual environment exists`n" -ForegroundColor Green
}

# Step 2: Activate virtual environment
Write-Host "🔧 Activating virtual environment..." -ForegroundColor Yellow
& ".venv\Scripts\Activate.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to activate virtual environment" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Virtual environment activated`n" -ForegroundColor Green

# Step 3: Install/upgrade dependencies
Write-Host "📥 Installing dependencies from requirements.txt..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to install dependencies" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Dependencies installed`n" -ForegroundColor Green

# Step 4: Print Swagger URL
Write-Host "================================" -ForegroundColor Cyan
Write-Host "📖 Swagger UI Documentation:" -ForegroundColor Green
Write-Host "   http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "================================`n" -ForegroundColor Cyan

# Step 5: Run FastAPI with uvicorn
Write-Host "🌟 Starting FastAPI development server..." -ForegroundColor Yellow
Write-Host "   Press Ctrl+C to stop`n" -ForegroundColor Gray
uvicorn app.main:app --reload
