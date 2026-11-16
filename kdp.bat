@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
python kdp_agent.py make --count 2
python kdp_agent.py link
start "" kdp_out
pause
