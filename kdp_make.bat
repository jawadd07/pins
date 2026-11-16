@echo off
cd /d "%~dp0"
if exist keys.bat call keys.bat
if not exist .venv\Scripts\activate.bat python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q reportlab pymupdf pillow requests
python kdp_agent.py make --count 2
start "" kdp_out
pause
