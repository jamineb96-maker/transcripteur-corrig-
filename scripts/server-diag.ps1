[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:5000'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

Write-Host '=== Diagnostic serveur ===' -ForegroundColor Cyan
Write-Host "Date     : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "OS       : $([System.Environment]::OSVersion)"
Write-Host "API Base : $BaseUrl"

if (Test-Path $venvPython) {
    $pythonVersion = & $venvPython -c "import sys;print(sys.version.replace('\n',' '))"
    Write-Host "Python   : $pythonVersion"
    try {
        $flaskVersion = & $venvPython -c "import flask;print(flask.__version__)"
        Write-Host "Flask    : $flaskVersion"
    } catch {
        Write-Warning 'Flask non disponible dans .venv.'
    }
} else {
    Write-Warning 'Environnement .venv absent.'
}

Write-Host "Variables d’environnement pertinentes :"
foreach ($name in 'FLASK_ENV', 'FLASK_DEBUG', 'PYTHONIOENCODING', 'DEMO_PATIENTS') {
    Write-Host (" - {0}={1}" -f $name, (Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue).Value)
}

Write-Host 'Ports à l’écoute :' -ForegroundColor Cyan
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 5000, 1421 } |
    Select-Object LocalAddress, LocalPort, OwningProcess

Write-Host 'Requêtes HTTP :' -ForegroundColor Cyan
foreach ($path in @('/', '/api/health', '/api/patients')) {
    $url = if ($path -eq '/') { $BaseUrl } else { "$BaseUrl$path" }
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -Method Get -Headers @{ 'Accept' = 'application/json' }
        $length = $response.RawContentLength
        Write-Host ("{0,-16} {1,5} {2,8} octets" -f $path, [int]$response.StatusCode, $length)
    } catch {
        Write-Host ("{0,-16} ERREUR {1}" -f $path, $_.Exception.Message) -ForegroundColor Red
    }
}
