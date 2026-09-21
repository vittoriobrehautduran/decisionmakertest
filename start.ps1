# Start the Jev vs Laya comparison app on Windows.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Host "Creating virtualenv..."
  & $python -m venv .venv
}

$venvPy = ".\.venv\Scripts\python.exe"
Write-Host "Starting http://127.0.0.1:8000"
& $venvPy -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
