# Notes de mise à niveau

Ce document aide à migrer d’anciennes installations du transcripteur post‑séance
vers cette nouvelle version.  Les principaux changements concernent la
séparation claire des étapes de la pipeline, la structure de persistance des
fichiers et l’interface utilisateur.

## Ancienne API vs nouvelle API

* L’ancienne route `/api/post-session/upload-audio` est remplacée par
  `POST /transcribe` pour une transcription isolée et par
  `POST /post_session` pour l’orchestration complète.
* Les routes `/api/post-session/plan` et `/api/post-session/mail` sont
  remplacées par `POST /prepare_prompt` avec le paramètre de requête
  `stage`.  Les paramètres JSON attendus sont détaillés dans `docs/API.md`.
* La structure de la réponse diffère : la clé `ok` indique désormais le
  succès et les charges utiles sont alignées sur les schémas JSON fournis
  dans la spécification.

## Persistance des artefacts

* Les fichiers sont désormais stockés sous
  `instance/archives/<patient>/<session_id>/`.  Le nom `session_id` est un
  hash SHA256 du contenu audio (ou du texte), garantissant l’idempotence.
* Les fichiers générés portent des noms fixes : `transcript.txt`,
  `segments.json`, `research.json`, `analysis.json`, `plan.txt`, `mail.md`.

## Interface utilisateur

* L’interface est maintenant un assistant en cinq étapes.  Les anciens
  écrans Post‑séance n’existent plus.  Les toasts d’erreurs sont visibles
  et la barre de progression indique l’état courant.

## Scripts de démarrage

* Utiliser `./run.sh` (Linux) ou `run.ps1` (Windows) pour lancer le serveur.
* Les scripts `dev.sh` et `dev.ps1` démarrent le serveur avec le reloader
  automatique de Flask.

## Tests

* Les tests existants peuvent être adaptés en important les classes
  `Transcriber`, `ResearchPipeline` et `FinalPipeline` depuis le nouveau
  package `server`.

## Prochaines étapes

Cette version constitue une base minimaliste.  Pour aller plus loin :

* Intégrer un moteur de recherche local ou web afin d’enrichir les
  `evidence_sheet` et `critical_sheet` avec des citations vérifiables.
* Implémenter un validateur post‑génération plus strict pour le mail final.
* Ajouter une persistance des états intermédiaires pour permettre la reprise
  d’une session inachevée après rechargement du navigateur.