param(
    [string]$Time = "09:00",
    [switch]$Unregister
)
# 注册/删除 Windows 定时任务：每日 $Time 自动运行 main.py
# 特性：唤醒计算机运行 + 错过计划时间尽快补发（开机补发）
$ErrorActionPreference = "Stop"

$appDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$condaBase = (& conda info --base | Select-Object -First 1).Trim()
if (-not $condaBase) { throw "未找到 conda，请先运行 install.bat" }
$pythonExe = Join-Path $condaBase "envs\dy_spark\python.exe"
if (-not (Test-Path $pythonExe)) { throw "未找到 $pythonExe，请先运行 install.bat" }

$taskName = "DYSparkAutoKeeper"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "已删除定时任务 $taskName"
    exit 0
}

# 动作：调用 dy_spark 环境的 python 运行 main.py
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$appDir\main.py`"" -WorkingDirectory $appDir

# 触发器：每日指定时间；休眠/睡眠时唤醒计算机运行
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$trigger.WakeToRun = $true

# 设置：错过计划时间则尽快启动（保证"开机即补发"）；最长运行 10 分钟
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "抖音自动续火花：每日 $Time 自动给好友发送消息" -Force | Out-Null

Write-Host "已注册定时任务 $taskName（每日 $Time，唤醒运行，错过自动补发）"
Write-Host "查看/删除：scripts\register_task.bat -Time 09:00 | register_task.bat -Unregister"
