@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0control-aidc.ps1" -Action Restart
exit /b %errorlevel%
