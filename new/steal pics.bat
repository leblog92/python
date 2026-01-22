@echo off
:loop
set /p url="Enter URL: "
gallery-dl "%url%"
goto :loop
