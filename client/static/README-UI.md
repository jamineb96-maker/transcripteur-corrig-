# Navigation Priority+

La barre d'onglets applique le motif Priority+ pour conserver les modules à plus forte valeur dans la zone visible et basculer les autres dans le menu de débordement quand l'espace se raréfie.
Le script `client/static/components/header.js` expose le tableau `NAV_ITEMS` : chaque entrée définit l'onglet, sa route et un score `priority`. Plus le score est élevé, plus l'onglet est gardé dans la barre avant les autres.
Lors de l'initialisation, `header.js` trie `NAV_ITEMS` par priorité puis génère la barre et le menu secondaire ; à priorité égale, l'ordre du tableau est conservé.
Ajustez la priorité d'un module en modifiant la valeur `priority` correspondante dans `NAV_ITEMS`, puis rechargez l'interface pour appliquer le nouveau classement.
Les styles responsives de la barre et du menu sont centralisés dans `client/styles/base.css` (sections `.tabs`, `.tabs a` et `.header-actions`).
Pour ajouter un nouvel onglet, déclarez-le dans `NAV_ITEMS` avec son identifiant, son libellé et sa priorité, puis créez le module dans `client/tabs/<mon-onglet>/`.
Ajoutez ensuite son identifiant dans le tableau `TABS` et la table `TAB_PATHS` de `client/app.js` afin que le chargeur dynamique sache récupérer les ressources.
Enfin, vérifiez les règles CSS de `base.css` pour adapter l'affichage (largeur minimale, comportement overflow) si votre onglet nécessite un style particulier.
