# Zip recent logs and the MT5 bridge files for diagnostics. Excludes config and database.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$out = "logs\diagnostics_$(Get-Date -Format yyyyMMdd_HHmmss).zip"
Compress-Archive -Path logs\*.log -DestinationPath $out -Force
Write-Host "Wrote $out (contains no credentials; review before sharing)."
