# Audit du module « Documents d'aide »

## Inventaire des fichiers existants

- `client/tabs/documents_aide/index.js` — module principal côté client.
- `client/tabs/documents_aide/view.html` — vue canonique (synchronisée avec les sélecteurs JS).
- `client/tabs/documents_aide/style.css` — feuille de style officielle injectée dynamiquement.
- `client/static/tabs/documents_aide/view.html` — **supprimée** après migration.
- `client/static/tabs/documents_aide/style.css` — **supprimée** après migration.
- `client/static/tabs/documents_aide/index.js` — **absent** (le module charge bien depuis `client/tabs`).
- `client/app.js` — routeur qui mappe l'onglet `documents` vers `documents_aide`.

Côté serveur, plusieurs templates et routes `documents_aide` sont définis sous `server/` mais ne participent pas à l'affichage du tab SPA.

## Importations et chemins dynamiques

- `client/app.js` construit l'URL `/static/tabs/documents_aide/index.js` via `withAssetVersion()`.
- `client/tabs/documents_aide/index.js` charge la vue et la feuille de style avec les constantes :
  - `VIEW_URL = '/static/tabs/documents_aide/view.html'`
  - `STYLE_URL = '/static/tabs/documents_aide/style.css'`
- Toutes les requêtes API du module ciblent le préfixe `/api/documents-aide/...`.

## Sélecteurs attendus par le module

Le module référence les sélecteurs suivants lors de l'initialisation :

- `#docAidePatientSelect`
- `#docAideNewButton`
- `#docAideCatalogGrid`
- `#docAideSearch`
- `#docAideCategoryFilter`
- `#docAideHistoryBody`
- `#docAideRefreshHistory`
- `#docAideProfileBlock`
- `#docAideSuggestions`
- `#docAideLastNotes`
- `#docAideWizard`
- `#docAideFormContainer`
- `#docAidePreview`
- `#docAideFormat`
- `#docAideGenerate`
- `#docAidePronoun`
- `#docAideGender`
- `#docAideTV`
- `#docAideWizardTitle`
- `.wizard-steps button`

La vue canonique `client/tabs/documents_aide/view.html` expose l’ensemble de ces sélecteurs et le diagnostic `validateTab()` signale tout écart.

## Table de correspondance disque/HTTP

| Asset | Chemin disque actuel | URL HTTP résolue |
| --- | --- | --- |
| Module JS | `client/tabs/documents_aide/index.js` | `/static/tabs/documents_aide/index.js` |
| Vue HTML | `client/tabs/documents_aide/view.html` | `/static/tabs/documents_aide/view.html` |
| CSS | `client/tabs/documents_aide/style.css` | `/static/tabs/documents_aide/style.css` |

> **Constat** : les assets HTML/CSS servis aujourd'hui proviennent du doublon `client/static/...` tandis que le JS est chargé depuis `client/tabs/...`, générant une incohérence structurelle.

## Points de vigilance

1. S'assurer qu'aucun doublon `client/static/tabs/documents_aide/` ne réapparaît (script `scripts/validate_tabs.py`).
2. Conserver la parité stricte entre la vue canonique et les sélecteurs attendus par `index.js`.
3. Maintenir un seul `data-tab` côté routeur (`section[data-tab="documents_aide"]`).
4. Le hash d'assets agrège désormais `index.js`, `view.html` et `style.css` pour invalider le cache.
5. Les diagnostics (`validateTab`) doivent rester activés en mode développement pour pointer les manquements.
