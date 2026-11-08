@echo off
cd /d "%~dp0"
if exist keys.bat call keys.bat
if not exist .venv\Scripts\activate.bat python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
python add_products.py --setlinks links.txt
python add_products.py --import picks.txt
python add_products.py --digital digital.txt
if defined GEMINI_API_KEY (python add_products.py --ideas) else (python add_products.py)
call run.bat
