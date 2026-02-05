@echo off
chcp 65001 > nul
title Redémarrage EAR

echo Arrêt de l'assistant vocal...
taskkill /f /im python.exe 2>nul
taskkill /f /im pythonw.exe 2>nul

timeout /t 2 /nobreak >nul

cd /d "%~dp0.."
echo Démarrage du nouvel assistant...
python ear.py --gui
exit