@echo off
setlocal
set "ROOT=%~dp0"
if not "%FAB_PYTHON%"=="" (
  set "PYTHON_EXE=%FAB_PYTHON%"
  goto :run_native
)
if exist "%ROOT%.venv-win\Scripts\python.exe" (
  set "PYTHON_EXE=%ROOT%.venv-win\Scripts\python.exe"
  goto :run_native
)
if exist "%ROOT%.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"
  goto :run_native
)
if not "%VIRTUAL_ENV%"=="" if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
  set "PYTHON_EXE=%VIRTUAL_ENV%\Scripts\python.exe"
  goto :run_native
)
if not "%CONDA_PREFIX%"=="" if exist "%CONDA_PREFIX%\python.exe" (
  set "PYTHON_EXE=%CONDA_PREFIX%\python.exe"
  goto :run_native
)
if not "%FAB_CONDA_ENV%"=="" if defined CONDA_EXE (
  "%CONDA_EXE%" run --no-capture-output -n "%FAB_CONDA_ENV%" python "%ROOT%run.py" %*
  goto :end
)
where python >nul 2>&1 && (
  set "PYTHON_EXE=python"
  goto :run_native
)
py -3 "%ROOT%run.py" %*
goto :end

:run_native
"%PYTHON_EXE%" "%ROOT%run.py" %*

:end
exit /b %ERRORLEVEL%
