# pytest.ps1 - Run pytest using the project virtual environment
# Usage: .\pytest.ps1 [pytest arguments]
# Examples:
#   .\pytest.ps1                                        # Run all tests
#   .\pytest.ps1 tests/services/test_audio_post_pipeline.py  # Run specific file
#   .\pytest.ps1 -v -k "test_mastering"                # Run with verbose + filter

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

# Ensure we're in the backend directory
Push-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

try {
    # Run pytest using the venv Python interpreter
    & .\.venv\Scripts\python.exe -m pytest @PytestArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $exitCode
