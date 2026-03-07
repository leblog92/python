@echo off
cd /d "%~dp0"
echo Starting EAR Voice Assistant...
python ear.py --gui
if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to exit.
    pause > nul
)