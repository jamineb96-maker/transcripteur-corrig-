<#
    Script PowerShell de test rapide (smoke test) pour l'API.
    Il exécute trois requêtes HTTP et affiche un résumé coloré
    indiquant le succès ou l'échec de chaque étape.
#>

[CmdletBinding()]
param(
    [string]$BaseUrl
)

$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
Set-Location -Path $PSScriptRoot

function Join-Url {
    param(
        [string]$Base,
        [string]$Path
    )

    if ($null -eq $Base -or $Base.Trim() -eq '') {
        return $Path
    }

    $trimmedBase = $Base.TrimEnd('/')
    $trimmedPath = $Path.TrimStart('/')
    return "$trimmedBase/$trimmedPath"
}

if (-not $BaseUrl) {
    $port = if ($env:APP_PORT) { $env:APP_PORT } else { '1421' }
    $BaseUrl = "http://127.0.0.1:$port"
}

Write-Host "Tests de fumée sur $BaseUrl" -ForegroundColor Cyan

$results = @()

function Invoke-SmokeRequest {
    param(
        [string]$Label,
        [string]$Url,
        [ScriptBlock]$Projector
    )

    $result = [ordered]@{
        Label = $Label
        Url = $Url
        Success = $false
        StatusCode = $null
        Detail = $null
    }

    Write-Host "\n$Label ($Url)" -ForegroundColor DarkCyan

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -ErrorAction Stop
        $projection = & $Projector $response
        if ($projection) {
            $projection | Format-Table -AutoSize
        }
        $result.Success = $true
        $result.StatusCode = $response.StatusCode
        $result.Detail = $projection
    } catch {
        $statusCode = $null
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            try {
                $statusCode = [int]$_.Exception.Response.StatusCode
            } catch {
                $statusCode = $null
            }
        }
        Write-Warning "Requête échouée : $($_.Exception.Message)"
        $result.Success = $false
        $result.StatusCode = $statusCode
        $result.Detail = $_.Exception.Message
    }

    return [PSCustomObject]$result
}

$homeUrl = Join-Url -Base $BaseUrl -Path '/'
$healthUrl = Join-Url -Base $BaseUrl -Path 'api/health'
$patientsUrl = Join-Url -Base $BaseUrl -Path 'api/patients'

$results += Invoke-SmokeRequest -Label 'Page d\'accueil' -Url $homeUrl -Projector {
    param($response)
    [PSCustomObject]@{
        StatusCode = $response.StatusCode
        ContentLength = $response.RawContentLength
    }
}

$results += Invoke-SmokeRequest -Label 'Santé API' -Url $healthUrl -Projector {
    param($response)
    $body = if ($response.Content.Length -gt 120) {
        $response.Content.Substring(0, 120)
    } else {
        $response.Content
    }
    [PSCustomObject]@{
        StatusCode = $response.StatusCode
        Body = $body
    }
}

$results += Invoke-SmokeRequest -Label 'Patients API' -Url $patientsUrl -Projector {
    param($response)
    [PSCustomObject]@{
        StatusCode = $response.StatusCode
        ContentLength = $response.RawContentLength
    }
}

Write-Host "\nRésumé" -ForegroundColor Cyan
foreach ($entry in $results) {
    $color = if ($entry.Success) { 'Green' } else { 'Red' }
    $detail = if ($entry.Success) {
        if ($entry.Detail -is [System.Collections.IEnumerable] -and -not ($entry.Detail -is [string])) {
            ($entry.Detail | Format-List | Out-String).Trim()
        } else {
            [string]$entry.Detail
        }
    } else {
        $entry.Detail
    }
    $statusText = if ($entry.StatusCode) { "code $($entry.StatusCode)" } else { "aucun code" }
    Write-Host (" - {0} : {1} ({2})" -f $entry.Label, (if ($entry.Success) { 'succès' } else { 'échec' }), $statusText) -ForegroundColor $color
    if ($detail) {
        Write-Host "   -> $detail" -ForegroundColor $color
    }
}

if ((@($results | Where-Object { $_.Success })).Count -eq $results.Count) {
    Write-Host "\nTous les tests de fumée sont passés." -ForegroundColor Green
} else {
    Write-Warning "\nUn ou plusieurs tests ont échoué. Consultez les détails ci-dessus."
}
