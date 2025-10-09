[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $projectRoot

Write-Host '=== Reconstruction des assets ===' -ForegroundColor Cyan

if (Test-Path 'package.json') {
    Write-Host 'Installation des dépendances npm…'
    npm install | Write-Output
    if (Test-Path 'package-lock.json') {
        Write-Host 'Build npm…'
        npm run build | Write-Output
    }
} else {
    Write-Host 'Aucun bundler npm détecté, vérification des assets existants.'
}

$timestamp = Get-Date -Format 'yyyyMMddHHmmss'
$versionFile = Join-Path 'client' '.asset-version'
Set-Content -Path $versionFile -Value $timestamp -Encoding UTF8
Write-Host "Nouvelle version d’assets : $timestamp" -ForegroundColor Cyan

$assets = @('client/app.js', 'client/styles/base.css', 'client/styles/diagnostics.css')
foreach ($asset in $assets) {
    if (Test-Path $asset) {
        $info = Get-Item $asset
        Write-Host (" - {0} ({1} octets)" -f $asset, $info.Length)
    } else {
        Write-Warning "$asset introuvable."
    }
}
