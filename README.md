# Assistant Clinique – Suite Modulaire

Cette suite fournit une base complète et extensible pour un assistant clinique.  Elle repose sur un serveur Flask modulaire et un client web en JavaScript natif.  Les fonctionnalités de génération de textes pré/post‑séance sont complétées par une **librairie interne** de ressources consultables.  Un logo intégré et une interface modernisée rendent l’ensemble agréable à utiliser en mode clair ou sombre.

## Pré‑requis

* **Système** : Windows est recommandé pour utiliser les scripts `.bat` / `.ps1`, mais la structure reste compatible avec Linux/macOS via Python.
* **Python 3.10 ou supérieur** : nécessaire pour créer l’environnement virtuel et exécuter le serveur Flask.

## Démarrage rapide

1. **Ouvrez un terminal** (PowerShell ou `cmd.exe`) dans le dossier du projet.
   > ℹ️ Copiez d'abord le fichier `.env.example` vers `.env` et ajustez `PATIENTS_DIR` pour pointer vers vos données locales.
2. Sur Windows :
   * Double‑cliquez sur `start_server.bat` ou exécutez `./start_server.bat`. Le script crée `.venv` si nécessaire, installe `requirements.txt`, force `PORT=1421` et `FLASK_ENV=production`, puis lance `python server.py`. La fenêtre reste ouverte et affiche le code de sortie.
   * En PowerShell, utilisez `./start_server.ps1`. La sortie est également copiée dans `logs/server.log` pour faciliter le débogage ultérieur.
