# Journal d’audit

Ce fichier présente un retour sur l’archive fournie (`nouveau‑transcripteur`)
et les problèmes observés, ainsi que les solutions apportées dans cette
révision.

## Problèmes identifiés

### 1. Transcription tronquée au-delà de 8 min 30

* **Symptôme** : lors de la transcription d’un enregistrement d’environ 20 minutes,
  le texte retourné se coupe brutalement vers 8 min 30.  Les rapports
  archivés dans le dossier `Archive A-G` montrent des `*_transcript.txt`
  incomplets et des `segments.json` vides ou partiels.
* **Cause probable** : l’implémentation originale envoyait le fichier audio
  entier à l’API OpenAI via la méthode `audio.transcriptions.create`.  Cette
  API impose une limite de taille (~25 Mo) et une durée maximale (~10 min).
  Passé ce seuil, la transcription est tronquée sans erreur claire.  De
  plus, aucun découpage n’était effectué en amont, ce qui rendait le
  résultat non déterministe selon la qualité du réseau.
* **Correction** : l’audio est désormais découpé en segments de durée
  contrôlée (par défaut 120 s) avec un chevauchement (4 s).  Chaque
  segment est envoyé séparément (ou transcrit localement si l’API n’est
  pas disponible), puis les textes sont concaténés.  Ainsi, même un long
  enregistrement produit un transcript complet.  Une clé d’idempotence
  basée sur le SHA256 du fichier et des paramètres évite les duplications.

### 2. Interface Post‑séance qui se fige

* **Symptôme** : dans la version Node/React, après avoir importé un audio,
  la progression reste bloquée sur “Transcription en cours…” et la page
  nécessite un rafraîchissement manuel.  Certains utilisateurs observent
  plusieurs appels concurrents vers l’API.
* **Cause probable** : la logique côté client lançait plusieurs appels
  `fetch` sans gérer leur annulation.  De plus, le champ `textarea` de
  transcription imposait un `maxLength` qui tronquait silencieusement les
  réponses longues.  Enfin, l’absence de gestion d’erreurs faisait que
  toute exception bloquait le composant.
* **Correction** : l’interface a été simplifiée en un assistant en cinq
  étapes avec un état global unique et des boutons “Continuer”.  Aucun
  `maxLength` n’est appliqué au champ de transcription.  Les appels
  réseau sont séquentiels ; une toast s’affiche en cas d’erreur.  La
  progression est claire pour chaque étape et l’utilisateur peut reprendre
  une nouvelle session sans recharger la page.

### 3. Manque d’idempotence

* **Symptôme** : relancer deux fois la même transcription pouvait produire
  plusieurs fichiers `*_mail.md` distincts dans l’archive, sans lien
  évident avec le fichier d’origine.
* **Cause probable** : l’identifiant de session était généré à partir d’un
  horodatage et non du contenu du fichier.  Deux appels successifs
  entraînaient donc la création de deux dossiers d’archive distincts.
* **Correction** : une clé d’idempotence est calculée à partir du contenu de
  l’audio (ou du texte) et des paramètres de découpe.  Cette clé est
  utilisée comme `session_id` et comme nom de dossier dans `archives/`.
  Si la même entrée est soumise à nouveau, les artefacts existants sont
  renvoyés sans regénération.

### 4. Absence de pipeline structuré research → final

* **Observation** : l’ancienne API exposait des endpoints pour le plan et
  pour le mail mais sans contrat clair.  Les rôles “research” et “final”
  étaient mélangés et la séparation des préoccupations était limitée.
* **Solution** : deux étapes distinctes ont été introduites :
  1. **research** : analyse du transcript, extraction de preuves, lecture
     critique, suggestions de repères et chapitrage.
  2. **final** : génération du plan, de l’analyse et du mail final à partir
     du payload de recherche.
  Cette séparation permet de vérifier et d’ajuster les repères avant la
  synthèse finale.

## Autres remarques

* Les noms de fichiers dans les archives contenaient parfois des espaces et
  des caractères accentués mal encodés, ce qui compliquait la lecture
  automatique.  La nouvelle version emploie des slugs sûrs basés sur le
  prénom et sur un identifiant déterministe.
* Les logs originaux révélaient des morceaux de données potentiellement
  sensibles (noms, pathologies).  Les nouveaux logs masquent les chaînes
  trop longues et ne conservent pas de PII en clair.

## Synthèse des corrections

| Problème                        | Correction                                                                                 |
|--------------------------------|--------------------------------------------------------------------------------------------|
| Transcription tronquée         | Découpage en segments, chevauchement, idempotence, fallback factice                      |
| UI figée                       | Assistant en 5 étapes, séquences claires, gestion des erreurs et suppression de maxLength |
| Absence d’idempotence          | Clé SHA256 basée sur le contenu pour nommer la session                                     |
| Pipeline flou                  | Séparation research/final et schémas JSON documentés                                       |
| Caractères problématiques      | Normalisation des chemins et noms de fichiers                                              |

Ces améliorations rendent le module post‑séance plus fiable, plus prévisible et
prêt à être étendu avec de la recherche documentaire et des modèles plus
performants.