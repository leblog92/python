@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM   P.I.G.E. - Programme Intelligent de Guet et d'Ecoute
REM   Installation automatique : Python 3.12 + dependances
REM   (installation sans droits administrateur)
REM ============================================================

set "PYVER=3.12.10"
set "PYVER_SHORT=Python312"
set "PYEXE_NAME=python-%PYVER%-amd64.exe"
set "PYEXE_URL=https://www.python.org/ftp/python/%PYVER%/%PYEXE_NAME%"
set "INSTALL_DIR=%LocalAppData%\Programs\Python\%PYVER_SHORT%"
set "PYTHON_EXE=%INSTALL_DIR%\python.exe"
set "FOUND=0"

echo ============================================================
echo   P.I.G.E. - Installation de l'environnement
echo   (Programme Intelligent de Guet et d'Ecoute)
echo ============================================================
echo.

cd /d "%~dp0"

REM ── 1) Chercher une installation Python 3.12 deja presente (lanceur "py") ──
where py >nul 2>nul
if !ERRORLEVEL! EQU 0 (
    py -3.12 --version >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        echo [OK] Python 3.12 deja installe, on le reutilise.
        for /f "usebackq tokens=*" %%P in (`py -3.12 -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%P"
        set "FOUND=1"
    )
)

REM ── 2) Sinon, verifier l'emplacement d'installation standard ──
if "!FOUND!"=="0" (
    if exist "%PYTHON_EXE%" (
        echo [OK] Python 3.12 trouve dans "%INSTALL_DIR%"
        set "FOUND=1"
    )
)

REM ── 3) Sinon, telecharger et installer Python 3.12 (utilisateur, sans admin) ──
if "!FOUND!"=="0" (
    echo [INFO] Python 3.12 introuvable - telechargement de %PYEXE_NAME%...
    set "TMP_INSTALLER=%TEMP%\%PYEXE_NAME%"
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%PYEXE_URL%' -OutFile '!TMP_INSTALLER!' } catch { exit 1 }"
    if not exist "!TMP_INSTALLER!" (
        echo [ERREUR] Le telechargement a echoue. Verifiez votre connexion internet
        echo          ou installez Python 3.12 manuellement depuis python.org.
        pause
        exit /b 1
    )

    echo [INFO] Installation de Python %PYVER% ^(utilisateur courant, sans droits admin^)...
    echo        Merci de patienter, cela peut prendre une minute...
    "!TMP_INSTALLER!" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_test=0

    REM Laisser le temps a l'installeur de terminer avant de verifier
    timeout /t 8 /nobreak >nul

    if not exist "%PYTHON_EXE%" (
        echo [ERREUR] L'installation de Python semble avoir echoue.
        echo Vous pouvez relancer l'installeur manuellement :
        echo   "!TMP_INSTALLER!"
        pause
        exit /b 1
    )
    echo [OK] Python %PYVER% installe dans "%INSTALL_DIR%"
)

REM ── 4) Environnement virtuel dedie au projet ──
echo.
echo [INFO] Creation de l'environnement virtuel (dossier venv)...
"%PYTHON_EXE%" -m venv venv
if not exist "venv\Scripts\python.exe" (
    echo [ERREUR] La creation de l'environnement virtuel a echoue.
    pause
    exit /b 1
)

echo [INFO] Mise a jour de pip...
venv\Scripts\python.exe -m pip install --upgrade pip >nul

echo [INFO] Installation des dependances (requirements.txt)...
echo        (flask, opencv-python, numpy, python-dotenv, sounddevice)
venv\Scripts\python.exe -m pip install -r requirements.txt
if !ERRORLEVEL! NEQ 0 (
    echo [ERREUR] L'installation des dependances a echoue. Voir le detail ci-dessus.
    pause
    exit /b 1
)

REM ── 5) Demarrage automatique a l'ouverture de session (sans droits admin) ──
echo.
echo [INFO] Configuration du demarrage automatique...
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "STARTUP_BAT=%STARTUP_DIR%\pige_autostart.bat"
(
    echo @echo off
    echo REM Cree automatiquement par install_pige.bat - ne pas modifier a la main.
    echo REM Pour desactiver le demarrage automatique, supprimez ce fichier.
    echo start "P.I.G.E." /min "%~dp0venv\Scripts\python.exe" "%~dp0pige.py"
) > "%STARTUP_BAT%" 2>nul

if exist "%STARTUP_BAT%" (
    echo [OK] P.I.G.E. se lancera desormais automatiquement a chaque ouverture
    echo      de session Windows ^(fenetre reduite^).
) else (
    echo [ATTENTION] Impossible de configurer le demarrage automatique.
    echo             Vous pouvez toujours lancer P.I.G.E. via run_pige.bat.
)

echo.
echo ============================================================
echo   Installation terminee avec succes !
echo ============================================================
echo.
echo   Pour lancer P.I.G.E. manuellement, double-cliquez sur
echo   run_pige.bat ^(inutile de relancer install_pige.bat^).
echo.

set /p LAUNCH="Lancer P.I.G.E. maintenant ? [O/n] : "
if /i "!LAUNCH!"=="n" goto :fin
echo [INFO] Demarrage dans une fenetre reduite dans la barre des taches...
start "P.I.G.E." /min "%~dp0venv\Scripts\python.exe" "%~dp0pige.py"

:fin
echo.
pause