3. **Ouvrez votre navigateur** sur [http://127.0.0.1:1421](http://127.0.0.1:1421).  L'application écoute par défaut sur ce port et accepte aussi l'origine `http://localhost:1421`.
4. Pour vérifier les endpoints essentiels, lancez `scripts\smoke-test.ps1 -BaseUrl http://127.0.0.1:1421` dans une seconde fenêtre.

## Configuration OpenAI

Les fonctionnalités LLM reposent sur l'API OpenAI. Ajoutez les variables suivantes dans votre fichier `.env` à la racine du projet :

* `OPENAI_API_KEY` (**obligatoire**) : clé API OpenAI standard ou Azure.
* `OPENAI_API_TYPE` (optionnelle) : définissez `azure` pour activer un déploiement Azure OpenAI.
* `OPENAI_API_BASE` (optionnelle) : URL complète de votre ressource Azure (ex. `https://xxx.openai.azure.com`). Obligatoire si `OPENAI_API_TYPE=azure`.

Variables conseillées (valeurs par défaut fournies) :

```
OPENAI_API_KEY=sk-...
OPENAI_TEXT_MODEL=gpt-4o-mini
OPENAI_ASR_MODEL=gpt-4o-mini-transcribe
OPENAI_MODEL_WEB=gpt-4o-mini
```

### Lancer le serveur avec la clé chargée

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python server\run.py
```

Le serveur expose une route de santé `GET /api/health` indiquant si la clé est présente (`env`) et si l'API répond (`llm`). L'interface web consomme cette route pour afficher ou masquer le bandeau d'avertissement lié aux fonctionnalités LLM.

## Structure du projet

```
assistant-clinique-suite/
  assets/            # Contient le logo et les ressources statiques à servir
  client/            # Code front : modules ES, styles, composants
  data/              # Données de démonstration (patients)
  server/            # Code serveur Flask : Blueprints, services, librairie
  start_server.bat   # Lanceur Windows
  start_server.ps1   # Lanceur PowerShell
  README.md          # Ce fichier
```

### Librairie

Le dossier `server/library/store/` contient des documents Markdown, texte ou JSON décompressés depuis `library.zip`.  À chaque démarrage, le serveur construit un index en mémoire via `server/library/indexer.py`.  Les documents sont accessibles par des endpoints JSON :

* `GET /api/library/status` : indique le nombre de documents indexés, la date d’indexation et la liste des tags connus.
* `GET /api/library/search?q=<query>&tags=tag1,tag2&limit=10` : recherche des ressources par mots clés et (facultativement) par tags.  Retourne les métadonnées et le résumé.
* `GET /api/library/item?id=<id>` : récupère le contenu complet d’un document identifié par son chemin relatif.

Le panneau **Ressources** dans les onglets Pré‑séance et Post‑séance consomme ces endpoints pour offrir une recherche simplifiée.  Vous pouvez ajouter vos propres fichiers dans `server/library/store/` (formats `.md`, `.txt`, `.json`) : ils seront indexés automatiquement au prochain démarrage.

### Logo et identité

Le logo est stocké dans `assets/logo.png`.  Pour le remplacer, déposez un fichier `logo.png` dans ce dossier.  L’icône de l’onglet et le logo affiché dans l’interface seront mis à jour sans modification du code.

### Thème et accessibilité

La feuille `client/styles/base.css` définit des variables CSS et des composants réutilisables : entête collant, panneaux avec fond élevé, boutons primaires/secondaires, etc.  Elle s’adapte automatiquement aux préférences système (`prefers-color-scheme: dark`).  Vous pouvez forcer un thème en définissant `data-theme="dark"` ou `data-theme="light"` sur `<html>` si besoin.

### Déploiement

Les scripts de démarrage fonctionnent sans arguments :

* `start_server.bat` : crée ou réutilise `.venv`, installe les dépendances de `requirements.txt`, copie `.env.example` vers `.env` si nécessaire et lance `python server/run.py`.
* `start_server.ps1` : équivalent PowerShell, affiche en fin d’exécution l’URL d’accès à l’application.

Le serveur écoute sur le port défini par `APP_PORT` (1421 par défaut).  Modifiez cette valeur dans `.env` pour en changer.

### Versionnement des assets

L’application injecte un hash de version dans `<meta name="asset-version">`. Ce hash est dérivé du contenu concaténé de `client/app.js`, `client/tabs/documents_aide/index.js`, `client/tabs/documents_aide/view.html` et `client/tabs/documents_aide/style.css`. Tous les chargements dynamiques utilisent `withAssetVersion()` pour ajouter `?v=<hash>` aux URLs, ce qui invalide automatiquement le cache navigateur dès qu’un de ces fichiers change. Les onglets peuvent exploiter `validateTab()` en mode développement pour vérifier que les assets sont disponibles et que la vue expose bien les sélecteurs attendus.

## API disponible

## Journal critique

Le journal critique repose sur une persistance disque robuste et atomique. Les données sont stockées dans le dossier `instance/journal_critique/` (créé automatiquement au démarrage) :

* `entries/` : chaque note est enregistrée dans un fichier JSON nommé d’après son identifiant (`{id}.json`).
* `index.jsonl` : index de recherche minimal, une note par ligne, mis à jour à chaque sauvegarde/suppression.
* `.trash/` : corbeille recevant les notes supprimées (la récupération peut se faire en déplaçant le fichier dans `entries/`).
* `../search_indexes/journal_critique.jsonl` : miroir de l’index destiné au moteur de recherche interne.

### Schéma des notes

Chaque entrée sauvegardée suit la structure suivante :

```json
{
  "id": "uuid4",
  "title": "Titre de la note",
  "body_md": "Contenu Markdown",
  "created_at": "2024-05-01T08:30:00Z",
  "updated_at": "2024-05-01T08:45:00Z",
  "tags": ["somatique", "politique"],
  "concepts": ["masking social"],
  "sources": [{"label": "Revue Santé", "url": "https://example.org"}],
  "patients": [{"id": "abc123", "name": "Patiente Demo"}],
  "meta": {"author": "system", "version": 1}
}
```

Les écritures sont atomiques (`json.dumps(..., ensure_ascii=False)` + `os.replace`), encodées en UTF-8 avec des fins de ligne `\n`. Toutes les valeurs textuelles peuvent contenir des accents et des caractères propres aux langues romanes.

### Endpoints principaux

* `GET /api/journal-critique/ping` → vérifie la disponibilité (`{"success": true, "data": "journal-pong"}`).
* `GET /api/journal-critique/list` → liste paginée (`query`, `tags`, `concepts`, `patient`, `from`, `to`, `limit`, `offset`). Les filtres s’appuient uniquement sur l’index JSONL pour garantir la tolérance à la corruption.
* `GET /api/journal-critique/get?id=<id>` → charge la note complète depuis `entries/{id}.json` (404 si absente).
* `POST /api/journal-critique/save` → crée ou met à jour une note. Les champs acceptés sont `title`, `body_md`, `tags`, `concepts`, `sources`, `patients`. L’identifiant est généré côté serveur.
* `DELETE /api/journal-critique/delete?id=<id>` → déplace la note dans `.trash` et l’exclut de l’index.
* `POST /api/journal-critique/reindex` → reconstruit l’index à partir des fichiers présents dans `entries/` et purge les lignes corrompues.

Les erreurs suivent un format commun :`{"success": false, "error": {"code": "validation_error", "message": "...", "details": {}}}` avec les codes `validation_error`, `not_found`, `io_error`, `index_error`.

### Exemples d’appels `curl`

```bash
# Vérifier la disponibilité
curl -s http://127.0.0.1:1421/api/journal-critique/ping | jq

# Créer une note
curl -s -X POST http://127.0.0.1:1421/api/journal-critique/save \
  -H "Content-Type: application/json" \
  -d '{
        "title": "Journal critique – séance 12",
        "body_md": "## Observations\n- Noter les micro-résistances",
        "tags": ["somatique", "politique"],
        "concepts": ["masking social"],
        "patients": [{"id": "abc123", "name": "Patiente Demo"}]
      }' | jq

