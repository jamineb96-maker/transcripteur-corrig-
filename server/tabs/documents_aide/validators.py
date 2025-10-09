"""Validateurs éditoriaux et de cohérence pour les documents d'aide."""

from __future__ import annotations

from typing import Dict, Iterable, List

from .library import Tool

_PROSCRIBED_TERMS = {
    'complexe d\'œdipe',
    'complexe d\'oedipe',
    'pulsion de mort',
    'transfert analytique',
}


def _jaccard(tags_a: Iterable[str], tags_b: Iterable[str]) -> float:
    set_a = {tag.lower() for tag in tags_a}
    set_b = {tag.lower() for tag in tags_b}
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def validate_selection(modules: List[Tool], artefacts: Dict[str, object], patient_contraindications: Iterable[str] = ()) -> Dict[str, List[Dict[str, str]]]:
    """Retourne les avertissements et erreurs relevés pour la sélection."""

    warnings: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []
    contraindications = {item.lower() for item in patient_contraindications}

    for module in modules:
        for term in _PROSCRIBED_TERMS:
            if term in module.file.read_text(encoding='utf-8').lower():
                errors.append(
                    {
                        'code': 'editorial_guard',
                        'module': module.id,
                        'message': "Formulation proscrite détectée (terminologie psychanalytique).",
                    }
                )
        for contraindication in module.contraindications:
            if contraindication.lower() in contraindications:
                errors.append(
                    {
                        'code': 'contraindication',
                        'module': module.id,
                        'message': f"Le module {module.title} est contre-indiqué pour ce profil.",
                    }
                )

    for idx, module in enumerate(modules):
        for other in modules[idx + 1 :]:
            overlap = _jaccard(module.tags, other.tags)
            if overlap >= 0.6:
                warnings.append(
                    {
                        'code': 'overlap',
                        'modules': f"{module.id},{other.id}",
                        'message': f"{module.title} et {other.title} couvrent des thèmes très proches.",
                    }
                )

    if artefacts.get('indices_cognitifs'):
        intense_modules = [module for module in modules if 'intensif' in {tag.lower() for tag in module.tags}]
        if intense_modules:
            warnings.append(
                {
                    'code': 'budget_contraint',
                    'modules': ','.join(module.id for module in intense_modules),
                    'message': "Budget cognitif fragile détecté : privilégier les variantes allégées.",
                }
            )

    return {'warnings': warnings, 'errors': errors}
