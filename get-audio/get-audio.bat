@echo off
:start
set /p url="Enter URL: "
set "download_dir=C:\Users\FOR5\Music\"

REM Créer le dossier s'il n'existe pas
if not exist "%download_dir%" mkdir "%download_dir%"

REM Se déplacer dans le dossier de destination
cd /d "%download_dir%"

REM Télécharger (sera directement dans le dossier courant)
yt-dlp --extract-audio --audio-format mp3 --ffmpeg-location "C:\ffmpeg\bin\ffmpeg.exe" %url%

REM Revenir au répertoire original et ouvrir le dossier
explorer "%download_dir%"
pause
goto :start