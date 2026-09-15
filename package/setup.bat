@echo off
rem mpau one-click installer - double click this file
title mpau Installer
cd /d "%~dp0"
echo ============================================
echo    mpau Auto Upload - One-click Installer
echo ============================================
echo.
if not exist "%~dp0install.ps1" (
    echo [ERROR] install.ps1 not found next to this file.
    echo Please keep setup.bat, install.ps1 and mpau.zip in the SAME folder.
    pause
    exit /b 1
)
if not exist "%~dp0mpau.zip" (
    echo [ERROR] mpau.zip not found next to this file.
    echo Please keep setup.bat, install.ps1 and mpau.zip in the SAME folder.
    pause
    exit /b 1
)
echo Installing to D:\mpau-auto-upload ...
echo This takes 5-10 minutes. Do not close this window.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -OfflineZip "%~dp0mpau.zip"
echo.
echo Installer finished. Press any key to close.
pause >nul
