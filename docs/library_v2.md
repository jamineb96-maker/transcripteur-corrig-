# Bibliothèque clinique v2

Ce guide résume le flux de travail introduit par la V2 de la bibliothèque clinique. Il décrit comment indexer un document, normaliser les notions canoniques, comprendre la pondération des résultats de recherche et utiliser les outils de débogage.

## 1. Indexer un document PDF

1. Ouvrir l'onglet **Bibliothèque clinique** puis sélectionner un document déjà présent dans le dépôt documentaire.
2. Vérifier les métadonnées proposées (titre, auteurs, domaines, niveau de preuve). Ajuster au besoin. Le serveur calcule un `doc_id` déterministe lors de l'upload (`sha256(titre|auteurs|année|hash(pdf))`) et l'UI l'affiche immédiatement : ce même identifiant est réutilisé pour toutes les opérations (aucun recalcul côté client).
3. Avant toute indexation, contrôler l'état du pipeline via `GET /api/library/health` : le JSON renvoyé précise si le store est accessible, si le backend d'embeddings est opérationnel (`ok`, `fake`, `unavailable`) et si FAISS est actif.
4. Cliquer sur **Indexer les chunks**. L'interface appelle `POST /api/library/index_chunks` avec:
   ```json
   {
     "doc_id": "abc123",
     "doc_path": "/chemin/vers/le/pdf.pdf",
     "meta": {
       "title": "Titre officiel",
       "year": 2023,
       "domains": ["Trauma"],
       "evidence_level": "élevé",
       "pseudonymize": true
     }
   }
   ```
5. Le serveur découpe le PDF en blocs de ~1100 mots (chevauchement 180), pseudonymise si demandé, calcule les embeddings et insère les chunks dans le `VectorDB` (`server/library/store/chunks.jsonl`).
6. Le panneau de statut affiche le nombre de chunks nouvellement indexés, la durée (ms) et si la pseudonymisation a été activée. Ces informations sont également tracées dans `server/library/store/journal.log` (`event: index_chunks` et `event: index_chunks_endpoint`).
7. Utiliser `GET /api/library/debug/doc/<doc_id>` pour vérifier que le document possède bien des chunks indexés et compter les notions associées. En cas d'échec, l'UI affiche un message explicite (`embedding_failed`, `pdf introuvable`, etc.), aucun traitement silencieux n'a lieu.

## 2. Normaliser une notion canonique

1. Dans la section **Revue humaine**, remplir le formulaire pour chaque notion:
   - `label`: étiquette courte et explicite.
   - `definition`: 1 à 3 phrases falsifiables décrivant la notion.
   - `synonyms`: optionnels.
   - `domains`: au moins un domaine clinique.
   - `evidence_level`: `élevé`, `modéré`, `faible` ou `inconnu`.
   - `sources`: sélectionner un ou plusieurs chunks pertinents (preview + pagination affichés).
2. Cliquer sur **Indexer la sélection** pour chaque notion. L'appel `POST /api/library/notions` persiste l'entrée dans `server/library/store/notions.jsonl` après validation stricte (sources obligatoires, label/definition non vides, slug conforme). Une notion sans source valide est refusée avec `error: validation_failed` et un message explicite.
3. Le panneau latéral **Ce qui sera utilisable en Pré/Post** récapitule le nombre de chunks indexés et de notions reliées pour le document courant. Les compteurs sont rafraîchis après chaque insertion et peuvent être revérifiés via `GET /api/library/chunks?doc_id=...`.

## 3. Pondération de la recherche Pré/Post v2

La fonction `search_evidence` (modules `server/tabs/pre_session/research_engine_v2.py` et `post_session/research_engine_v2.py`) procède comme suit :

1. Encodage de la requête utilisateur via l'adaptateur d'embeddings existant (fallback haché local si indisponible).
2. Recherche sémantique top-k dans le `VectorDB` avec filtres facultatifs (`domains`, `min_year`, `min_evidence_level`).
   - Les filtres `domains` et `doc_id` s'appliquent avant la similarité, `min_year` et `min_evidence_level` éliminent les études trop anciennes ou insuffisamment étayées.
   - L'UI expose ces filtres dans la modale de debug et les contrôleurs Pré/Post peuvent transmettre les mêmes paramètres.
