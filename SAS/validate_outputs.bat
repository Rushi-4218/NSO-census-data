@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% "%~dp0validate_outputs.py" --outputs "%~dp0outputs" --dictionary "%~dp0config\client_schema_fallback.csv"
exit /b %errorlevel%
