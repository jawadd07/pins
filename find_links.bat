@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat python -m venv .venv
call .venv\Scripts\activate.bat
python add_products.py --openlinks
echo.
echo Each tab: click best product, copy address bar URL, paste in links.txt after the name, save.
pause
