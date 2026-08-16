@echo off
chcp 65001 >nul
rem 注册开机自启定时任务（需管理员权限：登录时检查 + 每日定时）
rem 自动请求提权，UAC 弹出时请点"是"

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo 需要管理员权限，正在请求提升（请在弹出的 UAC 窗口点"是"）...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_task.ps1" %*
echo.
pause
