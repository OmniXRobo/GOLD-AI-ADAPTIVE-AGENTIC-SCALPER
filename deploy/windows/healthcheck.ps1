# Returns exit code 0 when the API answers, 1 otherwise. Suitable for monitoring.
param([int]$Port = 8000)
try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5
    if ($r.status -eq "ok") { Write-Host "OK"; exit 0 }
} catch { Write-Host "API not reachable: $_" }
exit 1
