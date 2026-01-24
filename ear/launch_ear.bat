@echo off
REM Change le répertoire courant vers celui où se trouve le batch
cd /d "%~dp0"
echo Répertoire courant: %cd%
python ear.py
pause