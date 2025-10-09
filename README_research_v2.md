# Moteur de recherche pré-session v2

Cette version renforce la collecte, le filtrage et la traçabilité des recherches réalisées avant séance. Elle fonctionne en parallèle du moteur existant et s'active via un *feature flag*.

## Activation

```bash
export PRESESSION_RESEARCH_V2=true
```

Ou bien passer `{"use_v2": true}` dans le champ `options` lors de l'appel à `modules.research_engine.run_research`.

## Variables d'environnement principales

| Variable | Description | Valeur par défaut |
| --- | --- | --- |
| `PRESESSION_RESEARCH_V2` | Active la V2 lorsqu'à `true` | `false` |
| `RESEARCH_V2_CACHE_PATH` | Emplacement du cache persistant | `logs/research/cache.json` |
| `RESEARCH_V2_CACHE_TTL_SECONDS` | Durée de vie des entrées cache | `86400` (24h) |
| `RESEARCH_V2_USER_AGENT` | User-Agent explicite pour la collecte | `pre-session-research-bot/2.0` |
| `RESEARCH_V2_REQUEST_DELAY` | Délai entre deux requêtes réseau | `0.5` seconde |
| `RESEARCH_V2_REQUEST_TIMEOUT` | Timeout réseau | `8` secondes |
| `RESEARCH_V2_MAX_RETRIES` | Nombre de tentatives par requête | `2` |

## Fichiers de configuration

- `config/research_sources.yml` : registre des domaines whitelist/greylist et niveaux de preuve.
- `config/research_policy.yml` : fenêtres de fraîcheur, seuils de gating et pondérations de scoring.

## Pipeline

1. **Facettisation** (`modules/research_v2/faceting.py`) : extraction de facettes contextualisées.
2. **Génération de requêtes** (`modules/research_v2/queries.py`) : requêtes multi-angles (clinique, déterminants, local) sans PII.
3. **Collecte** (`modules/research_v2/collector.py`) : appels réseau polis, cache persistant, extraction du contenu principal.
4. **Filtrage & déduplication** (`modules/research_v2/filter_dedupe.py`) : élimination des domaines bloqués, contenu faible et doublons.
5. **Scoring** (`modules/research_v2/scorer.py`) : calcul couverture/fraîcheur/diversité + gating.
6. **Synthèse** (`modules/research_v2/synthesizer.py`) : sections "évidence", "déterminants", "fenêtres de faisabilité", "coordination".
7. **Rendu** (`modules/research_v2/renderer.py`) : JSON normalisé avec progrès par facette et audit.
8. **Audit** (`modules/research_v2/audit.py`) : journalisation JSON dans `logs/research/sessions.log`.

## Exemple d'appel

```python
from modules.research_engine import run_research

plan = {"orientation": "Endométriose et charge mentale"}
context = {"orientation": "Douleurs pelviennes", "objectif_prioritaire": "Soulager la crise"}
resultat = run_research(plan, context, options={"use_v2": True, "location": "France"})
```

## Exemple de sortie (abrégé)

```json
{
  "facets": [
    {
      "name": "douleur_dysautonomie",
      "status": "ok",
      "scores": {"coverage": 0.8, "freshness": 0.9, "diversity": 0.7},
      "progress": {"targets": {"candidates": 10}, "current": {"candidates": 12}},
      "synthesis": {
        "evidence": "La HAS (2024-01-12) recommande...",
        "determinants": "Repérage des coûts et délais...",
        "feasibility": "Fenêtres de faisabilité : ...",
        "coordination": "Coordination : préparer l'échange..."
      },
      "citations": [
        {
          "title": "Recommandation HAS prise en charge endométriose",
          "url": "https://has-sante.fr/...",
          "date": "2024-01-12",
          "jurisdiction": "FR",
          "evidence_level": "guideline"
        }
      ]
    }
  ],
  "audit": {
    "session_id": "...",
    "started_at": "2024-03-04T10:20:30Z",
    "decisions": [
      {"url": "https://example.com", "kept": false, "reason": "low_quality"}
    ]
  }
}
```

## Tableau des niveaux de preuve (extrait)

| Niveau | Description | Impact sur le scoring |
| --- | --- | --- |
| `meta` | Méta-analyses et revues Cochrane | Favorise la diversité et la fraîcheur |
| `guideline` | Recommandations nationales (HAS, NICE) | Augmente la couverture et la pondération |
| `safety_notice` | Alertes de pharmacovigilance | Renforce la fraîcheur requise |
| `narrative` | Revues narratives (greylist) | Nécessite recoupement avec une source whitelist |

## Tests

```bash
pytest tests/research_v2
```

Les tests couvrent la facettisation, le filtrage/déduplication, le scoring, l'intégration avec collecteur mocké et la compatibilité du point d'entrée historique.
