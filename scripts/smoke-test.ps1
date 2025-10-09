[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:1421'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Status {
    param([string]$Label, [System.Net.HttpStatusCode]$Code, [int]$Length)
    Write-Host ("{0,-18} {1,5} {2,8} octets" -f $Label, [int]$Code, $Length)
}

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

Write-Host '=== Smoke test ===' -ForegroundColor Cyan
Write-Host "OS        : $([System.Environment]::OSVersion)"
if (Test-Path $venvPython) {
    $pythonVersion = & $venvPython -c "import sys;print(sys.version.replace('\n',' '))"
    Write-Host "Python    : $pythonVersion"
    try {
        $flaskVersion = & $venvPython -c "import flask;print(flask.__version__)"
        Write-Host "Flask     : $flaskVersion"
    } catch {
        Write-Warning 'Flask introuvable dans l’environnement.'
    }
} else {
    Write-Warning 'Environnement virtuel non détecté.'
}

$paths = @(
    @{ Label = 'GET /'; Url = $BaseUrl },
    @{ Label = 'GET /api/health'; Url = "$BaseUrl/api/health" },
    @{ Label = 'GET /api/patients'; Url = "$BaseUrl/api/patients" },
    @{ Label = 'GET /api/journal'; Url = "$BaseUrl/api/journal-critique/prompts" },
    @{ Label = 'GET /api/documents'; Url = "$BaseUrl/api/documents-aide/context?patient=nelle" },
    @{ Label = 'GET /api/invoices'; Url = "$BaseUrl/api/invoices/diagnostics" },
    @{ Label = 'GET /api/library'; Url = "$BaseUrl/api/library/search?q=demo&limit=3" }
)

foreach ($item in $paths) {
    try {
        $response = Invoke-WebRequest -Uri $item.Url -UseBasicParsing -Method Get -Headers @{ 'Accept' = 'application/json' }
        Write-Status $item.Label $response.StatusCode ($response.RawContentLength)
    } catch {
        Write-Host ("{0,-18} ERREUR {1}" -f $item.Label, $_.Exception.Message) -ForegroundColor Red
    }
}
