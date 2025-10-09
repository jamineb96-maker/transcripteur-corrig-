# Changelog

Toutes les modifications notables de ce projet seront consignées dans ce
fichier.  La datation suit le format AAAA‑MM‑JJ.

## 2025‑10‑10 — Première version publique

* Ajout d’un service Flask modulaire avec :
  * Upload et transcription d’audio en segments avec chevauchement, et mode
    de repli si l’API OpenAI n’est pas disponible.
  * Pipeline en deux passes (`/prepare_prompt?stage=research` et
    `/prepare_prompt?stage=final`) produisant un objet de recherche et une
    synthèse finale.
  * Endpoint `/post_session` orchestrant toute la chaîne et persistant les
    artefacts dans une structure de répertoires stable.
  * Endpoint `/artifacts/<path>` pour servir les fichiers générés.
* Ajout d’une interface Web minimaliste en 5 étapes (import audio/texte,
  transcription, recherche, synthèse, téléchargement).
* Mise en place de tests unitaires et d’intégration basés sur pytest.
* Documentation initiale (`README.md`, `API.md`, `CHANGELOG.md`,
  `UPGRADE_NOTES.md`, `AUDIT.md`).
