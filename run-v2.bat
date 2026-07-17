@echo off
setlocal
set "WINDOWS_ROOT=%~dp0"
set "WINDOWS_ROOT=%WINDOWS_ROOT:~0,-1%"
for /f "usebackq delims=" %%I in (`wsl.exe wslpath -a "%WINDOWS_ROOT%"`) do set "WSL_ROOT=%%I"
if not defined WSL_ROOT (
  echo Unable to resolve the current worktree path in WSL.
  exit /b 1
)
wsl.exe --cd "%WSL_ROOT%" bash ./run-v2.sh
