[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $projectRoot

$venvPython = Join-Path '.venv' 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    throw "Virtualenv introuvable. Exécutez scripts\setup-env.ps1 au préalable."
}

$env:FLASK_ENV = 'development'
$env:FLASK_DEBUG = '1'
$env:PYTHONIOENCODING = 'utf-8'

Write-Host "==> Démarrage du serveur Flask (http://127.0.0.1:5000)" -ForegroundColor Cyan
& $venvPython 'server.py' --host '127.0.0.1' --port 5000 --debug
