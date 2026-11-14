<#
  Starts HomeNet Monitor. On first run it sets up Python packages and builds the web UI.
  Usage:  powershell -ExecutionPolicy Bypass -File .\start.ps1 [-Rebuild]
#>
param([switch]$Rebuild)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# Some Windows PATHs contain stray quote characters, which stop cmd.exe (used by npm) finding node.
$env:PATH = (($env:PATH -split ';') | Where-Object { $_ -and $_ -notmatch '"' -and $_ -ne '%path%' }) -join ';'

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host 'Creating Python environment...' -ForegroundColor Cyan
    python -m venv (Join-Path $root '.venv')
}
& $py -c "import fastapi, uvicorn, httpx" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing Python packages...' -ForegroundColor Cyan
    & $py -m pip install -q --disable-pip-version-check --no-cache-dir -r (Join-Path $root 'backend\requirements.txt')
}

$dist = Join-Path $root 'frontend\dist\index.html'
if ($Rebuild -or -not (Test-Path $dist)) {
    Write-Host 'Building the web UI...' -ForegroundColor Cyan
    Push-Location (Join-Path $root 'frontend')
    try {
        if (-not (Test-Path 'node_modules')) { npm install --no-audit --no-fund }
        npm run build
    } finally { Pop-Location }
}

& $py (Join-Path $root 'backend\run.py')
