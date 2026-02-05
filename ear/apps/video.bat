@echo off
echo Capture video from internet
echo Compatible with YouTube, Vimeo, TikTok, Twitter, Instagram, Reddit, and hundreds of other platforms
:start
set /p url="Enter URL: "
yt-dlp "%url%" -P "%USERPROFILE%/downloads" --legacy-server-connect -U --hls-prefer-ffmpeg
goto :start