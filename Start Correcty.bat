@echo off
rem Starts Correcty in the background and opens it in your browser.
rem First run: creates a private Python environment (.venv) and installs Flask.
setlocal
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_PYW=.venv\Scripts\pythonw.exe"

if not exist "%VENV_PY%" (
  echo Setting up Correcty for the first time. This takes about a minute...
  call :find_python
  if not defined PY goto :no_python
  %PY% -m venv .venv
  if errorlevel 1 goto :setup_failed
)

rem Install dependencies on first run, and again whenever requirements.txt changes.
fc /b requirements.txt .venv\requirements.installed >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies...
  "%VENV_PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 goto :setup_failed
  copy /y requirements.txt .venv\requirements.installed >nul
)

start "" "%VENV_PYW%" "%~dp0app.py" --open-browser
exit /b 0

:find_python
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
exit /b 0

:no_python
echo.
echo Python 3.10 or newer is needed and wasn't found.
echo Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
echo then double-click this file again.
pause
exit /b 1

:setup_failed
echo.
echo Setup didn't finish. Check your internet connection and try again.
echo If it keeps failing, delete the .venv folder and run this file again.
pause
exit /b 1
