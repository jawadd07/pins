@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (.venv\Scripts\python.exe agent_doctor.py) else (python agent_doctor.py)
echo.
pause
