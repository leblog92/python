@echo off
:start
set /p url="Enter URL: "
yt-dlp --extract-audio --audio-format mp3 --ffmpeg-location "C:\ffmpeg\bin\ffmpeg.exe" %url%
pause
goto :start