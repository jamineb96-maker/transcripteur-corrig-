#!/usr/bin/env pwsh

# Ce script exécute les tests unitaires, d'intégration et E2E sur Windows.

Write-Host "[tests] Exécution des tests Python avec pytest…"
pytest -q

Write-Host "[tests] Exécution des tests end‑to‑end avec Playwright…"
try {
    npm list -g @playwright/test | Out-Null
    npx playwright install chromium | Out-Null
    npx playwright test tests/e2e
} catch {
    Write-Warning "Playwright n'est pas installé.  Installez-le via npm pour exécuter les tests E2E."
}

Write-Host "[tests] Tous les tests ont été exécutés."