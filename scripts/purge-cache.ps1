[CmdletBinding()]
param(
    [switch]$SkipRestart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Remove-DirSafe {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Clear-PythonCaches {
    param([string]$Root)
    if (-not (Test-Path -LiteralPath $Root)) { return }
    Write-Step "Suppression des __pycache__ dans $Root"
    Get-ChildItem -LiteralPath $Root -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
}

function Clear-ChromiumCaches {
    param([string]$Root)
    if (-not (Test-Path -LiteralPath $Root)) { return }
    Write-Step "Nettoyage des caches Chromium dans $Root"
    $profiles = Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq 'Default' -or $_.Name -like 'Profile *' }
    foreach ($profile in $profiles) {
        Remove-DirSafe (Join-Path $profile.FullName 'Service Worker')
        Remove-DirSafe (Join-Path $profile.FullName 'Cache')
        Remove-DirSafe (Join-Path $profile.FullName 'Code Cache')
        Remove-DirSafe (Join-Path $profile.FullName 'GPUCache')
    }
}

function Clear-FirefoxCaches {
    param([string]$Root)
    if (-not (Test-Path -LiteralPath $Root)) { return }
    Write-Step "Nettoyage des caches Firefox dans $Root"
    Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-DirSafe (Join-Path $_.FullName 'cache2')
            Remove-DirSafe (Join-Path $_.FullName 'startupCache')
            Remove-DirSafe (Join-Path $_.FullName 'OfflineCache')
            Remove-Item -LiteralPath (Join-Path $_.FullName 'serviceworker.txt') -Force -ErrorAction SilentlyContinue
        }
}

function Remove-ServiceWorkerFiles {
    param([string]$ProjectRoot)
    $swCandidates = @(
        (Join-Path $ProjectRoot 'client\static\service-worker.js'),
        (Join-Path $ProjectRoot 'client\service-worker.js')
    )
    foreach ($candidate in $swCandidates) {
        if (Test-Path -LiteralPath $candidate) {
            Write-Step "Suppression du service worker $candidate"
            Remove-Item -LiteralPath $candidate -Force -ErrorAction SilentlyContinue
        }
    }
}

Write-Step 'Purge des caches locaux'
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Clear-PythonCaches $projectRoot
Remove-ServiceWorkerFiles $projectRoot

$chromeRoot = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data'
$edgeRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data'
$firefoxRoot = Join-Path $env:APPDATA 'Mozilla\Firefox\Profiles'

Clear-ChromiumCaches $chromeRoot
Clear-ChromiumCaches $edgeRoot
Clear-FirefoxCaches $firefoxRoot

if (-not $SkipRestart) {
    Write-Step 'Relance du serveur (port 1421)'
    & (Join-Path $PSScriptRoot 'run-1421.ps1')
}
