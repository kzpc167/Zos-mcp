@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart_workbuddy.ps1" %*
echo.
pause
