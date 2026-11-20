@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (set "INPUT=%~dp0INPUT") else (set "INPUT=%~1")
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% "%~dp0run_pipeline.py" --inputs "%INPUT%" --round all --no-wide --reuse-cache-only
exit /b %errorlevel%
