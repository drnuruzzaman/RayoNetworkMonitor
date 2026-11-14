<#
  Installs AdGuard Home as a Windows service and opens DNS (port 53) in Windows Firewall
  for your private (home) network.

  Run from an *Administrator* PowerShell:
     powershell -ExecutionPolicy Bypass -File .\scripts\install-adguard.ps1

  Then open http://127.0.0.1:3000 to finish AdGuard's own first-run wizard.
#>
#Requires -RunAsAdministrator
param(
    [string]$InstallDir = 'C:\AdGuardHome'
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$existing = Get-Service -Name AdGuardHome -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "AdGuard Home is already installed (service status: $($existing.Status))." -ForegroundColor Yellow
    if ($existing.Status -ne 'Running') { Start-Service AdGuardHome }
    Write-Host 'Open http://127.0.0.1:3000 to manage it.'
    return
}

# Make sure nothing else is using DNS port 53.
$busy = Get-NetUDPEndpoint -LocalPort 53 -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -ne '127.0.0.53' }
if ($busy) {
    $proc = Get-Process -Id ($busy | Select-Object -First 1).OwningProcess -ErrorAction SilentlyContinue
    Write-Warning "Port 53 is already used by '$($proc.ProcessName)'. Stop that program first (for example Windows 'Internet Connection Sharing' or another DNS server)."
    return
}

$arch = switch ($env:PROCESSOR_ARCHITECTURE) { 'ARM64' { 'arm64' } 'x86' { '386' } default { 'amd64' } }
$url = "https://github.com/AdguardTeam/AdGuardHome/releases/latest/download/AdGuardHome_windows_$arch.zip"
$work = Join-Path $env:TEMP ("adguard-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $work | Out-Null
$zip = Join-Path $work 'AdGuardHome.zip'

Write-Host "Downloading AdGuard Home from the official GitHub release:`n  $url" -ForegroundColor Cyan
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
Write-Host ("SHA-256: " + (Get-FileHash $zip -Algorithm SHA256).Hash)

Expand-Archive -Path $zip -DestinationPath $work -Force
$src = Join-Path $work 'AdGuardHome'
if (-not (Test-Path (Join-Path $src 'AdGuardHome.exe'))) { throw 'Download did not contain AdGuardHome.exe' }

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item -Path (Join-Path $src '*') -Destination $InstallDir -Recurse -Force
Remove-Item $work -Recurse -Force

Write-Host 'Installing the Windows service...' -ForegroundColor Cyan
Push-Location $InstallDir
try { & .\AdGuardHome.exe -s install } finally { Pop-Location }

Write-Host 'Allowing DNS through Windows Firewall (home/private networks only)...' -ForegroundColor Cyan
foreach ($proto in 'UDP', 'TCP') {
    $name = "AdGuard Home DNS ($proto)"
    if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol $proto -LocalPort 53 -Action Allow -Profile Private | Out-Null
    }
}

$netProfile = (Get-NetConnectionProfile | Select-Object -First 1)
if ($netProfile -and $netProfile.NetworkCategory -ne 'Private') {
    Write-Warning "Your network '$($netProfile.Name)' is set to $($netProfile.NetworkCategory). Set it to Private (Settings > Network & internet > Wi-Fi > your network) so other devices can reach this PC."
}

Write-Host "`nDone! Open http://127.0.0.1:3000 to finish AdGuard Home's setup wizard." -ForegroundColor Green
Write-Host 'On the "Admin Web Interface" step choose port 3000. Keep DNS on all interfaces, port 53.'
