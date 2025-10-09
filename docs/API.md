# Spécification de l'API

Ce document décrit les différentes routes exposées par le serveur Flask du
module post‑séance.  Toutes les réponses sont au format JSON et contiennent
au minimum la clé `ok` indiquant le succès de l'opération.

## POST `/transcribe`

Transcrit un fichier audio ou accepte une transcription textuelle.

### Paramètres (multipart/form‑data)

* `audio` (fichier) : fichier audio (.mp3, .wav, .m4a, etc.).
* `chunk_seconds` (optionnel) : durée des segments en secondes (défaut : 120).
* `overlap_seconds` (optionnel) : chevauchement entre segments (défaut : 4).
* `idempotency_key` (optionnel) : clé externe pour éviter les duplications.

### Paramètres (JSON)

* `transcript` (string) : transcription brute.
* `audio` (data URL) : audio encodé en `data:...;base64,...`.
* `options` (objet) : peut contenir `chunk_seconds`, `overlap_seconds` et
  `idempotency_key`.

### Réponse

```
{
  "ok": true,
  "transcript": "Texte intégral de la séance…",
  "segments": [
    { "t": [0.0, 120.0], "text": "Segment…" },
    { "t": [116.0, 236.0], "text": "Segment…" },
    …
  ],
  "duration": 1800.0,
  "text_sha256": "…",
  "text_len": 12345,
  "session_id": "…"
}
```

* `segments` liste les segments transcrits avec leur intervalle temporel.
* `session_id` est une clé déterministe basée sur le contenu audio ou textuel.

## POST `/prepare_prompt?stage=research`

Prépare la structure de recherche à partir d'une transcription.

### Paramètres (JSON)

* `transcript` (string) : texte complet à analyser (obligatoire).
* `prenom` (string) : prénom du patient (optionnel).
* `base_name` (string) : identifiant de séance (optionnel).
* `date` (string) : date au format ISO‐8601 (optionnel, défaut : aujourd'hui).
* `register` (string) : "tu" ou "vous" (optionnel, défaut : "vous").

### Réponse

```
{
  "meta": {
    "session_id": "…",
    "hash": "…",
    "date": "2025-10-10",
    "prenom": "Alice",
    "register": "vous"
  },
  "evidence_sheet": "Lignes de texte…",
  "critical_sheet": "Analyse critique…",
  "lenses_used": [ "matérialisme", "histoire du sujet", … ],
  "reperes_candidates": [ "Clarifier les ressources…", … ],
  "points_mail": [ "Première phrase", "Deuxième phrase", … ],
  "chapters": [
    { "t": [0.0, 1.0], "title": "Introduction", "summary": "…" },
    …
  ]
}
```

## POST `/prepare_prompt?stage=final`

Génère la synthèse finale à partir d'un payload de recherche.  Le corps de la
requête doit être l'objet retourné par la phase de recherche.

### Réponse

```
{
  "plan_markdown": "Plan en markdown…",
  "analysis": {
    "lenses": [ "matérialisme", … ],
    "reperes_selected": [ … ],
    "contradictions": [ … ],
    "objectives": [ … ]
  },
  "mail_markdown": "# Compte‑rendu…"
}
```

## POST `/post_session`

Orchestre toute la chaîne post‑séance : transcription, recherche, synthèse
finale et persistance.  Accepte les mêmes paramètres que `/transcribe` avec
des métadonnées optionnelles (`prenom`, `base_name`, `date`, `register`).

### Réponse

```
{
  "meta": {
    "session_id": "…",
    "patient": "Alice",
    "date": "2025-10-10",
    "base_name": null,
    "register": "vous"
  },
  "plan": "Plan…",
  "analysis": { … },
  "mail": "# Compte‑rendu…",
  "artifacts": {
    "transcript_txt": "archives/Alice/<session>/transcript.txt",
    "segments_json": "archives/Alice/<session>/segments.json",
    "research_json": "archives/Alice/<session>/research.json",
    "analysis_json": "archives/Alice/<session>/analysis.json",
    "plan_txt": "archives/Alice/<session>/plan.txt",
    "mail_md": "archives/Alice/<session>/mail.md"
  }
}
```

Les fichiers sont accessibles via `GET /artifacts/<path>`.

## GET `/artifacts/<path>`

Retourne un artefact précédemment sauvegardé.  La route empêche la
traversée de répertoires hors du dossier `ARCHIVE_DIR`.