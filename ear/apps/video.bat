@echo off
:start
set /p url="Enter URL: "
yt-dlp "%url%" -P "d:/downloads" --legacy-server-connect -U --hls-prefer-ffmpeg --cookies d:/python/cookies.txt
goto :start
