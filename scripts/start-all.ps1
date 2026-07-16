$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Scripts = $PSScriptRoot

Write-Host "Starting backend (port 5055) and frontend (port 5180)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @("-NoExit", "-File", (Join-Path $Scripts "start-backend.ps1"))
Start-Sleep -Seconds 3
Start-Process powershell -ArgumentList @("-NoExit", "-File", (Join-Path $Scripts "start-frontend.ps1"))
Write-Host ""
Write-Host "Backend:  http://127.0.0.1:5055" -ForegroundColor Green
Write-Host "Frontend: http://127.0.0.1:5180" -ForegroundColor Green
