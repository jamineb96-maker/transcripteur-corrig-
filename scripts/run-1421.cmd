@echo off
setlocal
set SCRIPT_DIR=%~dp0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run-1421.ps1" %*
if errorlevel 1 (
  echo.
  echo Le serveur s'est terminé avec une erreur.
  pause
) else (
  echo.
  echo Serveur arrêté.
  pause
)
endlocal
