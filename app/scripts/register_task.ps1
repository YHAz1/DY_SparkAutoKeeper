param(
    [string]$Time = "09:00",
    [switch]$Unregister
)
# Register/remove auto-start for DY Spark AutoKeeper.
# No admin required. Two mechanisms (both user-level):
#   1) Startup-folder VBS -> fully hidden, runs on every logon with 20s delay,
#      main.py decides: done -> exit | before send time -> wait | past time -> send now
#   2) Daily scheduled task at $Time -> scheduled fallback
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads files as GBK, non-ASCII breaks parsing)
$ErrorActionPreference = "Stop"

$appDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$condaBase = (& conda info --base | Select-Object -First 1).Trim()
if (-not $condaBase) { throw "conda not found, run install.bat first" }
$pythonw = Join-Path $condaBase "envs\dy_spark\pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "env dy_spark not found, run install.bat first" }

$taskName = "DYSparkAutoKeeper"
$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$startupFile = Join-Path $startupDir "spark_check.lnk"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $startupFile -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $startupDir "spark_check.vbs") -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $startupDir "spark_check.bat") -Force -ErrorAction SilentlyContinue
    Write-Host "Auto-start removed"
    exit 0
}

# --- 1) Startup-folder shortcut (runs on every logon, no window) ---
# Shortcut avoids the WScript.Shell.Run double-quoted-args bug; shell handles quoting.
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($startupFile)
$lnk.TargetPath = $pythonw
$lnk.Arguments = "`"$appDir\main.py`""
$lnk.WorkingDirectory = $appDir
$lnk.WindowStyle = 7
$lnk.Save()
Remove-Item (Join-Path $startupDir "spark_check.vbs") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $startupDir "spark_check.bat") -Force -ErrorAction SilentlyContinue
Write-Host "OK: startup check installed (shortcut) -> $startupFile"

# --- 2) Daily scheduled task (fallback trigger) ---
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$appDir\main.py`"" -WorkingDirectory $appDir
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 60)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "DY Spark AutoKeeper: daily send at $Time" -Force | Out-Null
Write-Host "OK: daily task $taskName registered at $Time"
Write-Host "Manage: register_task.bat -Time 09:00 | register_task.bat -Unregister"