# Lister les notes en filtrant sur un tag
curl -s "http://127.0.0.1:1421/api/journal-critique/list?tags=somatique" | jq '.items'

# Supprimer une note
curl -s -X DELETE "http://127.0.0.1:1421/api/journal-critique/delete?id=<ID>" | jq

# Reconstruire l'index
curl -s -X POST http://127.0.0.1:1421/api/journal-critique/reindex | jq
```

### Tests manuels automatisés

Un script utilitaire est fourni pour vérifier le cycle CRUD complet sans serveur HTTP :

```bash
python server/scripts/test_journal.py
```

Le script crée un environnement temporaire, sauvegarde une note, la relit, la supprime puis déclenche une réindexation. Le code de sortie est non nul en cas d’échec.

## Documents d’aide

La suite inclut désormais un onglet **Documents d’aide** permettant de composer des PDF personnalisés pour chaque patient.
L’interface propose des suggestions issues de la pipeline Post-séance (objectifs, indices somatiques/cognitifs, lenses critiques) et
calcule automatiquement un score de couverture documentaire avant chaque export.

### Fonctionnalités principales

* Paramétrage par patient du registre (tutoiement/vouvoiement) et du genre grammatical (neutre/féminin/masculin).
* Pré-sélection intelligente des modules à partir des artefacts Post-séance avec explication de chaque recommandation.
* Résumé dynamique des modules sélectionnés (ordre réorganisable) et alertes de cohérence éditoriale.
* Génération de PDF structurés via ReportLab (page de garde, modules harmonisés, pied de page daté).
* Rapport de couverture documentaire archivable et gabarits `.md` proposés lorsque la bibliothèque manque d’un outil pertinent.

### Endpoints disponibles

* `GET /api/documents-aide/modules` — liste des modules disponibles dans la bibliothèque locale.
* `GET /api/documents-aide/context?patient=<id>` — suggestions, artefacts synthétiques et couverture de départ.
* `POST /api/documents-aide/assess` — recalcul du score de couverture, alertes et recommandations d’enrichissement.
* `POST /api/documents-aide/preview` — génère un aperçu PNG du document.
* `POST /api/documents-aide` — crée le PDF final et l’archive dans `instance/documents/<patient>/`.
* `GET /api/documents-aide?patient=<id>` — historique des documents précédents.
* `GET /api/documents-aide/coverage-report?patient=<id>` — rapport JSON des modules, manques et artefacts utilisés.
* `GET /api/documents-aide/recommendations` — gabarits de modules à rédiger lorsque la couverture est insuffisante.

Ajoutez vos modules dans `library/tools_index.json` et `library/modules/` pour enrichir automatiquement l’onglet.


Outre la librairie, l’application expose également :

* `GET /api/health` : statut de fonctionnement (`{ success: true, data: { status: "ok" } }`).
* `GET /api/version` : version des assets utilisée pour le cache.
* `GET /api/patients` : liste des patients de démonstration (`{ success: true, patients: [...] }` depuis `data/patients_seed.json`).
* Routes par onglet (`/api/pre`, `/api/post`, `/api/constellation`, `/api/anatomie3d`, `/api/facturation`, `/api/agenda`) fournissant des points d’extension pour vos fonctionnalités futures.

## Facturation

La maquette actuelle expose un onglet Facturation complet côté client (`client/tabs/facturation`) et un jeu d’API simulées dans `server/tabs/facturation/routes.py`.  Le serveur génère des factures factices à la volée en fonction de l’identifiant patient, ce qui permet de prévisualiser l’expérience sans persistance.

* **Index et compteurs** : les séquences de factures sont entièrement calculées en mémoire par `_generate_mock_invoices()` et `_compute_totals()` ; la numérotation dépend d’une graine dérivée du patient et d’un incrément (`FAC-<graine>-<n>`).【F:server/tabs/facturation/routes.py†L52-L128】【F:server/tabs/facturation/routes.py†L146-L165】  Lorsque la persistance sera activée, stockez vos fichiers d’index (`invoices_index.json`) et de compteurs (`counters.json`) dans `instance/facturation/` afin de conserver la séparation entre données sensibles et code.  Laissez les scripts de démarrage créer ce dossier pour éviter des problèmes de droits.
* **Gabarit de génération** : le gabarit ODT utilisé par LibreOffice doit être placé (non versionné) dans `instance/facturation/modele_facture.odt`.  Cette séparation vous permet de personnaliser la charte sans modifier le dépôt public.  L’onglet web charge quant à lui sa propre vue depuis `client/tabs/facturation/view.html` et la feuille de style associée.【F:client/tabs/facturation/index.js†L18-L81】【F:client/tabs/facturation/index.js†L104-L152】
* **LibreOffice & fallback ReportLab** : le flux de génération tente d’abord d’appeler `soffice --headless` à l’emplacement fourni (variable d’environnement `LIBREOFFICE_BIN`, ou bien présent sur le `PATH`).  Si LibreOffice n’est pas accessible, basculez sur la génération PDF programmée avec ReportLab ; le rendu sera plus simple (logo + en-tête + tableau), mais garantit un PDF fonctionnel.  Veillez à installer `reportlab` dans l’environnement virtuel pour profiter de ce repli.
* **Conventions de nommage** : les numéros suivent le motif `FAC-<graine sur 4 chiffres>-<index>` pour les factures confirmées et `FAC-<graine>-D<index>` pour les brouillons simulés.【F:server/tabs/facturation/routes.py†L55-L68】【F:server/tabs/facturation/routes.py†L112-L123】  Alignez vos exports PDF (`<numero>.pdf`) sur ces identifiants afin de rester cohérent avec l’interface.
* **Variables à renseigner** : ajoutez dans `.env` les clés `LIBREOFFICE_BIN` (chemin vers `soffice`), `FACTURATION_TEMPLATE_PATH` (gabarit ODT), `FACTURATION_OUTPUT_DIR` (dossier de sortie, par défaut `instance/facturation/exports`) et `FACTURATION_FALLBACK_FONT` (police ReportLab).  Ces paramètres permettent d’adapter le pipeline selon l’OS sans modifier le code.

## Personnalisation

* **Ajouter des ressources** : placez vos fichiers Markdown (`.md`), texte (`.txt`) ou JSON (`.json`) dans `server/library/store/`.  Au prochain démarrage, ils seront indexés et consultables via l’onglet Ressources.
* **Modifier le logo** : remplacez `assets/logo.png` par votre propre image (format PNG, idéalement carré).  Pensez à effacer le cache de votre navigateur ou à incrémenter la version des assets si besoin.
* **Étendre les onglets** : chaque dossier sous `server/tabs/` et `client/tabs/` constitue un module autonome.  Ajoutez des routes, des logiques ou des vues en respectant la structure existante.

## Tests

Les tests automatisés couvrent à la fois le backend Flask et certains utilitaires front.

* **Tests API** : exécutez `pytest` depuis la racine du projet pour lancer les suites Python (`tests/test_patients_endpoint.py`, `tests/test_post_session_routes.py`).【F:tests/test_patients_endpoint.py†L1-L58】【F:tests/test_post_session_routes.py†L1-L58】  L’environnement de test instancie l’application en mémoire sans avoir besoin de serveur externe.
* **Tests unitaires front** : utilisez Node 18+ et la commande `node --test tests/unit/patient_matcher.test.mjs` pour valider le résolveur de patients exploité lors de l’import de transcriptions.【F:tests/unit/patient_matcher.test.mjs†L1-L40】

> 💡 **Astuce instance** : ne créez pas manuellement les dossiers `instance/…`.  Lancez plutôt `start_server.bat` (Windows) ou `./start_server.ps1` (PowerShell) afin que les scripts provisionnent l’arborescence attendue et initialisent les fichiers de configuration.  Cela garantit que les droits d’écriture sont corrects sur chaque plate-forme.【F:legacy_server.py†L1-L74】

## Notes

* L’onglet **Agenda** reste inoffensif tant que les variables `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` et `GOOGLE_REDIRECT_URI` (ou `GOOGLE_REDIRECT_BASE`) dans `.env` sont vides.  Vous pouvez activer l’intégration Google plus tard en complétant ces valeurs.
* Aucune dépendance externe n’est utilisée côté client ; toute l’interface repose sur des modules ES standards et du CSS maison.
* Veillez à redémarrer le serveur pour prendre en compte les modifications de configuration ou l’ajout de nouvelles ressources.

## Agenda Google

### Création du client OAuth

1. Ouvrez [console.cloud.google.com](https://console.cloud.google.com) et créez un **projet** Google Cloud si nécessaire.
2. Dans **API & Services → Identifiants**, créez un **ID client OAuth** de type **Application de bureau**. Google fournit immédiatement un couple **Client ID / Client Secret** et un fichier JSON téléchargeable.
3. Ajoutez l’URI de redirection autorisée suivante : `http://127.0.0.1:1421/agenda/gcal/oauth2callback` (ajoutez la variante `http://localhost:1421/agenda/gcal/oauth2callback` si vous utilisez cet alias).

