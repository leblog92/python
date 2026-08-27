@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
 
REM ============================================================
REM   P.I.G.E. - Lancement du programme (fenetre reduite)
REM ============================================================
 
if not exist "venv\Scripts\python.exe" (
    echo [ERREUR] Environnement virtuel introuvable dans ce dossier.
    echo.
    echo Lancez d'abord install_pige.bat ^(une seule fois^), il installe
    echo Python et les dependances necessaires.
    echo.
    pause
    exit /b 1
)
 
start "P.I.G.E." /min "%~dp0venv\Scripts\python.exe" "%~dp0pige.py"