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
$log = "logs\gold_ai_$(Get-Date -Format yyyyMMdd).log"
.\.venv\Scripts\python.exe @args *>> $log
