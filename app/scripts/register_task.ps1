param(
    [string]$Time = "09:00",
    [switch]$Unregister
)
# Register/remove auto-start for DY Spark AutoKeeper.
# No admin required. Two mechanisms (both user-level):
#   1) Startup-folder shortcut -> runs on every logon, main decides:
#      done -> exit | before time -> wait | past time -> send now (catch-up)
#   2) Daily scheduled task at $Time -> scheduled fallback
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads files as GBK, non-ASCII breaks parsing)
$ErrorActionPreference = "Stop"

# Fix mojibake when output is redirected (GUI calls us via subprocess):
# PS 5.1 writes stdout/stderr in OEM codepage when redirected; force UTF-8 then.
if ([Console]::IsOutputRedirected -or [Console]::IsErrorRedirected) {
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
    try { [Console]::ErrorEncoding = [System.Text.Encoding]::UTF8 } catch {}
}

$appDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$taskName = "DYSparkAutoKeeper"
$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$startupFile = Join-Path $startupDir "spark_check.lnk"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $startupFile -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $startupDir "spark_check.vbs") -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $startupDir "spark_check.bat") -Force -ErrorAction SilentlyContinue
    Write-Host "OK: auto-start removed"
    exit 0
}

# Resolve runner: packaged exe (app.exe --run) if present;
# otherwise conda pythonw (dev mode). conda is only needed in dev mode,
# so packaged builds (no conda on the machine) register without conda.
$exe = Join-Path $appDir "app.exe"
if (Test-Path $exe) {
    $runner = $exe
    $runArg = "--run"
    Write-Host "OK: packaged mode detected -> $exe"
} else {
    $condaBase = (& conda info --base | Select-Object -First 1).Trim()
    if (-not $condaBase) { throw "conda not found (dev mode requires conda env dy_spark)" }
    $pythonw = Join-Path $condaBase "envs\dy_spark\pythonw.exe"
    if (-not (Test-Path $pythonw)) { throw "env dy_spark not found, run install.bat first" }
    $runner = $pythonw
    $runArg = "`"$appDir\main.py`""
}

# --- 1) Startup-folder shortcut (runs on every logon, no window) ---
# Shortcut avoids the WScript.Shell.Run double-quoted-args bug; shell handles quoting.
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($startupFile)
$lnk.TargetPath = $runner
$lnk.Arguments = $runArg
$lnk.WorkingDirectory = $appDir
$lnk.WindowStyle = 7
$lnk.Save()
Remove-Item (Join-Path $startupDir "spark_check.vbs") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $startupDir "spark_check.bat") -Force -ErrorAction SilentlyContinue
Write-Host "OK: startup check installed (shortcut) -> $startupFile"

# --- 2) Daily scheduled task (fallback trigger) ---
$action = New-ScheduledTaskAction -Execute $runner -Argument $runArg -WorkingDirectory $appDir
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 60)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "DY Spark AutoKeeper: daily send at $Time" -Force | Out-Null
Write-Host "OK: daily task $taskName registered at $Time"
Write-Host "Manage: register_task.bat -Time 09:00 | register_task.bat -Unregister"
