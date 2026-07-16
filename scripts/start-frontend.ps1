$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$FE = Join-Path $Root "frontend"
Push-Location $FE
try {
    if (-not (Test-Path (Join-Path $FE "node_modules"))) {
        Write-Host "Installing npm deps..." -ForegroundColor Cyan
        npm install
    }
    npm run dev
} finally { Pop-Location }
