$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot
foreach ($name in @("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT")) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        $value = [Environment]::GetEnvironmentVariable($name, "User")
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}
$logDirectory = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$logFile = Join-Path $logDirectory "push-reminders.log"

"[$(Get-Date -Format s)] Starting due-payment push run" | Tee-Object -FilePath $logFile -Append
& $python -m flask --app run.py send-due-payment-pushes 2>&1 |
    Tee-Object -FilePath $logFile -Append

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}