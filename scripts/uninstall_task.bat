@echo off
chcp 65001 >nul
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\install_task.ps1" -Remove %*
echo.
echo 按任意键关闭窗口。
pause >nul
