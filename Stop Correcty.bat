@echo off
rem Stops the copy of Correcty that is running in the background.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Correcty is not installed yet.
  "%SystemRoot%\System32\timeout.exe" /t 3 /nobreak >nul 2>&1
  exit /b 0
)
".venv\Scripts\python.exe" app.py --stop
"%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul 2>&1