### Options de configuration

Deux approches coexistent et peuvent être utilisées selon votre politique de déploiement :

* **Fichier secret** — Renommez le JSON téléchargé en `gcal_client_secret.json` et placez-le dans `instance/` (le dossier est créé automatiquement au lancement du serveur). Le fichier n’est jamais exposé publiquement.
* **Variables `.env`** — Renseignez `GOOGLE_CLIENT_ID` et `GOOGLE_CLIENT_SECRET` dans `.env`. Vous pouvez également ajuster `GOOGLE_SCOPES` (séparés par des espaces ou des virgules), `GOOGLE_REDIRECT_URI` pour définir explicitement l’URL de retour, ou `GOOGLE_REDIRECT_BASE` si seule la base doit changer (`http://127.0.0.1:1421` par défaut).

Le service détecte automatiquement le mode actif (`env`, `file` ou `none`). La section **Agenda** de l’interface affiche l’état courant et la redirection retenue.

### Démarrage et authentification

1. Installez les dépendances via `pip install -r requirements.txt` (les bibliothèques Google requises sont listées dans ce fichier).
2. Lancez le serveur avec `python server/run.py` (ou utilisez les scripts `start_server.*`).
3. Ouvrez l’application sur [http://127.0.0.1:1421](http://127.0.0.1:1421) puis l’onglet **Agenda**.
4. Cliquez sur **Connecter Google**. Après validation du consentement, vous êtes redirigé vers l’onglet avec une notification de succès.
5. Vérifiez l’état via `GET /api/agenda/status` : le champ `authenticated` passe à `true` et `instance/gcal_token.json` est créé (le service le rafraîchit automatiquement avant expiration).

Pour révoquer l’accès, utilisez le bouton **Déconnecter** ou supprimez `instance/gcal_token.json`. La commande `python server/scripts/test_gcal.py` fournit un diagnostic rapide (`configured`, `authenticated`, listing des agendas accessibles) et retourne un code de sortie non nul en cas de configuration absente ou d’erreur API.

## Journal critique

L’onglet **Journal critique** permet de composer des journaux narratifs
externalisant le Problème dans l’esprit de White & Epston. Il repose sur
une bibliothèque de prompts éditoriaux stockés dans
`library/journal_prompts/` et indexés par `library/journal_prompts_index.json`.

### Fonctionnalités principales

* **Catalogue de prompts** : les fichiers Markdown sont classés par
  famille (`externalisation`, `resultats_uniques`, `re_membering`, etc.).
  Chaque entrée du JSON indique le budget cognitif recommandé, les tags
  critiques et les domaines couverts (somatique, cognitif, relationnel,
  politique, valeurs).
* **Personnalisation linguistique** : le moteur remplace les tokens
  `{{TUT:Tu peux|Vous pouvez}}`, `{{GEN:tes|vos|tes}}`,
  `{{PRONOM_SUJET}}`, `{{PATIENT_PRENOM}}`… en fonction des paramètres de
  civilité et de genre choisis pour le patient. Aucun token résiduel ne
  subsiste dans les exports.
* **Intégration Post‑séance** : l’interface peut consommer un bloc JSON
  d’artefacts (objectifs extraits, indices somatiques, lenses utilisées)
  afin de proposer automatiquement des prompts pertinents et de calculer
  la couverture critique. Les suggestions sont accessibles via
  `POST /api/journal-critique/suggestions`.
* **Exports structurés** : `POST /api/journal-critique/generate` produit
  un PDF (ReportLab) et un DOCX (python-docx) dans `instance/journal/<patient>/`.
  Le PDF comprend une page de garde, les sections organisées par famille
  et des annexes optionnelles (lettre outsider-witness, bibliographie
  située). Un endpoint `POST /api/journal-critique/preview` renvoie une
  prévisualisation encodée en base64.
* **Couverture éditoriale** : `POST /api/journal-critique/coverage`
  renvoie un score 0–100 par domaine. Lorsque la bibliothèque est pauvre
  sur un domaine, `GET /api/journal-critique/recommendations?domain=...`
  fournit des gabarits prêts à l’emploi basés sur le canevas narratif.

### Conventions d’écriture des prompts

* Les fichiers Markdown commencent par un titre `#`, suivi de sections
  `## Invitation principale`, `## Variante budget faible`,
  `## Encadré – situer le contexte`, `## Témoin outsider-witness`.
* Les invitations sont rédigées en paragraphes sans listes prescriptives
  et contiennent au moins une question re-authoring.
* Les tokens linguistiques disponibles sont :
  * `{{TUT:…|…}}` pour différencier tutoiement/vouvoiement.
  * `{{GEN:F|M|N}}` pour les accords féminins/masculins/neutres.
  * `{{PATIENT_PRENOM}}`, `{{PRONOM_SUJET}}`, `{{PRONOM_OBJET}}`,
    `{{PRONOM_POSSESSIF}}`, `{{TEMPS:present|futur}}`.
* Aucun terme pathologisant ou référence psychanalytique n’est toléré :
  la génération est bloquée si un prompt contient un mot proscrit.

### Historique

Chaque export est historisé dans `instance/journal/history_index.json`
avec les prompts sélectionnés, les alertes affichées et les liens vers
les fichiers générés. L’UI affiche cet historique dans la colonne de
droite de l’onglet.

### Scopes et précautions

* Les scopes par défaut visent l’accès en lecture/écriture au calendrier Google (par exemple `https://www.googleapis.com/auth/calendar`). Vérifiez qu’ils correspondent à vos besoins avant de déployer.
* Le dossier `instance/` est destiné aux secrets et jetons locaux : ne le commitez jamais dans votre dépôt Git. Les fichiers sensibles (`gcal_client_secret.json`, `gcal_token.json`) doivent rester en local ou dans un gestionnaire de secrets.
* Pour ajouter ou retirer des scopes, mettez à jour la configuration dans le code serveur puis supprimez `instance/gcal_token.json` afin de déclencher un nouveau consentement utilisateur.
#   t r a n s c r i p t e u r - c o r r i g -  
 