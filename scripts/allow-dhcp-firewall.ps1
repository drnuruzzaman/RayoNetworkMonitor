<#
  Lets devices on your home network reach HomeNet's address server (DHCP, UDP port 67).
  Only needed if you turn on the address server in HomeNet.

  Run from an *Administrator* PowerShell:
     powershell -ExecutionPolicy Bypass -File .\scripts\allow-dhcp-firewall.ps1
  Remove again with:  -Uninstall
#>
#Requires -RunAsAdministrator
param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$name = 'HomeNet DHCP server (UDP 67)'

Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Uninstall) {
    Write-Host 'DHCP firewall rule removed.' -ForegroundColor Green
    return
}
New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol UDP -LocalPort 67 -Action Allow -Profile Private | Out-Null
Write-Host "Done. Devices on your home (Private) network can now get addresses from HomeNet." -ForegroundColor Green
