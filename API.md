# API du service post‑séance

Ce document décrit les différents endpoints exposés par le serveur Flask du nouvel assistant post‑séance.  Les schémas JSON sont donnés à titre indicatif : toutes les clés non mentionnées sont ignorées et ne doivent pas être présentes dans les requêtes.

## `POST /transcribe`

Transcrit un audio ou retourne un texte tel quel.  La requête peut être envoyée en `multipart/form-data` (champ `audio`) ou en JSON avec un champ `audio` contenant un [data URL](https://datatracker.ietf.org/doc/html/rfc2397) ou un champ `transcript` déjà rempli.

### Corps JSON

```json
{
  "audio": "data:audio/wav;base64,…",       // optionnel, l'audio codé en base64
  "transcript": "…",                       // optionnel, un texte brut à utiliser à la place de l'audio
  "options": {
    "chunk_seconds": 120,                 // durée d'un segment en secondes (défaut : 120)
    "overlap_seconds": 4,                 // recouvrement entre segments (défaut : 4)
    "idempotency_key": "abcd1234"       // clé facultative pour forcer la réutilisation d'un artefact existant
  }
}
```

### Réponse

```json
{
  "ok": true,
  "transcript": "Texte complet…",
  "segments": [
    {"t": [0.0, 120.0], "text": "…"},
    {"t": [116.0, 236.0], "text": "…"}
  ],
  "duration": 1234.5,               // durée totale en secondes (si disponible)
  "text_sha256": "…",              // hash du texte complet
  "text_len": 3456,                // nombre de caractères
  "session_id": "abcd1234",        // clé déterministe de la session
  "cached": true                    // présent uniquement si l'audio était déjà transcrit
}
```

Le service découpe toujours l'audio en segments déterministes.  Si un artefact existe déjà pour la même clé, il est retourné sans recalcul et le champ `cached` est ajouté à `true`.

## `POST /prepare_prompt?stage=research`

Construit la **fiche research** à partir d'un transcript brut.  Les champs optionnels servent à personnaliser le contexte.

### Corps JSON

```json
{
  "transcript": "…",
  "prenom": "Alice",      // facultatif : prénom ou identifiant du patient
  "base_name": "Séance 5", // facultatif : titre de séance
  "date": "2025-10-10",    // facultatif : date au format AAAA-MM-JJ
  "register": "vous"       // tutoiement ou vouvoiement (défaut : vous)
}
```

### Réponse

```json
{
  "meta": {
    "session_id": "…",
    "hash": "…",
    "date": "2025-10-10",
    "prenom": "Alice",
    "register": "vous"
  },
  "evidence_sheet": "…",     // premières lignes du transcript
  "critical_sheet": "…",     // grille de lecture matérialiste
  "lenses_used": ["matérialisme", "histoire du sujet", "analyse foucaldienne"],
  "reperes_candidates": ["Clarifier…", "Identifier…"],
  "points_mail": ["…", "…"],
  "chapters": [
    {"t": [0.0, 1.0], "title": "Introduction", "summary": "Résumé…"},
    {"t": [1.0, 2.0], "title": "Développement", "summary": "…"},
    {"t": [2.0, 3.0], "title": "Conclusion", "summary": "…"}
  ]
}
```

## `POST /prepare_prompt?stage=final`

Prend en entrée l'objet JSON retourné par la phase research et produit un plan, une analyse structurée et un mail prêt à être envoyé.  Aucun paramètre supplémentaire n'est requis.

### Réponse

```json
{
  "plan_markdown": "Plan de séance…",  // résumé en markdown
  "analysis": {
    "lenses": ["matérialisme", …],
    "reperes_selected": ["Clarifier…", "Identifier…"],
    "contradictions": ["…"],
    "objectives": ["…", "…"]
  },
  "mail_markdown": "# Compte-rendu de séance…"
}
```

Le mail produit respecte un style strict : pas de listes numérotées ni de tirets longs, guillemets droits et cohérence du registre.

## `POST /post_session`

Enchaîne les étapes transcription → research → final et persiste les artefacts sur disque.  Accepte soit un champ `audio` (multipart ou data URL) soit un champ `transcript`.  Les champs facultatifs `prenom`, `base_name`, `date` et `register` sont propagés aux phases suivantes.

### Réponse

```json
{
  "meta": {
    "session_id": "…",       // identique à celui de /transcribe
    "patient": "Alice",
    "date": "2025-10-10",
    "base_name": "Séance 5",
    "register": "vous",
    "cached": true             // présent uniquement si la session existait déjà
  },
  "plan": "…",              // texte markdown
  "analysis": {…},           // voir ci‑dessus
  "mail": "…",              // message formaté
  "artifacts": {
    "transcript_txt": "_global/abcd1234/transcript.txt", // chemins relatifs à ARCHIVE_DIR
    "segments_json": "_global/abcd1234/segments.json",
    "research_json": "_global/abcd1234/research.json",
    "analysis_json": "_global/abcd1234/analysis.json",
    "plan_txt": "_global/abcd1234/plan.txt",
    "mail_md": "_global/abcd1234/mail.md"
  }
}
```

Les artefacts sont stockés dans `instance/archives/<patient>/<session_id>/`.  Si une session avec la même clé existe déjà, les fichiers existants sont renvoyés sans recalcul et le champ `cached` est ajouté à `true` dans la réponse.

## `GET /artifacts/<path>`

Permet de télécharger un fichier précédemment persisté.  Le chemin est relatif au dossier d'archives.  Une erreur 403 est renvoyée si le chemin tente de sortir de `ARCHIVE_DIR`.

## `GET /_health`

Retourne un état simple du serveur :

```json
{
  "version": "…",        // version logicielle
  "ffmpeg": true,         // ffmpeg est-il présent sur le système
  "ffprobe": true,        // ffprobe est-il présent
  "read_write": true      // les dossiers upload/archives sont accessibles en écriture
}
```

Ce point de terminaison est utile pour le monitoring et les diagnostics.