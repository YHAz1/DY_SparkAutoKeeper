param(
    [string]$Time = "09:00",
    [switch]$Unregister
)
# Register/remove Windows scheduled task: run main.py daily at $Time
# Features: wake-to-run + catch-up after missed schedule
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads files as GBK, non-ASCII breaks parsing)
$ErrorActionPreference = "Stop"

$appDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$condaBase = (& conda info --base | Select-Object -First 1).Trim()
if (-not $condaBase) { throw "conda not found, run install.bat first" }
$pythonExe = Join-Path $condaBase "envs\dy_spark\python.exe"
if (-not (Test-Path $pythonExe)) { throw "env dy_spark not found, run install.bat first" }

$taskName = "DYSparkAutoKeeper"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Task $taskName removed"
    exit 0
}

# Action: run main.py with dy_spark python
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$appDir\main.py`"" -WorkingDirectory $appDir

# Trigger: daily at $Time
$trigger = New-ScheduledTaskTrigger -Daily -At $Time

# Settings: catch up missed schedule, max runtime 10 min
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$task = Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "DY Spark AutoKeeper: daily send at $Time" -Force

# Set wake-to-run (PS5.1 cannot set it on New-ScheduledTaskTrigger, set after registration)
try {
    $task.Triggers[0].WakeToRun = $true
    Set-ScheduledTask -InputObject $task | Out-Null
    Write-Host "OK: registered $taskName (daily $Time, wake-to-run, catch-up)"
} catch {
    Write-Host "OK: registered $taskName (daily $Time, catch-up)"
    Write-Warning "wake-to-run failed (does not affect scheduled trigger): $($_.Exception.Message)"
}
Write-Host "Manage: register_task.bat -Time 09:00 | register_task.bat -Unregister"
