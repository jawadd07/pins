@echo off
cd /d "%~dp0"
if exist keys.bat call keys.bat
call .venv\Scripts\activate.bat
python pinterest_agent.py reschedule --after 2026-11-15
echo.
echo New CSV in exports folder. Delete the old scheduled pins from 15 Nov on BEFORE uploading it.
pause
