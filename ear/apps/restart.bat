@echo off
chcp 65001 > nul
title Redémarrage Ear Assistant

echo ========================================
echo  Redémarrage de l'assistant vocal EAR
echo ========================================

REM Arrêter le processus ear.py s'il est en cours d'exécution
echo Arrêt de l'application en cours...
taskkill /f /im python.exe 2>nul
taskkill /f /im pythonw.exe 2>nul
timeout /t 2 /nobreak >nul

REM Se déplacer dans le répertoire parent
cd /d "%~dp0.."

echo Démarrage de EAR...
echo.

REM Options de démarrage
REM Utilisez --gui pour l'interface graphique (défaut)
REM Ou utilisez --console pour le mode console

if "%1"=="" (
    REM Mode graphique par défaut
    echo Mode: Interface Graphique
    echo.
    python ear.py --gui
) else if "%1"=="--gui" (
    echo Mode: Interface Graphique
    echo.
    python ear.py --gui
) else if "%1"=="--console" (
    echo Mode: Console
    echo.
    python ear.py
) else if "%1"=="--help" (
    echo Options disponibles:
    echo   --gui     : Lance avec interface graphique (défaut)
    echo   --console : Lance en mode console
    echo   --help    : Affiche cette aide
    pause
    exit /b 0
) else (
    echo Option inconnue: %1
    echo Utilisez --help pour voir les options disponibles
    pause
    exit /b 1
)

if errorlevel 1 (
    echo.
    echo Une erreur s'est produite lors du démarrage.
    echo Vérifiez que:
    echo   1. Python est installé
    echo   2. Les dépendances sont installées (pip install -r requirements.txt)
    echo.
    pause
)