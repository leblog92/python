@echo off
echo Remote Sound Controller
echo =======================
echo.
if "%1"=="" (
    echo Usage: %0 [server_ip] [command]
    echo.
    echo Commands:
    echo   play [filepath]  - Play sound file
    echo   tts [text]       - Speak text
    echo   ping             - Test connection
    goto :end
)

if "%2"=="play" (
    python sound_client.py %1 play "%3"
) else if "%2"=="tts" (
    python sound_client.py %1 tts "%3"
) else if "%2"=="ping" (
    python sound_client.py %1 ping
) else (
    echo Unknown command: %2
)

:end
pause