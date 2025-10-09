# Diagnostics techniques

## Agenda Google

- **Symptôme observé** : l'échange OAuth retournait `invalid_client` et l'interface ne proposait aucune aide.
- **Cause identifiée** : les identifiants Google étaient mal chargés (variables d'environnement incohérentes, URI de redirection non enregistrée ou client de type « installed »).
- **Correctifs** :
  - Ajout d'un chargeur unifié des credentials (`server/services/gcal_config.py`) avec diagnostics détaillés (présence des variables, type de client, validation des URI).
  - Exposition d'un endpoint de debug et enrichissement de `/api/agenda/status` avec `reason`, `redirect_uri_ok`, `client_type`, etc.
  - Mise à jour de l'UI (onglet Agenda) pour afficher un bandeau de diagnostic contextualisé.

## Bibliothèque – Plan LLM

- **Symptôme observé** : le serveur rejetait fréquemment la réponse du LLM avec `invalid_plan_schema` et renvoyait un HTTP 422.
- **Cause identifiée** : le schéma JSON attendu n'était ni normalisé ni documenté, la sortie du modèle pouvait inclure des fences ou des littéraux Python (`True/False`), et aucune réparation n'était tentée.
- **Correctifs** :
  - Ajout d'un schéma Pydantic figé (`PlanV1`, `SCHEMA_VERSION=1.0.0`) et d'un utilitaire de réparation JSON tolérant (`strip_code_fences`, `lenient_json_loads`).
  - Durcissement du prompt LLM (mode JSON strict, mention du schéma complet, seed, max_tokens).
  - Normalisation et validation systématiques côté serveur avec retours HTTP 200 explicites (`why`, `validator_trace`).
  - Adaptation de l'UI pour présenter les erreurs de validation et proposer une régénération « contrainte stricte ».
# Diagnostics et scripts de maintenance

## Synchronisation des vendors Three.js

Pour mettre à jour les dépendances Three.js embarquées, installez `three` dans `node_modules` puis exécutez :

```bash
python tools/sync_three_vendor.py
```

Le script copie le strict nécessaire dans `static/vendor/three/` (build, loaders, contrôles et décodeurs Draco/Meshopt).
Le binaire `draco_decoder.wasm` est converti en `draco_decoder.wasm.base64` pour éviter les fichiers binaires dans le dépôt ;
le serveur reconstruit automatiquement le `.wasm` depuis cette sauvegarde si besoin.

## Tests fumée Anatomie 3D

Après avoir démarré le serveur local sur http://127.0.0.1:1421, lancez :

```bash
python server/tests/run_anatomy3d_smoke.py
```

Le test vérifie la route de santé `/anatomy3d/health` et la disponibilité des bundles Three.js.
