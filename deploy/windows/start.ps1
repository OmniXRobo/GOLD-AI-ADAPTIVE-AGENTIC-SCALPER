# Start the API/dashboard with the read-only MT5 collector and live virtual engine.
# The MT5 terminal must be running and logged in. Real-money execution stays disabled
# unless the owner separately enables it (see docs/SECURITY.md).
# The service is restarted 10 s after it exits (Task Scheduler's "restart on failure" does not
# react to a non-zero exit code). Use -Once to run it a single time. To stop it for good, end the
# scheduled task (Stop-ScheduledTask) or create logs\STOP.
param(
    [string]$TerminalPath = "",
    [string]$Symbol = "",
    [string]$Symbols = "",
    [int]$Port = 8000,
    [switch]$Once
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$pyArgs = @("-m", "gold_ai", "--config", "config.local.json", "serve", "--mt5", "--port", $Port)
if ($TerminalPath) { $pyArgs += @("--terminal-path", $TerminalPath) }
if ($Symbol) { $pyArgs += @("--symbol", $Symbol) }
if ($Symbols) { $pyArgs += @("--symbols", $Symbols) }
New-Item -ItemType Directory -Force -Path logs | Out-Null
Remove-Item logs\STOP -ErrorAction SilentlyContinue
# Start-Process keeps Python's stderr (uvicorn logs) from being turned into PowerShell errors,
# which would stop this script under ErrorActionPreference=Stop on Windows PowerShell 5.1.
$quoted = $pyArgs | ForEach-Object { if ("$_" -match '\s') { "`"$_`"" } else { "$_" } }
while ($true) {
    $stamp = Get-Date -Format yyyyMMdd_HHmmss
    # No -Wait: Start-Process -Wait also waits for child processes, and the MT5 terminal that the service
    # relaunches after a lost link is a child of Python. On 2026-11-05 the service exited but this loop kept
    # waiting on that terminal and never restarted it. WaitForExit() waits for the Python process only.
    $p = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList $quoted -NoNewWindow -PassThru `
        -RedirectStandardOutput "logs\gold_ai_$stamp.out.log" -RedirectStandardError "logs\gold_ai_$stamp.log"
    $null = $p.Handle   # keeps the process handle so ExitCode is available after it exits
    $p.WaitForExit()
    Add-Content logs\restarts.log "$(Get-Date -Format o) service exited with code $($p.ExitCode)"
    if ($Once -or (Test-Path logs\STOP)) { exit $p.ExitCode }
    Start-Sleep -Seconds 10
}
