[CmdletBinding()]
param(
    [string]$Url = 'http://127.0.0.1:5000/?debug=1'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Find-Firefox {
    $candidates = @()
    foreach ($base in @($env:PROGRAMFILES, $env:PROGRAMFILES(x86), $env:LOCALAPPDATA)) {
        if ($null -ne $base -and $base -ne '') {
            $candidates += Join-Path $base 'Mozilla Firefox\firefox.exe'
        }
    }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

$firefox = Find-Firefox
if (-not $firefox) {
    throw 'Firefox introuvable sur ce poste.'
}

$profileRoot = Join-Path ([System.IO.Path]::GetTempPath()) "assist-cli-profile-$([System.Guid]::NewGuid())"
New-Item -Path $profileRoot -ItemType Directory | Out-Null

& $firefox -CreateProfile "assist-cli $profileRoot" | Out-Null

$snippet = @"
(async () => {
  const registrations = navigator.serviceWorker && (await navigator.serviceWorker.getRegistrations());
  console.group('[assist-cli] Diagnostic client');
  console.log('navigator.serviceWorker', registrations);
  console.log('localStorage', Object.assign({}, window.localStorage));
  console.log('sessionStorage', Object.assign({}, window.sessionStorage));
  console.groupEnd();
})();
"@

$snippetPath = Join-Path $profileRoot 'client-diag.js'
Set-Content -Path $snippetPath -Value $snippet -Encoding UTF8

Write-Host "==> Lancement de Firefox avec un profil vierge" -ForegroundColor Cyan
Start-Process -FilePath $firefox -ArgumentList @('-new-instance', '-profile', $profileRoot, '-devtools', $Url)

Write-Host "Console : utilisez le raccourci Ctrl+Shift+K, puis exécutez :" -ForegroundColor Cyan
Write-Host "`n`n$(Get-Content -Path $snippetPath -Raw)`n" -ForegroundColor Yellow
Write-Host "Le profil temporaire est stocké dans $profileRoot (sera supprimé manuellement)."
