# Start the API/dashboard with the read-only MT5 collector and live virtual engine.
# The MT5 terminal must be running and logged in. Real-money execution stays disabled
# unless the owner separately enables it (see docs/SECURITY.md).
param(
    [string]$TerminalPath = "",
    [string]$Symbol = "",
    [int]$Port = 8000
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$pyArgs = @("-m", "gold_ai", "--config", "config.local.json", "serve", "--mt5", "--port", $Port)
if ($TerminalPath) { $pyArgs += @("--terminal-path", $TerminalPath) }
if ($Symbol) { $pyArgs += @("--symbol", $Symbol) }
New-Item -ItemType Directory -Force -Path logs | Out-Null
$stamp = Get-Date -Format yyyyMMdd_HHmmss
# Start-Process keeps Python's stderr (uvicorn logs) from being turned into PowerShell errors,
# which would stop this script under ErrorActionPreference=Stop on Windows PowerShell 5.1.
$quoted = $pyArgs | ForEach-Object { if ("$_" -match '\s') { "`"$_`"" } else { "$_" } }
$p = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList $quoted -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput "logs\gold_ai_$stamp.out.log" -RedirectStandardError "logs\gold_ai_$stamp.log"
exit $p.ExitCode
