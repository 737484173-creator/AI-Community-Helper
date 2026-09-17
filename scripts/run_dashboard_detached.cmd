@echo off
cd /d "%~dp0.."
"%CD%\.venv\Scripts\python.exe" manage.py dashboard --port 8502 >> logs\dashboard_detached.out.log 2>> logs\dashboard_detached.err.log
