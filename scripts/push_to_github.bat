@echo off
chcp 65001 >nul
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\push_to_github.ps1" %*
echo.
echo 按任意键关闭窗口。
pause >nul
