
@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
 
REM ============================================================
REM   P.I.G.E. - Lancement du programme
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
 
echo ============================================================
echo   P.I.G.E. - Programme Intelligent de Guet et d'Ecoute
echo ============================================================
echo.
echo   Fermez cette fenetre ^(ou Ctrl+C^) pour arreter le programme.
echo.
 
venv\Scripts\python.exe pige.py
 
echo.
echo [INFO] Le programme s'est arrete.
pause