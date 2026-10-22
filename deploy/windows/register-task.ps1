# Register a per-user scheduled task that starts GOLD AI at logon and restarts it on failure.
# No administrator rights needed (runs as the current user, only while logged on - keep the VPS
# session logged in, which MT5 needs anyway).
param([string]$TaskName = "GoldAI", [string]$TerminalPath = "", [string]$Symbol = "")
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$root\deploy\windows\start.ps1`""
if ($TerminalPath) { $arg += " -TerminalPath `"$TerminalPath`"" }
if ($Symbol) { $arg += " -Symbol $Symbol" }
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Registered task $TaskName. Start now with: Start-ScheduledTask -TaskName $TaskName"
