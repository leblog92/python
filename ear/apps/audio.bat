@echo off
chcp 65001 >nul
echo Capture audio from video
echo Compatible with YouTube, Vimeo, TikTok, Twitter, Instagram, Reddit, and hundreds of other platforms
echo.

:start
REM Check clipboard for URL content
echo Checking clipboard for URL...
set url=
powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $clipText = [Windows.Forms.Clipboard]::GetText(); if ($clipText -match '^https?://[^\s]+$') { Write-Output $clipText }"

if errorlevel 1 (
    echo Could not access clipboard or PowerShell unavailable.
    goto ask_url
)

for /f "delims=" %%i in ('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $clipText = [Windows.Forms.Clipboard]::GetText(); if ($clipText -match \"^https?://[^\s]+$\") { Write-Output $clipText }"') do (
    set "url=%%i"
)

if defined url (
    echo Found URL in clipboard: %url%
    set /p use_clipboard="Use this URL? (Y/N): "
    if /i "%use_clipboard%"=="y" (
        echo Using URL from clipboard...
        goto download
    ) else if /i "%use_clipboard%"=="n" (
        goto ask_url
    ) else (
        echo Invalid choice, please enter manually.
        goto ask_url
    )
) else (
    echo No valid URL found in clipboard.
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
set "download_dir=%USERPROFILE%\Music\"

REM Create directory if it doesn't exist
if not exist "%download_dir%" mkdir "%download_dir%"

REM Move to download directory
cd /d "%download_dir%"

echo Downloading from: %url%
echo Saving to: %download_dir%
echo.

REM Download the audio
yt-dlp --extract-audio --audio-format mp3 --ffmpeg-location "C:\ffmpeg\bin\ffmpeg.exe" "%url%"

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
pause
goto :start