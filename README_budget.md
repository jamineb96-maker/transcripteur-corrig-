# Onglet « Budget cognitif et somatique »

Cet onglet introduit une estimation critique du budget de cuillères sur
une journée ou une semaine.  Il combine un interrogatoire guidé, un
moteur de calcul falsifiable et des exports PDF/DOCX psychoéducatifs.

## Architecture

- **Client** : `client/tabs/budget/` contient la vue, le style et la
  logique d'interaction.  L'UI se structure en trois panneaux
  (« Patient & paramètres », « Interrogatoire & estimation » et « Aperçu &
  export »).  Les curseurs d'intensité (0‑10) et les modificateurs
  aggravants/atténuants construisent un payload auditable.
- **API** : `server/tabs/budget/routes.py` expose
  - `GET /api/budget/presets`
  - `POST /api/budget/assess`
  - `POST /api/budget/export`
  - `POST /api/budget/save-profile`
  - `GET /api/budget/history`
  - `GET /api/budget/download/<file>`
- **Moteur** : `server/services/budget_engine.py` implémente le calcul du
  stock, des coûts, des récupérations et de la dette (projection sur
  3 jours ou 1 semaine).  Les coefficients sont chargés depuis
  `data/budget_presets.json`.
- **Exports** : `server/services/graphs.py` génère les diagrammes
  « cuillères » et « timeline effort/repos ».  `routes.py` assemble ensuite
  les PDF via ReportLab et les DOCX (python-docx).  Un garde-fou rejette
  les fichiers < 6 Ko.
- **Données** : `instance/budget_history/` stocke l'historique et les
  calibrations patient (profil bias par catégorie).  Le fichier est créé
  à la volée.

## Formules principales

- **Stock initial** : `S₀ = base(profile, période) + Σ modulateurs`
  (borné à 4 cuillères/jour).  Les modulateurs par défaut sont exposés
  dans `data/budget_presets.json` et peuvent être modifiés sans changer
  le code.
- **Coût d'une activité** :
  `Cᵢ = base(activity, intensité) × (1 + aggravants) × (1 − atténuants)`
  avec biais patient optionnels (±20 %) mémorisés dans le profil.
- **Récupération** : même formule avec coefficients positifs.
- **Solde et dette** : `S_net = S₀ − ΣCᵢ + ΣRⱼ` puis projection sur 3 ou
  7 jours avec un coefficient d'amortissement `α = 0.6`.  Les projections
  sont renvoyées pour alimenter les graphiques et l'alerte dette.

## Intégration Post-séance

Le client lit `post:v3:<patient>` dans `localStorage` (état conservé par
l'onglet Post-séance) et en extrait :

- indices somatiques et cognitifs (détection simple par mots-clés) ;
- objectifs extraits du plan ;
- contradictions (phrases contenant « mais », « pourtant », …) ;
- lentilles critiques (validisme, patriarcat) et demandes à l'IA.

Lorsque l'utilisateur coche « Importer les indices de la dernière
post-séance », les curseurs et modulateurs sont pré‑ajustés et des notes
contextuelles apparaissent dans le panneau de synthèse.

## Tests manuels suggérés

1. Sélectionner un patient, indiquer des intensités et lancer
   « Analyser » : le solde, les graphiques et le texte narratif doivent
   s'actualiser.
2. Activer l'import Post-séance après avoir rempli l'onglet Post-séance :
   les curseurs exécutifs et somatiques sont majorés, les modulateurs
   globalement abaissés.
3. Déclencher « Analyser & archiver » : l'historique se met à jour et un
   fichier JSON est écrit dans `instance/budget_history/`.
4. Exporter en PDF et DOCX : les fichiers contiennent les graphiques et
   la narration critique (taille > 6 Ko).
5. Enregistrer une calibration : la valeur est persistée et réappliquée
   au prochain calcul pour ce patient.

## Variables auditables

Les coefficients par défaut (bases, modulateurs, limites de dette) sont
regroupés dans `data/budget_presets.json`.  Modifier ce fichier suffit à
ajuster le modèle sans code supplémentaire.
