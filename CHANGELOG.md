# Journal des modifications

Toutes les modifications majeures apportées au transcripteur post‑séance sont listées dans ce document.  Les dates utilisent le format ISO (AAAA‑MM‑JJ).

## 2025‑10‑10

### Ajouts

* **Transcription par segments** : l’algorithme monolithique a été remplacé par une découpe systématique en fenêtres glissantes (`chunk_seconds` et `overlap_seconds`).  Chaque segment est transcrit indépendamment puis concaténé, ce qui supprime toute troncature des longues séances.
* **Idempotence forte** : chaque audio génère une clé SHA256 déterministe calculée à partir des octets et des paramètres de découpe.  Si un client transmet à nouveau le même enregistrement ou le même transcript, le serveur renvoie immédiatement les artefacts persistés sans recalcul.  Les routes `/transcribe` et `/post_session` ajoutent un champ `cached` pour signaler une réutilisation.
* **Persistences des artefacts** : le pipeline haut niveau `/post_session` enregistre désormais systématiquement le transcript (`transcript.txt`), les segments (`segments.json`), la fiche research, l’analyse, le plan et le mail.  Ces fichiers sont servis via `GET /artifacts/<path>`.
* **Tests automatiques** : ajout de tests Pytest (`tests/test_idempotency.py`) pour valider la stabilité du `session_id` et la réutilisation des données.
* **Échantillons** : ajout de deux fichiers audio de démonstration (`samples/sample_short.wav`, `samples/sample_long.wav`) et d’un exemple de session JSON (`samples/sample_session.json`).

### Modifications

* La route `/post_session` vérifie avant de lancer les étapes research/final si des artefacts existent pour la clé demandée.  En cas de hit, les résultats sont renvoyés tels quels et le champ `cached` est ajouté dans la réponse `meta`.
* Le fichier `server/transcriber.py` n’a pas été modifié mais est désormais utilisé en mode cache.

### Corrections

* Résolution d’un bug entraînant la suppression prématurée des fichiers audio temporaires avant la fin du traitement.  Les fichiers sont maintenant supprimés après la persistance éventuelle.
* Meilleure gestion des exceptions lors du chargement des artefacts : en cas de corruption, le serveur repasse en recalcul complet.

### Correctifs UI (navigation et mode nuit)

* **Routeur SPA tolérant** : l’interface web s’appuie désormais sur un routeur en JavaScript qui interprète les ancres (`#tab`), les paramètres `?tab=` et les chemins `/tab/…`.  Le routeur met à jour l’attribut `data-active-tab` sur `<body>`, applique la classe `active` sur les liens et masque automatiquement la section d’accueil identifiée par `tab-home`.  La compatibilité est maintenue avec les anciens panneaux via les sélecteurs `data-tab`, `.tab-panel` et `id^="tab-"`.
* **Mode sombre rétabli** : un module `theme.js` applique simultanément l’attribut `data-theme="dark"` et la classe `dark` en fonction des préférences utilisateur ou du système, persistées dans `localStorage`.  Il expose une API globale `setTheme()` et réagit aux changements de `prefers-color-scheme`.
* **Feuilles d’ajustement** : ajout de `router-fix.css` pour forcer `display:none` sur les éléments masqués via l’attribut `hidden`.  La feuille `theme-dark-fixes.css` a été déplacée dans `client/css/` et enrichie pour prendre en charge `.dark`.