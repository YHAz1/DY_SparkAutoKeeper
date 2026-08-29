param(
    [string]$Time = "09:00",
    [string]$RemindTime = "22:30",
    [switch]$Unregister
)
# Register/remove auto-start for DY Spark AutoKeeper.
# No admin required. Mechanisms (all user-level):
#   1) Startup-folder shortcut -> runs on every logon, main decides:
#      done -> exit | before time -> wait | past time -> send now (catch-up)
#   2) Daily scheduled task at $Time -> scheduled fallback (also wakes from sleep)
#   3) Daily remind task "$taskName-Remind" at $RemindTime -> runs app --remind:
#      if today's send still not done, it auto-resends once and/or pushes a
#      WeCom group-robot webhook notice. Skipped when $RemindTime is empty.
#      Remind time should be LATER than the latest possible send time
#      (random range is 09:00-22:00, so default 22:30).
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
    Unregister-ScheduledTask -TaskName "$taskName-Remind" -Confirm:$false -ErrorAction SilentlyContinue
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
    $remindArg = "--remind"
    Write-Host "OK: packaged mode detected -> $exe"
} else {
    $condaBase = (& conda info --base | Select-Object -First 1).Trim()
    if (-not $condaBase) { throw "conda not found (dev mode requires conda env dy_spark)" }
    $pythonw = Join-Path $condaBase "envs\dy_spark\pythonw.exe"
    if (-not (Test-Path $pythonw)) { throw "env dy_spark not found, run install.bat first" }
    $runner = $pythonw
    $runArg = "`"$appDir\main.py`""
    $remindArg = "`"$appDir\main.py`" --remind"
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

# --- 2) Daily scheduled task (fallback trigger) + network-reconnect event trigger ---
# Settings notes (2026-08-23 fix): allow start on battery + wake timers.
# Without -AllowStartIfOnBatteries the task silently skipped once when the PC
# woke from sleep (power source read as battery right after resume).
# -WakeToRun lets the machine wake up at send time even if it is asleep.
# ExecutionTimeLimit 120 min: send attempt fits comfortably.
#
# Event trigger (no polling): subscribe to Microsoft-Windows-NetworkProfile/
# Operational EventID 10000 ("network connected"). Every reconnect (sleep wake,
# Wi-Fi back, cable plug) starts app --run; main decides: done -> quick exit |
# past send time -> catch-up send. This is the recovery path when the scheduled
# run failed because the network was still down (verified EventID 10000 exists
# on Win10/11 incl. Win11 26200).
$action = New-ScheduledTaskAction -Execute $runner -Argument $runArg -WorkingDirectory $appDir
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$triggers = @($trigger)
try {
    $cimTrigger = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
    $netTrig = New-CimInstance -CimClass $cimTrigger -ClientOnly
    $netTrig.Enabled = $True
    $netTrig.Subscription = @'
<QueryList><Query Id="0"><Select Path="Microsoft-Windows-NetworkProfile/Operational">*[System[(EventID=10000)]]</Select></Query></QueryList>
'@
    $triggers += $netTrig
} catch {
    Write-Host "WARN: network-reconnect trigger unavailable: $($_.Exception.Message)"
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 120)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings `
    -Description "DY Spark AutoKeeper: daily send at $Time + resend on network reconnect" -Force | Out-Null
Write-Host "OK: daily task $taskName registered at $Time (+ network-reconnect trigger)"

# --- 3) Daily remind task (evening catch-up + webhook notice) ---
# Fires app --remind: re-checks state, auto-resends if still unsent, then
# pushes a WeCom group-robot webhook notice when it still failed.
# Empty $RemindTime = leave the remind task untouched (backward compat with
# register_task.ps1 -Time-only calls from the randomize flow).
if ($RemindTime -ne "") {
    $rAction = New-ScheduledTaskAction -Execute $runner -Argument $remindArg -WorkingDirectory $appDir
    $rTrigger = New-ScheduledTaskTrigger -Daily -At $RemindTime
    $rSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 120)
    Register-ScheduledTask -TaskName "$taskName-Remind" -Action $rAction -Trigger $rTrigger `
        -Settings $rSettings -Description "DY Spark AutoKeeper: evening remind/resend check at $RemindTime" -Force | Out-Null
    Write-Host "OK: remind task $taskName-Remind registered at $RemindTime"
}

Write-Host "Manage: register_task.bat -Time 09:00 [-RemindTime 22:30] | register_task.bat -Unregister"
