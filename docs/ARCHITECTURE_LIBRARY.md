# Bibliothèque clinique — Aperçu initial

Ce document décrit la future architecture du module Bibliothèque. Il
sera complété au fil des implémentations successives.

## Objectifs

- Ingestion de documents PDF et calcul d'un identifiant stable.
- Extraction, segmentation et validation humaine des notions clés.
- Indexation hybride (FTS + vecteurs) pour alimenter les suggestions des
  onglets Pré‑séance et Post‑séance.
- Journalisation et traçabilité complètes.

## Structure provisoire

Le repo contient désormais des dossiers dédiés sous `library/` pour
héberger les artefacts d'ingestion (PDF, extractions, index et journaux).
Les blueprints et modules Python correspondants sont initialisés sous
`modules/` et `server/blueprints/`.

Une feature flag `features.library_autosuggest` est défini dans
`config/app_config.json` et restera désactivé tant que le pipeline
complète n'est pas en production.
