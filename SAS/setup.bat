@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python was not found. Install Python 3.10+ and re-run this file.
    exit /b 1
  )
  set "PY=python"
)
%PY% -m pip install --upgrade pip
if errorlevel 1 exit /b 1
%PY% -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 exit /b 1
echo.
echo SETUP COMPLETE
endlocal
