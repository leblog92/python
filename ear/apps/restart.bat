@echo off
chcp 65001 > nul
title Redémarrage EAR

echo Arrêt de l'assistant vocal...
taskkill /f /im python.exe 2>nul
taskkill /f /im pythonw.exe 2>nul

timeout /t 2 /nobreak >nul

cd /d "%~dp0.."
start /B pythonw.exe ear.py --gui >nul 2>&1
exit