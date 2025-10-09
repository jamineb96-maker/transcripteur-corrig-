# Tests manuels – Pré-séance

Ces vérifications couvrent le nouveau flux de préparation (plan + prompt), la persistance locale et le rechargement de l'onglet.

## Préparation du plan
1. Sélectionner un patient.
2. Coller des échanges de mails dans le champ « Mails bruts ».
3. Renseigner éventuellement les champs « Contexte » et « Paramètres internes ».
4. Cliquer sur « Préparer le plan » et vérifier que le plan structuré s'affiche.
5. Confirmer que les alertes facultatives signalent uniquement les champs restés vides.

## Génération du prompt
1. Après la préparation, cliquer sur « Générer le prompt ».
2. Vérifier que le statut passe par « Génération du prompt… » puis « Prompt prêt à copier ».
3. Contrôler que le prompt apparaît dans le bloc de sortie et respecte les règles métiers (pas d'accolades ni de mots bannis).

## Persistance locale
1. Modifier un contexte ou les paramètres internes puis cliquer sur « Sauvegarder ».
2. Changer de patient, puis revenir sur le patient initial.
3. Vérifier que les mails, contextes, paramètres internes, plan et prompt précédemment générés sont restaurés.

## Rechargement de l'onglet
1. Avec un plan et un prompt déjà générés, recharger la page du navigateur.
2. Vérifier que l'onglet « Pré-séance » restaure l'ensemble des champs et des sorties sans lancer de requête tant que l'utilisateur n'interagit pas.
3. Confirmer que le bouton « Générer le prompt » reste disponible et qu'un nouvel appui regénère uniquement le prompt.
