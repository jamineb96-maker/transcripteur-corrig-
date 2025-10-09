# Onglet Anatomie 3D – Guide d'utilisation

Ce document décrit la configuration du module pédagogique « Anatomie 3D », ses limites, ainsi que la procédure pour l'étendre sans modifier le code JavaScript.

## Principes généraux

- L'onglet est indépendant de la sélection de patiente et fonctionne en mode "global" par défaut.
- Toutes les données de personnalisation (annotations, snapshots, préférences) sont stockées en local dans le navigateur (`localStorage`).
- Le module fonctionne hors-ligne : toutes les dépendances sont présentes dans `static/vendor/`.

## Navigation dans l'interface

### Raccourcis clavier

| Touche | Action |
| --- | --- |
| `R` | Réinitialiser la vue active |
| `I` | Isoler le groupe courant |
| `G` | Appliquer le mode « fantôme » aux autres groupes |
| `S` | Enregistrer un snapshot |
| `P` | Capturer le viewport en PNG |

Le focus clavier suit l'ordre logique suivant : navigation supérieure, scènes, couches, recherche, glossaire, annotations, séquence, options avancées.

### Modes d'affichage

Le module dispose de deux modes :

- **Global** (par défaut) : aucune interaction avec la sélection de patientes.
- **Lié** : synchronisable avec une future intégration patient. Ce mode est masqué dans les options avancées et nécessite la bascule manuelle.

La préférence est stockée dans `localStorage` sous la clé `anatomy3d.mode`.

## Organisation des données JSON

Les fichiers de configuration sont situés dans `static/tabs/anatomy3d/` :

- `layers.json` : liste des groupes fonctionnels et des nœuds associés.
- `scenes.json` : scènes pédagogiques préconfigurées.
- `glossary.json` : glossaire des structures, en français, avec définitions, idées reçues et liens d'approfondissement.
- `synonyms.json` : correspondances pour la recherche tolérante.
- `sequences/` : parcours pédagogiques exportés.

### Ajouter un groupe de couches

1. Éditer `layers.json`.
2. Ajouter un objet `{ "id": "identifiant_unique", "label": "Nom affiché", "nodes": ["NomNodeGLB", ...] }`.
3. Sauvegarder : le module lit ce fichier lors du chargement et met à jour automatiquement l'UI.

### Ajouter une scène pédagogique

1. Créer un objet conforme au schéma :

```json
{
  "id": "stress_aigu",
  "title": "Stress aigu vs chronique",
  "camera": { "position": [0, 1.6, 2.5], "target": [0, 0.9, 0], "fov": 40 },
  "visibility": [{ "node": "Cortex_frontal", "visible": true }],
  "opacity": [{ "node": "Cortex_temporal", "alpha": 0.3 }],
  "notes": [{ "title": "Points clés", "text": "- Activation limbique\n- Régulation corticale" }],
  "myths": [{ "claim": "On n'utilise que 10% du cerveau", "correction": "L'activité est distribuée et variable." }],
  "questions": ["Que se passe-t-il en phase aiguë ?", "Quels mécanismes de récupération ?"],
  "glossary_keys": ["systeme_limbique", "cortex_prefrontal"]
}
```

2. Enregistrer l'objet dans `scenes.json`.
3. Aucun redémarrage n'est nécessaire : le module recharge les scènes lors de l'ouverture.

### Ajouter un élément de glossaire

1. Éditer `glossary.json` et ajouter un objet :

```json
{
  "key": "hippocampe",
  "label_fr": "Hippocampe",
  "definition": "Structure en forme de cheval marin impliquée dans la mémoire déclarative.",
  "misunderstanding": "L'hippocampe ne sert pas uniquement à enregistrer des souvenirs.",
  "links": [{ "label": "Dossier mémoire", "href": "../docs/memoire.pdf" }]
}
```

2. Ajouter des synonymes associés dans `synonyms.json` si nécessaire :

```json
{
  "key": "hippocampe",
  "synonyms": ["hippocampus", "mémoire"]
}
```

### Ajouter un parcours pédagogique

1. Dans l'interface, enregistrer les snapshots représentatifs.
2. Ouvrir l'éditeur de parcours, composer une suite d'étapes et exporter.
3. Le fichier téléchargé (format JSON) peut être placé dans `static/tabs/anatomy3d/sequences/` pour le rendre disponible par défaut.

Le schéma minimal d'un parcours est :

```json
{
  "id": "parcours_douleur",
  "title": "Douleur chronique",
  "objectives": ["Comprendre les réseaux de la douleur"],
  "steps": [
    { "snapshot_id": "snapshot1", "narration": "Introduction", "pause_ms": 5000 }
  ]
}
```

## Limites et neuromythes à éviter

L'encadré intégré rappelle :

- Ce modèle ne représente pas l'activité électrophysiologique.
- Les circuits sont simplifiés.
- Aucun diagnostic ne doit être posé à partir de cette visualisation.

Neuromythes déconstruits :

1. « On n'utilise que 10 % du cerveau. »
2. « L'hémisphère droit est uniquement créatif, le gauche logique. »
3. « Les neurones sont figés et ne se régénèrent pas. »

## Licence et crédits

`static/models/neurology.license.md` décrit la source du modèle 3D. L'onglet affiche automatiquement ce contenu dans le panneau Crédits.

## Mode basse consommation

Le flag `anatomy3d_low_power_mode` dans `static/config/feature_flags.json` active :

- Réduction de la résolution de rendu.
- Désactivation des effets post-process.
- Limitation du rafraîchissement des contrôles orbitaux.

## Télémétrie locale

Si `anatomy3d_enable_telemetry` est à `true`, le module met à jour `localStorage.anatomy3d_stats` pour compter :

- Nombre d'ouvertures de l'onglet.
- Scènes consultées.
- Captures PNG générées.

Aucune donnée n'est envoyée à un serveur.
