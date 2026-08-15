@echo off
chcp 65001 >nul
setlocal
echo ============================================
echo   抖音自动续火花 - 一键安装
echo ============================================

rem 定位 conda
for /f "delims=" %%i in ('conda info --base') do set "CONDA_BASE=%%i"
if not defined CONDA_BASE (
  echo [错误] 未找到 conda，请确认 Anaconda 已安装并加入 PATH
  exit /b 1
)
set "ENV_DIR=%CONDA_BASE%\envs\dy_spark"
echo conda 基础目录: %CONDA_BASE%

rem 创建独立 conda 环境（绝不污染 base）
if not exist "%ENV_DIR%\python.exe" (
  echo [1/3] 创建独立 conda 环境 dy_spark ...
  call conda create -n dy_spark python=3.11 -y
) else (
  echo [1/3] 环境 dy_spark 已存在，跳过创建
)

echo [2/3] 安装依赖 playwright / pyyaml ...
call conda run -n dy_spark pip install -r "%~dp0..\requirements.txt"

echo [3/3] 下载 Chromium 浏览器（约 150MB，请耐心等待）...
call conda run -n dy_spark python -m playwright install chromium

echo.
echo 安装完成。下一步：
echo   1. 编辑 config.yaml 填写好友昵称、发送时间
echo   2. 运行 scripts\run_now.bat 完成首次扫码登录并测试发送
echo   3. 运行 scripts\register_task.bat 注册"开机自启 + 每日定时"任务
echo.
pause
