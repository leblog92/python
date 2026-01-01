@echo off
chcp 65001 > nul
title Programme d'extinction automatique
color 0A

:menu
cls
echo ===============================================
echo    PROGRAMME D'EXTINCTION AUTOMATIQUE
echo ===============================================
echo.
echo Choisissez le délai avant l'extinction :
echo.
echo    1 - 1 heure
echo    2 - 2 heures
echo    3 - 3 heures
echo    4 - 4 heures
echo    5 - Annuler une extinction programmée
echo    6 - Quitter
echo.
set /p choix="Votre choix (1-6) : "

if "%choix%"=="1" goto une_heure
if "%choix%"=="2" goto deux_heures
if "%choix%"=="3" goto trois_heures
if "%choix%"=="4" goto quatre_heures
if "%choix%"=="5" goto annuler
if "%choix%"=="6" goto quitter

echo.
echo Choix invalide ! Appuyez sur une touche pour recommencer...
pause > nul
goto menu

:une_heure
set /a secondes=3600
goto programmer

:deux_heures
set /a secondes=7200
goto programmer

:trois_heures
set /a secondes=10800
goto programmer

:quatre_heures
set /a secondes=14400
goto programmer

:programmer
cls
echo.
echo Extinction programmee dans %choix% heure(s)...
echo.
echo L'ordinateur s'eteindra a %time% + %choix% heure(s)
echo.
echo Pour annuler : executez ce programme et choisissez l'option 5
echo.
shutdown /s /f /t %secondes%
echo.
set /p continuer="Appuyez sur Entree pour retourner au menu..."
goto menu

:annuler
cls
echo.
shutdown /a
echo L'extinction programmee a ete annulee.
echo.
set /p continuer="Appuyez sur Entree pour retourner au menu..."
goto menu

:quitter
cls
echo.
echo Au revoir !
echo.
timeout /t 2 > nul
exit