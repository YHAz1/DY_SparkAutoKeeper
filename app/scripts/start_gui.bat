@echo off
chcp 65001 >nul
rem 启动配置面板（tkinter，后台运行，不残留命令行窗口）
for /f "delims=" %%i in ('conda info --base') do set "CONDA_BASE=%%i"
if not defined CONDA_BASE (
  echo [错误] 未找到 conda，请先运行 install.bat
  pause
  exit /b 1
)
if not exist "%CONDA_BASE%\envs\dy_spark\python.exe" (
  echo [错误] 未找到 dy_spark 环境，请先运行 install.bat
  pause
  exit /b 1
)
start "" "%CONDA_BASE%\envs\dy_spark\python.exe" "%~dp0..\gui.py"
