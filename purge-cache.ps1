<#
    Script PowerShell pour purger les caches de l'application.
    Il supprime les répertoires et fichiers temporaires courants
    puis exécute le script static/unregister-sw.js avec Node.js ou
    Python lorsqu'il est présent.
#>

[CmdletBinding()]
param()

$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
Set-Location -Path $PSScriptRoot

function Test-CommandExists {
    param([string]$Name)
    try {
        Get-Command $Name -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-IsExcluded {
    param([string]$Path)
    $exclusions = @('.git', '.venv')
    foreach ($entry in $exclusions) {
        if ($Path -like "*${entry}*") {
            return $true
        }
    }
    return $false
}

Write-Host "Purge des caches applicatifs..." -ForegroundColor Cyan

$removedItems = @()

$namedDirectories = @(
    'client/dist',
    'client/.svelte-kit',
    'client/.cache',
    'node_modules/.cache',
    'static/.cache'
)

foreach ($relative in $namedDirectories) {
    $fullPath = Join-Path $PSScriptRoot $relative
    if (Test-Path $fullPath) {
        try {
            Remove-Item -Path $fullPath -Recurse -Force -ErrorAction Stop
            $removedItems += $relative
            Write-Host " - Supprimé : $relative" -ForegroundColor DarkGray
        } catch {
            Write-Warning "Impossible de supprimer $relative : $($_.Exception.Message)"
        }
    }
}

$cacheDirNames = @('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.parcel-cache')
Get-ChildItem -Path $PSScriptRoot -Recurse -Force -Directory -ErrorAction SilentlyContinue |
    Where-Object { $cacheDirNames -contains $_.Name -and -not (Test-IsExcluded -Path $_.FullName) } |
    ForEach-Object {
        try {
            $relative = Resolve-Path -Path $_.FullName -Relative
            Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction Stop
            $removedItems += $relative
            Write-Host " - Supprimé : $relative" -ForegroundColor DarkGray
        } catch {
            Write-Warning "Impossible de supprimer $($_.FullName) : $($_.Exception.Message)"
        }
    }

Get-ChildItem -Path $PSScriptRoot -Recurse -Force -File -Include '*.pyc','*.pyo','*.pyd' -ErrorAction SilentlyContinue |
    Where-Object { -not (Test-IsExcluded -Path $_.DirectoryName) } |
    ForEach-Object {
        try {
            Remove-Item -Path $_.FullName -Force -ErrorAction Stop
        } catch {
            Write-Warning "Impossible de supprimer $($_.FullName) : $($_.Exception.Message)"
        }
    }

if ($removedItems.Count -eq 0) {
    Write-Host "Aucun cache spécifique n'a été supprimé." -ForegroundColor Yellow
}

$swCandidates = @(
    Join-Path $PSScriptRoot 'static/unregister-sw.js',
    Join-Path $PSScriptRoot 'client/unregister-sw.js',
    Join-Path $PSScriptRoot 'client/static/unregister-sw.js'
) | Where-Object { Test-Path $_ }

if ($swCandidates.Count -gt 0) {
    $swScript = $swCandidates[0]
    $relativeScript = Resolve-Path -Path $swScript -Relative
    $executor = $null
    if (Test-CommandExists 'node') {
        $executor = 'node'
    } elseif (Test-CommandExists 'python') {
        $executor = 'python'
    }

    if ($null -ne $executor) {
        Write-Host "Exécution de $executor $relativeScript" -ForegroundColor Cyan
        try {
            & $executor $swScript
        } catch {
            Write-Warning "Erreur lors de l'exécution de $executor $relativeScript : $($_.Exception.Message)"
        }
    } else {
        Write-Warning "Node.js ou Python introuvable pour exécuter $relativeScript."
    }
} else {
    Write-Host "Aucun script unregister-sw à exécuter." -ForegroundColor DarkGray
}

Write-Host "Purge terminée." -ForegroundColor Green
