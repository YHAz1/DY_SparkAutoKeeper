@echo off
chcp 65001 >nul
rem 运行页面结构探查脚本（输出 diag_output.txt）
for /f "delims=" %%i in ('conda info --base') do set "CONDA_BASE=%%i"
if not defined CONDA_BASE (
  echo [错误] 未找到 conda
  pause
  exit /b 1
)
"%CONDA_BASE%\envs\dy_spark\python.exe" "%~dp0..\diag.py"
pause
