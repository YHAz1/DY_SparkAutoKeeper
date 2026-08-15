@echo off
chcp 65001 >nul
rem 手动运行一次（首次用于扫码登录，之后用于测试）
for /f "delims=" %%i in ('conda info --base') do set "CONDA_BASE=%%i"
if not defined CONDA_BASE (
  echo [错误] 未找到 conda
  exit /b 1
)
"%CONDA_BASE%\envs\dy_spark\python.exe" "%~dp0..\main.py"
pause
