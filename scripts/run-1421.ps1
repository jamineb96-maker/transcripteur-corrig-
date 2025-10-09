[CmdletBinding()]
param(
    [switch]$NoInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$venvDir = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$requirements = Join-Path $projectRoot 'requirements.txt'

function Invoke-VenvCreation {
    Write-Host '==> Création de l’environnement virtuel (.venv)' -ForegroundColor Cyan
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $venvDir
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $venvDir
    } else {
        throw 'Python 3 est requis pour créer le virtualenv (.venv).'
    }
}

function Invoke-Install {
    if ($NoInstall) { return }
    if (-not (Test-Path -LiteralPath $requirements)) { return }
    Write-Host '==> Installation des dépendances (pip install -r requirements.txt)' -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip > $null
    & $venvPython -m pip install -r $requirements
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Invoke-VenvCreation
}

Invoke-Install

$env:PORT = '1421'
$env:HOST = '127.0.0.1'
$env:FLASK_DEBUG = '1'

Write-Host '==> Démarrage du serveur sur http://127.0.0.1:1421' -ForegroundColor Cyan
try {
    & $venvPython (Join-Path $projectRoot 'server.py')
} catch {
    Write-Error $_
    throw
} finally {
    try {
        Read-Host 'Appuyez sur Entrée pour fermer la fenêtre'
    } catch {
        # Ignorer si non interactif
    }
}
