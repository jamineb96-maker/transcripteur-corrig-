# Assistant post‑séance

Ce projet fournit un service autonome permettant de transformer un enregistrement
audio d'une séance en un compte‑rendu structuré et critique.  Il est conçu
pour fonctionner hors connexion, sur Windows ou Linux, et se concentre sur la
fiabilité et la traçabilité des artefacts produits.

## Fonctionnalités principales

* **Transcription robuste** : découpe déterministe des fichiers audio en
  segments avec chevauchement, transcription séquentielle et assemblage sans
  perte de contenu.  En l'absence de clé OpenAI valide, un mode factice
  annoté est utilisé.
* **Pipeline en deux passes** : un premier appel (`stage=research`) extrait
  les éléments factuels, la lecture critique, des repères candidats et
  découpe le texte en chapitres.  Un second appel (`stage=final`) crée un
  plan, une analyse et un mail final en respectant des contraintes de style
  strictes (pas de listes, guillemets droits, rappels de réversibilité,…).
* **Idempotence et persistance** : un hash SHA256 de l'audio (ou du texte)
  garantit qu'une même entrée produit toujours le même identifiant de
  session.  Les artefacts sont enregistrés sous
  `instance/archives/<patient>/<session_id>/`.
* **Interface Web minimale** : un assistant en cinq étapes guide l'utilisateur
  de l'import de l'audio jusqu'au téléchargement des artefacts, avec
  barres de progression et messages explicites.

## Installation

1. Cloner ou extraire ce dépôt sur votre machine.
2. Optionnel : créer un environnement virtuel :
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Installer les dépendances :
   ```bash
   pip install -r requirements.txt
   ```
4. (Facultatif) définir la variable `OPENAI_API_KEY` pour activer la
   transcription Whisper via l'API OpenAI.  Sans clé, un mode factice est
   utilisé et les segments sont annotés.

## Utilisation

Pour lancer le serveur et l'interface Web :

```bash
./run.sh
```

Sous Windows PowerShell :

```powershell
./run.ps1
```

Le serveur démarre sur `http://localhost:5000`.  Rendez‑vous dans votre
navigateur à cette adresse pour utiliser l'assistant.

### Endpoints API

L'API exposée par le serveur est documentée dans `docs/API.md`.

## Tests

Des tests unitaires et d'intégration sont fournis dans le dossier `tests/`.
Pour les exécuter :

```bash
pytest -q
```

Les tests génèrent des fichiers audio temporaires via `ffmpeg`.  Assurez‑vous
que `ffmpeg` est installé et disponible dans votre `PATH`.

## Structure du projet

```
final/
├── client/          # Interface utilisateur HTML/JS/CSS
├── docs/            # Documentation (README, API, changelog, audit)
├── server/          # Code serveur Flask et pipelines
├── samples/         # Exemples de fichiers audio ou de transcriptions
├── scripts/         # Scripts utilitaires (tests, génération)
├── tests/           # Suite de tests unitaires et intégration
├── requirements.txt # Dépendances Python
└── run.sh / run.ps1 # Scripts de démarrage
```

## Limitations

* Le pipeline de recherche repose sur des heuristiques simples et ne consulte
  pas de sources externes.  Il doit être remplacé par un moteur de recherche
  et une analyse critique plus poussée pour une utilisation en production.
* La validation stylistique est minimale.  Pour des contraintes plus fines
  (nombre de paragraphes, cohérence du ton, etc.), un validateur dédié
  devra être ajouté.
