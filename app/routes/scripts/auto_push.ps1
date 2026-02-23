# Loop Architect Auto Push Script
# Safely stages, commits, and pushes changes with error handling
# Usage: .\auto_push.ps1 [-Message "custom message"] [-DryRun]

param(
    [string]$Message = "auto: update",
    [switch]$DryRun = $false
)

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

function Write-ErrorMsg {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Write-InfoMsg {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

# Navigate to repo root automatically (find .git directory)
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = $scriptPath
while (-not (Test-Path "$repoRoot\.git")) {
    $parent = Split-Path -Parent $repoRoot
    if ($parent -eq $repoRoot) {
        Write-ErrorMsg "Could not find repository root (.git directory)"
        exit 1
    }
    $repoRoot = $parent
}

Set-Location $repoRoot
Write-InfoMsg "Working in repository: $repoRoot"

Write-InfoMsg "Checking git status..."
git status

Write-InfoMsg "Getting current branch name..."
$branch = git rev-parse --abbrev-ref HEAD
if ($LASTEXITCODE -ne 0) {
    Write-ErrorMsg "Failed to detect current branch"
    exit 1
}
Write-InfoMsg "Current branch: $branch"

Write-InfoMsg "Checking for changes..."
$status = git status --porcelain
if ([string]::IsNullOrWhiteSpace($status)) {
    Write-InfoMsg "No changes to commit. Working tree is clean."
    exit 0
}

Write-InfoMsg "Changes detected:"
Write-Host $status

if ($DryRun) {
    Write-InfoMsg "DRY RUN: Would stage and commit with message: '$Message'"
    exit 0
}

Write-InfoMsg "Staging all changes..."
git add -A
if ($LASTEXITCODE -ne 0) {
    Write-ErrorMsg "Failed to stage changes"
    exit 1
}
Write-Success "Changes staged"

Write-InfoMsg "Creating commit with message: '$Message'"
git commit -m "$Message"
if ($LASTEXITCODE -ne 0) {
    Write-ErrorMsg "Failed to create commit"
    exit 1
}
Write-Success "Commit created"

Write-InfoMsg "Pushing to origin/$branch..."
git push -u origin $branch
if ($LASTEXITCODE -ne 0) {
    Write-ErrorMsg "Failed to push changes"
    exit 1
}
Write-Success "Changes pushed to origin/$branch"

Write-Success "All done! Your changes are now on GitHub."


