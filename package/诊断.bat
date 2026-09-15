@echo off
chcp 65001 >nul
title mpau Diagnosis
cd /d "%~dp0"
if not exist "%~dp0diagnose.ps1" (
    echo [ERROR] diagnose.ps1 not found next to this file.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnose.ps1"
echo.
pause
