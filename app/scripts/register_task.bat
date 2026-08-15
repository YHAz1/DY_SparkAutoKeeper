@echo off
chcp 65001 >nul
powershell -ExecutionPolicy Bypass -File "%~dp0register_task.ps1" %*
pause