3. Re-ranking des candidats à l'aide de la formule :
   ```text
   score_final = 0.70 * score_semantique
               + 0.20 * weight_evidence(evidence_level)
               + 0.10 * weight_year(year)
   ```
   - `weight_evidence`: élevé=1.0, modéré=0.7, faible=0.4, inconnu=0.3.
   - `weight_year`: normalisation min-max sur les 15 dernières années (les études récentes sont favorisées sans exclure les anciennes).
4. Les résultats retournés incluent `doc_id`, `title`, `page_start/end`, `extract` (2–3 phrases), `score`, `evidence_level`, `year` et la liste des notions canoniques associées au chunk (via `NotionSource.chunk_ids`).
5. Toutes les recherches V2 loggent `event: search_v2` dans `journal.log` avec la requête, les filtres et la durée. Les requêtes de debug ajoutent également `event: search_debug`.

Si la variable d'environnement `RESEARCH_V2` vaut `false`, les contrôleurs Pré/Post utilisent automatiquement la logique historique (recherche textuelle existante). Aucun appel V2 n'est déclenché.

## 4. Déboguer et observer l'état temps réel

- `GET /api/library/health` : vérifier l'écriture disque, le backend d'embeddings et le flag `RESEARCH_V2`.
- `GET /api/library/debug/doc/<doc_id>` : connaître le volume de chunks et de notions reliées pour un document donné.
- `GET /api/library/chunks?doc_id=...` : récupérer les chunks (texte, pages, notions connectées) pour inspection manuelle.

L'onglet Bibliothèque propose un lien **Tester la recherche** qui ouvre une modale pilotant `POST /api/library/search_debug` :

L'onglet Bibliothèque propose un lien **Tester la recherche** qui ouvre une modale pilotant `POST /api/library/search_debug` :

```json
{
  "query": "plan trauma personnalisé",
  "filters": {
    "domains": ["Trauma"],
    "min_year": 2015,
    "min_evidence_level": "modéré"
  },
  "k": 5
}
```

La réponse fournit pour chaque hit : l'identifiant du document, les pages couvertes, un extrait court, le score brut et les notions reliées. Utiliser cette route pour :

- Vérifier que les chunks attendus ressortent bien avec les filtres appliqués.
- Examiner les scores bruts avant re-ranking pour ajuster les notions ou enrichir les métadonnées.
- Diagnostiquer un index incomplet (hits vides ⇒ relancer l'indexation et consulter `journal.log`).

## 5. Journaux et traçabilité

Chaque opération majeure écrit une ligne JSON dans `server/library/store/journal.log` :

- `index_chunks` : insertion brute des chunks (doc_id, n_chunks, durée).
- `index_chunks_endpoint` : synthèse post-indexation (chunks doc, notions liées, pseudonymisation activée).
- `debug_doc` et `list_chunks_endpoint` : consultation manuelle de la base.
- `search_v2` : requêtes Pré/Post v2 et debug.
- `search_debug` : requêtes manuelles depuis la modale.
- `save_notion` / `save_notion_endpoint` : validation d'une notion canonique (sources utilisées).

Ces journaux facilitent les audits et permettent de reconstituer le contexte d'une réponse clinique.

---

Pour plus d'informations sur la configuration (feature flag `RESEARCH_V2`, backend FAISS optionnel via `USE_FAISS`), consulter `server/library/vector_db.py` et `.env.example`.

## 6. Dépannage rapide

- **Embeddings indisponibles** : `embeddings_backend: "unavailable"` dans `/health` ⇒ activer un backend valide ou autoriser le fallback déterministe avec `ALLOW_FAKE_EMBEDS=true` (à n'utiliser qu'en test).
- **Droits disque** : `store_writable: false` ⇒ vérifier les permissions sur `server/library/store/` ou l'emplacement défini par `LIBRARY_VECTOR_STORE_DIR`.
- **doc_id incohérent** : si l'UI et l'API n'utilisent pas le même identifiant, recharger la page pour récupérer le `doc_id` calculé côté serveur et relancer l'indexation. Toute requête `/debug/doc/<doc_id>` doit refléter l'état réel.
