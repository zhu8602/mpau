@echo off
rem mpau launcher repair - run this on the installed machine
title mpau Repair
cd /d "%~dp0"
if not exist "%~dp0fix-launcher.ps1" (
    echo [ERROR] fix-launcher.ps1 not found next to this file.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix-launcher.ps1"
echo.
pause
