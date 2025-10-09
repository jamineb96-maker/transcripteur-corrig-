# Couche bibliothèque – Mapping doc_id / système de fichiers

Cette documentation décrit la version 2 de la couche de persistance « Library ».

## Racine configurable

* `LIBRARY_ROOT` (variable d'environnement) pointe vers le dossier persistant de
  la bibliothèque. Par défaut il s'agit de `instance/library`.
* Le dossier est créé automatiquement au démarrage de l'application, ainsi que
  son sous-dossier `extracted`.

## Drapeau de fonctionnalité

* `FEATURE_LIBRARY_FS_V2` active le nouveau schéma de fichiers. Il est activé
  par défaut mais peut être forcé à `false` via une variable d'environnement ou
  `config/app_config.json`.

## Mapping des identifiants

* La fonction `server.utils.docid.doc_id_to_fs_path()` convertit un `doc_id`
  au format `<algo>:<hash>` en un chemin POSIX/NT sûr :
  `root / algo / h0h1 / h2h3 / hash`.
* `server.utils.docid.legacy_fs_path()` reconstruit l'ancien chemin
  `<algo>:<hash>` pour la migration ou la lecture d'archives existantes.
* `server.utils.docid.ensure_dir()` encapsule la création de dossiers avec
  journalisation.

Les tests unitaires couvrent la validation stricte, le sharding par défaut et la
compatibilité Windows.

## Migration des dépôts existants

Un script utilitaire est disponible pour convertir d'anciens dépôts (répertoires
nommés `<algo>:<hash>`) vers la structure v2. Exemple :

```bash
python scripts/migrate_library_fs_v2.py --library-root instance/library --dry-run
python scripts/migrate_library_fs_v2.py --library-root instance/library
```

Le script déplace chaque dossier vers `algo/h0h1/h2h3/hash`, met à jour le
`manifest.json` et consigne l'opération dans les logs. L'option `--flat` permet
de désactiver le sharding pendant la migration, tandis que `--dry-run` effectue
simplement un inventaire.
