"""Génération des gabarits de modules à créer."""

from __future__ import annotations

from typing import Dict, List


_MICRO_PAUSE_TEMPLATE = """# Pauses micro-sensorielles express

Ce module propose des micro-pauses de 30 à 90 secondes adaptées aux contextes matérialistes de {{PATIENT_PRÉNOM}}.

## Avant de commencer

- Identifier les contraintes matérielles : lieu, accessibilité, disponibilité des outils sensoriels.
- Clarifier avec {{PRONOM_SUJET}} le niveau d'énergie disponible.

## Protocole express

1. Choisir un repère sensoriel (texture, son, odeur) accessible immédiatement.
2. Lancer un minuteur doux (30 à 90 secondes) et se concentrer sur la respiration basse.
3. Noter après coup ce qui a aidé, avec une question fermée.

### Variante budget faible

- Préparer une carte mémo avec deux options de micro-pauses.
- Autoriser la pause à n'importe quel moment sans justification.

### Consignes de sécurité

- Interrompre la micro-pause si des douleurs aiguës apparaissent.
- Documenter les obstacles matériels rencontrés (bruit, surveillance, manque d'intimité).
"""


def build_recommendations(missing_modules: List[Dict[str, object]], artefacts: Dict[str, object]) -> List[Dict[str, object]]:
    """Construit les recommandations d'enrichissement de la bibliothèque."""

    recommendations: List[Dict[str, object]] = []
    evidence = artefacts.get('evidence_sheet') or []
    refs = []
    for item in evidence:
        if isinstance(item, dict):
            title = item.get('title') or item.get('reference')
            author = item.get('author') or ''
            year = item.get('year') or ''
            if title:
                refs.append(f"{title} — {author} {year}".strip())
        elif isinstance(item, str):
            refs.append(item)

    for missing in missing_modules:
        module_id = missing.get('id')
        if module_id == 'micro_sensory_breaks':
            recommendations.append(
                {
                    'id': 'micro_sensory_breaks',
                    'title': 'Gabarit — Pauses micro-sensorielles',
                    'recommended_tags': missing.get('recommended_tags', ['somatique']),
                    'template': _MICRO_PAUSE_TEMPLATE,
                    'references': refs,
                    'notes': 'Créer un module orienté micro-pauses pour budgets énergétiques très faibles.',
                }
            )
        else:
            recommendations.append(
                {
                    'id': module_id or 'module_inconnu',
                    'title': missing.get('label', 'Nouveau module'),
                    'recommended_tags': missing.get('recommended_tags', []),
                    'template': '# Titre\n\nContenu à rédiger en utilisant les tokens {{TUT|VOUS}} et {{GEN:...}}.',
                    'references': refs,
                    'notes': missing.get('reason', ''),
                }
            )
    return recommendations
