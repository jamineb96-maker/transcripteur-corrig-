@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  echo [assist-cli] Virtualenv introuvable. Lancez d'abord scripts\setup-env.ps1.
  exit /b 1
)

set FLASK_ENV=development
set FLASK_DEBUG=1
set PYTHONIOENCODING=utf-8

pushd "%PROJECT_ROOT%"
"%VENV_PY%" server.py --host=127.0.0.1 --port=5000 --debug
set EXITCODE=%ERRORLEVEL%
popd

exit /b %EXITCODE%
