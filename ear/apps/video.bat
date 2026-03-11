@echo off
chcp 65001 >nul
echo Capture video from internet
echo Compatible with YouTube, Vimeo, TikTok, Twitter, Instagram, Reddit, and hundreds of other platforms
echo.

:start
REM Récupérer directement le contenu du presse-papiers
echo Checking clipboard for URL...
set url=
for /f "delims=" %%i in ('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [Windows.Forms.Clipboard]::GetText()"') do (
    set "url=%%i"
)

if defined url (
    echo Found in clipboard: %url%
    echo Using content from clipboard...
    goto download
) else (
    echo Nothing found in clipboard.
    goto ask_url
)

:ask_url
set /p url="Enter URL (or leave blank to quit): "
if "%url%"=="" (
    echo No URL provided. Exiting.
    pause
    exit /b
)

:download
set "download_dir=%USERPROFILE%\Videos\"

REM Create directory if it doesn't exist
if not exist "%download_dir%" mkdir "%download_dir%"

REM Move to download directory
cd /d "%download_dir%"

echo Downloading from: %url%
echo Saving to: %download_dir%
echo.

REM Download the audio - sans validation
yt-dlp "%url%" -P "%USERPROFILE%/Videos" --legacy-server-connect -U --hls-prefer-ffmpeg

if errorlevel 1 (
    echo Download failed. Please check the URL and try again.
    pause
    goto :start
)

REM Open the download folder
explorer "%download_dir%"

echo.
echo Download completed!
echo.
exit