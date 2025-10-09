@echo off
setlocal
cd /d "%~dp0"

set "venv_created="
if not exist .venv\Scripts\activate.bat (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo(
    echo Failed to create virtual environment.
    pause
    exit /b %errorlevel%
  )
  set "venv_created=1"
)

call .venv\Scripts\activate.bat
if errorlevel 1 (
  echo(
  echo Unable to activate virtual environment.
  pause
  exit /b %errorlevel%
)

python -m pip install --upgrade pip
if errorlevel 1 (
  echo(
  echo Failed to upgrade pip.
  pause
  exit /b %errorlevel%
)

pip install -r requirements.txt
if errorlevel 1 (
  echo(
  echo Dependency installation failed.
  pause
  exit /b %errorlevel%
)

python -m compileall server
if errorlevel 1 (
  echo(
  echo Compilation failed.
  pause
  exit /b %errorlevel%
)

set PORT=1421
set FLASK_ENV=production
python server.py
if errorlevel 1 (
  echo(
  echo Server exited with code %errorlevel%
  pause
  exit /b %errorlevel%
)

exit /b 0
