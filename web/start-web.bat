@echo off
rem mpau web console launcher (local mode, http://127.0.0.1:8898)
title mpau Auto Upload Web
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set MPAU_WEB_HOST=127.0.0.1
set MPAU_WEB_PORT=8898
echo Starting mpau web console at http://127.0.0.1:8898 ...
echo Close this window to stop the service.
".venv\Scripts\python.exe" web/app.py
pause
