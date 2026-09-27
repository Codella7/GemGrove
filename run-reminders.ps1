$ErrorActionPreference = "Stop"

# This script intentionally contains no WhatsApp secrets. The scheduled task
# reads the permanent token and identifiers from this Windows user's environment.
Set-Location $PSScriptRoot
$logDirectory = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$logFile = Join-Path $logDirectory "whatsapp-reminders.log"

"[$(Get-Date -Format s)] Starting purchase reminder run" | Tee-Object -FilePath $logFile -Append
& python -m flask --app run.py send-purchase-reminders 2>&1 |
    Tee-Object -FilePath $logFile -Append

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
