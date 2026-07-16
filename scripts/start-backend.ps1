$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$BE = Join-Path $Root "backend"
if (-not (Test-Path (Join-Path $BE ".venv"))) {
    Write-Host "Creating venv..." -ForegroundColor Cyan
    python -m venv (Join-Path $BE ".venv")
    & (Join-Path $BE ".venv\Scripts\pip.exe") install -r (Join-Path $BE "requirements.txt") --quiet
}
Push-Location $BE
try {
    & ".\.venv\Scripts\python.exe" seed.py
    & ".\.venv\Scripts\python.exe" app.py
} finally { Pop-Location }
