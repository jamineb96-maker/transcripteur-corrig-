[CmdletBinding()]
param(
    [string]$Python = 'python'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $projectRoot

Write-Step "Racine du projet : $projectRoot"

if (-not (Test-Path '.venv')) {
    Write-Step 'Création de l’environnement virtuel (.venv)'
    & $Python -m venv .venv
}

$venvPython = Join-Path '.venv' 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    throw "Python introuvable dans .venv."
}

Write-Step 'Mise à jour de pip'
& $venvPython -m pip install --upgrade pip | Write-Output

if (Test-Path 'requirements.txt') {
    Write-Step 'Installation des dépendances requirements.txt'
    & $venvPython -m pip install -r requirements.txt | Write-Output
}

Write-Step 'Configuration des variables d’encodage UTF-8'
[System.Environment]::SetEnvironmentVariable('PYTHONUTF8', '1', 'Process')
[System.Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'Process')

$envFile = Join-Path $projectRoot '.env.dev'
@(
    'FLASK_ENV=development'
    'FLASK_DEBUG=1'
) | Set-Content -Path $envFile -Encoding UTF8
Write-Step "Fichier .env.dev généré à $envFile"

$pythonVersion = & $venvPython -c "import sys; print(sys.version)"
Write-Step "Python : $pythonVersion"

try {
    $flaskVersion = & $venvPython -c "import flask; print(flask.__version__)"
    Write-Step "Flask : $flaskVersion"
} catch {
    Write-Warning 'Flask n’est pas installé pour le moment.'
}

Write-Step 'Environnement prêt.'
