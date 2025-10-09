#!/bin/bash

# Ce script exécute l'ensemble des tests unitaires, d'intégration et end‑to‑end.
# Assurez‑vous d'avoir installé les dépendances Python et Node (Playwright)
# avant de lancer ce script.

set -e

echo "[tests] Exécution des tests Python avec pytest…"
pytest -q

echo "[tests] Exécution des tests end‑to‑end avec Playwright…"
if command -v npx >/dev/null 2>&1; then
  npx playwright install chromium > /dev/null 2>&1 || true
  npx playwright test tests/e2e
else
  echo "Playwright n'est pas installé.  Installez‑le via npm pour exécuter les tests E2E."
fi
echo "[tests] Tous les tests ont été exécutés."