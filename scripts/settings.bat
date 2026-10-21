@echo off
chcp 65001 >nul
cd /d "%~dp0.."

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 "%~dp0..\settings_gui.pyw"
    exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0..\settings_gui.pyw"
    exit /b 0
)
where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0..\settings_gui.pyw"
    exit /b 0
)
echo 没找到 Python 3，请先安装 python.org 的 Python（安装时勾选 Add to PATH）。
pause
