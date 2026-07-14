@echo off
setlocal

where wsl.exe >nul 2>&1
if errorlevel 1 (
    echo WSL is required to run Fab Insight Agent.
    pause
    exit /b 1
)

cd /d "%~dp0"
wsl.exe --cd "%~dp0" bash -lc "exec ./run.sh"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
