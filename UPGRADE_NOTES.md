# Notes de mise à niveau

Ce document explique comment migrer un ancien déploiement de la suite post‑séance vers la nouvelle version avec découpe par segments et idempotence.  Les anciens fichiers et scripts sont toujours reconnus, mais certaines habitudes doivent être mises à jour.

## Ruptures majeures

### Découpage audio

Auparavant, le transcripteur envoyait l’intégralité de l’audio au modèle Whisper en un seul appel.  Ceci provoquait des troncatures pour les enregistrements dépassant environ 8 minutes.  Désormais, la méthode `Transcriber.transcribe_audio()` divise systématiquement l’audio en fenêtres de taille configurable (120 s par défaut) avec un recouvrement de 4 s.  Le texte final est la concaténation des segments.  Aucune intervention n’est requise côté client : les paramètres `chunk_seconds` et `overlap_seconds` sont optionnels et ont des valeurs par défaut raisonnables.

### Idempotence

Chaque enregistrement est identifié de manière déterministe par une empreinte SHA256 des octets audio et des paramètres de découpe.  Cette clé (`session_id`) est renvoyée par les endpoints et utilisée comme sous‑répertoire pour persister les artefacts.  Lors d’une nouvelle requête avec le même fichier ou le même transcript :

* `/transcribe` renvoie le transcript et les segments depuis le cache et ajoute `"cached": true` dans la réponse.
* `/post_session` renvoie immédiatement le plan, l’analyse, le mail et les chemins relatifs vers les fichiers existants, avec `"cached": true` dans `meta`.

Pour forcer un recalcul malgré la présence d’un cache, supprimez le dossier correspondant dans `instance/archives/<patient>/<session_id>` ou passez une clé `idempotency_key` différente dans `options`.

### Structure des dossiers

Les artefacts sont désormais organisés ainsi :

```
instance/archives/
  <patient>/
    <session_id>/
      transcript.txt
      segments.json
      research.json
      analysis.json
      plan.txt
      mail.md
```

L’ancien dossier `Archive A-G` et suivants n’est plus mis à jour automatiquement.  Les sessions antérieures sont conservées pour référence mais ne sont plus modifiées par la nouvelle version.

## Scripts de démarrage

Les scripts `dev.sh`, `dev.ps1`, `run.sh` et `run.ps1` continuent de fonctionner sans modification.  Ils utilisent désormais l’application contenue dans `server/` qui implémente la découpe et l’idempotence.  Aucune option supplémentaire n’est nécessaire.

## Interface utilisateur

La version actuelle introduit un routeur SPA robuste et un gestionnaire de thème unifié :

* **Navigation par onglets** : les ancres (`#pre_session`), les paramètres `?tab=` et les chemins `/tab/…` sont désormais interprétés pour afficher le module adéquat.  La page d’accueil comporte l’identifiant `tab-home` et est masquée lorsque l’on navigue vers un autre module.
* **Thème clair/sombre** : l’application applique automatiquement le thème sombre en fonction de vos préférences système ou de votre choix explicite.  Utilisez `window.setTheme('light'|'dark'|'system')` dans la console pour tester.

La progression lors de la transcription affiche toujours le nombre de segments traités.

## Migration des données

Aucun script de migration automatique n’est fourni.  Les anciennes archives restent valides mais ne bénéficieront pas automatiquement de la nouvelle logique de découpe.  Pour migrer manuellement une ancienne séance :

1. Relancez une session en utilisant l’audio original (ou le transcript) via l’UI ou un appel API.
2. Laissez la pipeline recalculer le plan et le mail.  Les nouveaux fichiers seront enregistrés dans `instance/archives/<patient>/<nouvelle_clé>`.
3. Conservez ou archivez les anciens fichiers à des fins historiques.