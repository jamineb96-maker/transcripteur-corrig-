# Architecture

## Convention des onglets

Chaque onglet du client suit les règles suivantes :

- **Source canonique** : `client/tabs/<tab>/` contient `index.js`, `view.html` et `style.css`.
- **Chemins HTTP** : les assets sont servis depuis `/static/tabs/<tab>/index.js`, `/static/tabs/<tab>/view.html` et `/static/tabs/<tab>/style.css`.
- **Attribut `data-tab`** : seul le conteneur injecté par le routeur (`section[data-tab="<clé>"]`) possède l’attribut. Les vues ne dupliquent plus cet attribut en interne.
- **Versioning** : `server/services/assets.get_asset_version()` concatène le contenu des assets canoniques (`index.js`, `view.html`, `style.css`) pour calculer un hash court injecté dans le template racine (`<meta name="asset-version">`). Les modules consomment ce hash via `withAssetVersion()` pour forcer l’invalidation du cache navigateur.
- **Diagnostics** : en mode développement (`data-debug="true"` sur `<body>`), `validateTab(tabKey, { assets, selectors })` vérifie que les trois assets retournent un HTTP 200, que tous les sélecteurs attendus existent dans la vue et qu’aucun doublon `client/static/tabs/<tab>` ne subsiste.

Pour ajouter un nouvel onglet, créez un dossier dans `client/tabs/`, exposez un module ES avec `init()/show()/hide()`, et référencez-le dans le routeur (`client/app.js`). Le serveur n’a besoin d’aucune configuration supplémentaire : le versioning et la détection de doublons s’appliquent automatiquement.

## Politique d'import

Les modules Python sous `server/tabs/` doivent respecter une règle explicite :

- Les dépendances communes (`services`, `util`, `library`, etc.) s'importent **depuis le paquet racine** : `from server.services import …`, `from server.util import …`.
- Les imports relatifs avec un seul point sont réservés aux modules frères du même onglet (ex. `from . import routes`).

Cette convention évite les erreurs `ModuleNotFoundError` liées aux imports relatifs qui sortent du paquet `server.tabs`.
