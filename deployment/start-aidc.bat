@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0control-aidc.ps1" -Action Start
exit /b %errorlevel%
