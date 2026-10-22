# Owner-controlled backup of the GOLD AI database (prompts for the owner password). Nothing is deleted.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
.\.venv\Scripts\python.exe -m gold_ai --config config.local.json backup
