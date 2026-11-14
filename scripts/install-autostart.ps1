<#
  Makes HomeNet Monitor start automatically (hidden) when you sign in to Windows, and lets
  phones and laptops on your home network open the dashboard.

  Run from an *Administrator* PowerShell:
     powershell -ExecutionPolicy Bypass -File .\scripts\install-autostart.ps1
  Remove again with:  -Uninstall
#>
#Requires -RunAsAdministrator
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$taskName = 'HomeNet Monitor'
$fwName = 'HomeNet Monitor dashboard'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Get-NetFirewallRule -DisplayName $fwName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Host 'Autostart and firewall rule removed.' -ForegroundColor Green
    return
}

$pyw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pyw)) { throw 'Run start.ps1 once first so the Python environment exists.' }

# The dashboard port lives in HomeNet's settings database. Read it from there, don't hard-code it.
$py = Join-Path $root '.venv\Scripts\python.exe'
$port = & $py -c "import sys; sys.path.insert(0, r'$root\backend'); from app import db, settings_store as S; db.init(); print(S.get('ui_port'))"

$action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$root\backend\run.py`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Home network monitoring dashboard' -Force | Out-Null

Get-NetFirewallRule -DisplayName $fwName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $fwName -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow -Profile Private | Out-Null

Write-Host "Done. HomeNet starts when you sign in, and the dashboard is reachable on port $port from your home network." -ForegroundColor Green
Write-Host 'If you change the port in Settings later, run this script again.'
