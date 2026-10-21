@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
set "PYEXE=py -3"
where py >nul 2>nul || set "PYEXE=python"
%PYEXE% "%~dp0..\wechat_auto.py" email-test
echo.
echo 按任意键关闭窗口。
pause >nul
