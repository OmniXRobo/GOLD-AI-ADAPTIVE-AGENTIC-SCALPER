# Owner-controlled backup of the GOLD AI database. Nothing is deleted.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
.\.venv\Scripts\python.exe -c "from gold_ai.config import load_settings; from gold_ai.backup import create_backup; import json; s=load_settings('config.local.json'); print(json.dumps(create_backup(s.database_url, 'backups'), default=str, indent=2))"
