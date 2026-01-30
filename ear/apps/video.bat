@echo off
:start
set /p url="Enter URL: "
yt-dlp "%url%" -P "%USERPROFILE%/downloads" --legacy-server-connect -U --hls-prefer-ffmpeg
goto :start