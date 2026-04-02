@echo off
chcp 65001 > nul
title EAR Restart

REM restart.bat lives in apps\ — go up one level to reach ear's root folder
cd /d "%~dp0.."

echo Stopping EAR...

if exist "ear.pid" (
    set /p EAR_PID=<ear.pid
    taskkill /f /pid %EAR_PID% >nul 2>&1
    del "ear.pid" >nul 2>&1
    echo Process %EAR_PID% terminated.
) else (
    echo ear.pid not found - EAR may not be running.
)

timeout /t 2 /nobreak >nul

echo Starting EAR...
start /B pythonw.exe ear.py >nul 2>&1
exit