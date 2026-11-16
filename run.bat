@echo off
cd /d "%~dp0"
if exist keys.bat call keys.bat
rem FIRST TIME on a fresh folder: connect to the existing GitHub repo and restore old pages (so old pins keep working)
if not exist .git (
  git init
  git branch -M main
  git remote add origin https://github.com/jawadd07/pins.git
  git fetch origin main
  git reset origin/main
  git checkout -- docs
)
if not exist .venv\Scripts\activate.bat python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
python pinterest_agent.py run
if not exist docs\index.html > docs\index.html echo ^<h1^>pins^</h1^>
> .gitignore echo .venv*/
>> .gitignore echo state.db
>> .gitignore echo exports/
>> .gitignore echo __pycache__/
>> .gitignore echo keys.bat
>> .gitignore echo used_photos.txt
if not exist .git git init
git branch -M main
git remote get-url origin >nul 2>&1 || git remote add origin https://github.com/jawadd07/pins.git
git add .
git -c user.name=jawadd07 -c user.email=jawadd07@users.noreply.github.com commit -m "pins"
git push -u origin main
echo.
echo DONE. Upload CSV from exports folder to Pinterest.
pause
