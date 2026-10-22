# GOLD AI — Windows installation (run from the repository root in PowerShell).
# Does not require administrator rights. Creates .venv, installs Python deps, builds the dashboard.
param(
    [string]$Python = "py",
    [switch]$Postgres
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))

# The py launcher picks the newest installed Python 3; any 3.11+ works.
$PyArgs = @()
if ((Split-Path -Leaf $Python) -match '^py(\.exe)?$') { $PyArgs = @("-3") }
& $Python @PyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required." }
& $Python @PyArgs -m venv .venv
if (-not (Test-Path .\.venv\Scripts\python.exe)) { throw "Could not create .venv" }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install "MetaTrader5>=5.0.45"
if ($Postgres) { .\.venv\Scripts\python.exe -m pip install "psycopg[binary]>=3.1" }

if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location dashboard; npm ci; npm run build; Pop-Location
} else {
    Write-Warning "Node.js not found: dashboard not built (API still works)."
}

if (-not (Test-Path config.local.json)) {
    Copy-Item deploy\config.example.json config.local.json
    Write-Host "Created config.local.json - edit secret_key and database_url before starting."
}
New-Item -ItemType Directory -Force -Path data, logs, backups | Out-Null
.\.venv\Scripts\python.exe -m pytest -q
Write-Host "Install finished. Next: .\.venv\Scripts\python.exe -m gold_ai --config config.local.json create-user owner"
