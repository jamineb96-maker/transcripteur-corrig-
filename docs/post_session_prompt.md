# Compositeur de prompt post-séance

Le compositeur post-séance permet de générer un prompt cohérent, sectionné et
prêt à être transmis à ChatGPT tout en respectant un contrat d’attribution strict
entre les propos du/de la patient·e et les observations du praticien.

## API serveur

- **Endpoint** : `POST /api/postsession/prompt/compose`
- **Corps JSON** :

```json
{
  "slug": "caroline",
  "window": {"type": "sessions", "count": 6},
  "topics": ["fatigue cognitive", "culpabilité"],
  "include": {
    "segments": true,
    "milestones": true,
    "quotes": true,
    "contradictions": true,
    "contexts": true,
    "somatic": true,
    "trauma_profile": true,
    "unresolved_objectives": true
  },
  "max_tokens": 1400,
  "attribution_strict": true
}
```

- **Réponse JSON** :

```json
{
  "prompt": "<texte complet prêt à envoyer>",
  "usage": {"segments": 620, "milestones": 120, "quotes": 140, "contradictions": 120, "contexts": 120, "somatic": 100, "trauma": 160, "meta": 820},
  "trace": [{"source": "segments", "session": "2025-09-30", "topic": "fatigue cognitive", "speaker": "patient", "kind": "paraphrase", "reason": "recent+recurrent"}],
  "warnings": ["Correction automatique d'une attribution sensible: remplacement par \"Je note que\"."]
}
```

`warnings` est présent uniquement si le linter d’attribution corrige une phrase
risquée. `usage.meta` reflète l’estimation totale de tokens après lissage.

## Contrat d’attribution obligatoire

Chaque prompt débute par le bloc suivant :

```
CONTRAT D’ATTRIBUTION — À RESPECTER STRICTEMENT
- N’écrivez jamais “vous avez dit …” pour des éléments issus d’observations/hypothèses du praticien.
- Réservez “vous avez dit …” uniquement aux citations directes du/de la patient·e, marquées comme telles.
- Les formulations du praticien doivent être introduites par “Je note… / J’observe… / Hypothèse prudente…”.
- Si l’attribution est incertaine, ne l’attribuez pas au/à la patient·e : classez-la comme observation du praticien.
- Avant d’émettre la version finale, effectuez un AUTOCHECK interne :
  * Pour chaque phrase contenant “vous avez”/“tu as”/“you said”, vérifiez qu’elle provient d’une citation patient.
  * Sinon, reformulez immédiatement en observation du praticien.
Ne listez pas ce contrôle dans la sortie au patient.
```

Deux conteneurs distincts suivent immédiatement :

1. **Ce que la personne a dit** — uniquement `speaker="patient"`. Les citations
   directes sont formalisées par `Vous avez dit : « … »` et marquées `[P-QUOTE]`.
   Les reformulations sont signalées `[P-PARA]`.
2. **Observations / hypothèses du praticien** — uniquement `speaker="clinician"`
   ou `kind="hypothesis"`. Les formulations commencent par `Je note…`,
   `J’observe…` ou `Hypothèse prudente…` et portent le badge `[CL-HYP]`.

Le reste du prompt reprend le gabarit clinique (segments, contradictions,
repères, citations, profil traumatique, mémoire somatique, contextes,
objectifs non résolus, demandes pour la suite) avec quotas de tokens afin de
rester sous `max_tokens`.

## Linter d’attribution

Avant de renvoyer la réponse :

- Un scan regex `\b(vous avez|tu as|you said)\b` est effectué.
- Si la phrase n’est pas associée à un item `speaker="patient"` & `kind="quote"`,
  l’expression est remplacée par `Je note que …` et un avertissement est ajouté
  dans `warnings`.

## Données nécessaires

Le compositeur lit :

- `index.json`, `segments.json`, `milestones.json`, `quotes.json`,
  `contradictions.json`, `contexts.json`, `somatic.json`, `trauma_profile.json`.
- Les objectifs non résolus dans le dernier `plan.txt` (`- [ ] …`).

Les éléments sont scorés à partir de la récence (décroissance exponentielle), de
la fréquence des thèmes et de bonus pour contradictions ou profils traumatiques.
Les doublons sont évités via une similarité de Jaccard simple.

## Traçabilité

Chaque entrée renvoyée dans `trace` indique :

- `source` : section d’origine (`segments`, `milestones`, `quotes`, etc.).
- `session` : identifiant de séance lorsque disponible.
- `topic`, `speaker`, `kind`, `reason` : métadonnées utiles pour auditer la
  sélection.

## UI de composition

Le panneau « Composer le prompt » fournit :

- Sélecteur de fenêtre (séances ou mois) et compteur.
- Champ libre pour filtrer par thèmes.
- Checkboxes pour inclure/exclure chaque section.
- Champ `max_tokens` et toggle « Attribution stricte » (activé par défaut).
- Bouton « Prévisualiser » qui appelle l’API, affiche le prompt coloré
  (vert = patient, bleu = clinicien) et met à jour le compteur d’occurrences à
  risque (`vous avez`).
- Bouton « Copier » qui copie le prompt généré.
- Préférences persistées dans `localStorage` (`postSession.promptBuilder.v1`).
- Dégradé gracieux : si aucune donnée n’est disponible, la prévisualisation
  affiche un message neutre et les compteurs restent à zéro.

## Tests

Les tests unitaires couvrent :

- Respect du plafond `max_tokens`, absence de doublons et fonctionnement avec
  sections manquantes (`tests/unit/test_prompt_composer.py`).
- Garantie d’attribution (`tests/unit/test_prompt_attribution.py`) :
  * aucune hypothèse clinicienne n’apparaît sous « Ce que la personne a dit » ;
  * les citations patient conservent « Vous avez dit… » ;
  * le linter corrige toute occurrence fautive ;
  * les items `speaker="unknown"` sont classés côté praticien.
