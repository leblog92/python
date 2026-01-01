@echo off
:start
set /p url="Enter URL: "
yt-dlp --extract-audio --audio-format mp3 %url%
pause
goto :start
