@echo off
cd /d "%~dp0"
rmdir /s /q docs 2>nul
rmdir /s /q exports 2>nul
del state.db 2>nul
echo Test data deleted.
pause
