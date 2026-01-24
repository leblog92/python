@echo off
echo Capture pictures
echo Compatible with hundreds of platforms
:loop
set /p url="Enter URL: "
gallery-dl "%url%"
goto :loop
