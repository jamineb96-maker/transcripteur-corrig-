@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if exist requirements.txt pip install -r requirements.txt
set PORT=1421
set FLASK_DEBUG=1
python server.py
echo.
echo --- Press any key to exit ---
pause >nul
