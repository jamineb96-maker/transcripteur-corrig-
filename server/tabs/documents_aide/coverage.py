"""Calcul du score de couverture documentaire."""

from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List

from .library import Tool

_NEED_DEFINITIONS = {
    'somatic_support': {
        'label': 'Régulation somatique',
        'tags': {'somatique', 'auto_soin'},
        'triggers': {'indices_somatiques'},
    },
    'cognitive_budget': {
        'label': 'Budget cognitif',
        'tags': {'cognitif', 'budget_cognitif'},
        'triggers': {'indices_cognitifs', 'ai_requests'},
    },
    'boundaries': {
        'label': 'Limites et consentement',
        'tags': {'boundaries', 'autoprotection', 'communication'},
        'triggers': {'contradiction_spans', 'objectifs_extraits'},
    },
}

_LENS_TO_NEED = {
    'validisme': {
        'id': 'lens_validisme',
        'label': 'Encadré validisme',
        'tags': {'lens:validisme', 'contextualisation'},
    },
    'patriarcat': {
        'id': 'lens_patriarcat',
        'label': 'Analyse patriarcat',
        'tags': {'lens:patriarcat'},
    },
    'trauma_complexe': {
        'id': 'lens_trauma',
        'label': 'Trauma complexe',
        'tags': {'lens:trauma'},
    },
    'neurodiversité': {
        'id': 'lens_neurodiversite',
        'label': 'Perspective neurodiverse',
        'tags': {'lens:neurodiversite'},
    },
}

_MICRO_PAUSE_KEYWORDS = {'micro-pause', 'micro pause', 'micro-pauses', 'micro sensorielles', 'micro-sensorielles'}
_LEVEL_LABELS = {'base': 'niveau de base', 'intermediaire': 'niveau intermédiaire', 'avance': 'niveau avancé'}


def _infer_expected_level(artefacts: Dict[str, object]) -> str | None:
    """Détermine le niveau attendu en fonction du budget cognitif implicite."""

    ai_requests = [str(item).lower() for item in artefacts.get('ai_requests') or [] if isinstance(item, str)]
    has_cognitive_signals = bool(artefacts.get('indices_cognitifs')) or any('budget' in req for req in ai_requests)
    if has_cognitive_signals:
        return 'base'

    evidence = artefacts.get('evidence_sheet') or []
    if evidence:
        return 'avance'

    if artefacts.get('lenses_used') or artefacts.get('objectifs_extraits'):
        return 'intermediaire'

    return None


def _evaluate_level_alignment(selected: List[Tool], artefacts: Dict[str, object]) -> Dict[str, object]:
    expected = _infer_expected_level(artefacts)
    counts = Counter()
    for module in selected:
        level = (module.level or '').lower()
        if level:
            counts[level] += 1

    total = sum(counts.values())
    alignment = {
        'expected': expected,
        'expected_label': _LEVEL_LABELS.get(expected or '', expected or ''),
        'distribution': dict(counts),
        'status': 'neutral',
        'message': '',
    }

    if not expected:
        return alignment

    expected_label = _LEVEL_LABELS.get(expected, expected)
    matching = counts.get(expected, 0)

    if total == 0:
        alignment['status'] = 'missing'
        alignment['message'] = (
            f"Aucun module sélectionné alors qu'un {expected_label} est recommandé pour le budget cognitif détecté."
        )
        return alignment

    if matching == total:
        alignment['status'] = 'aligned'
        alignment['message'] = f"{expected_label.capitalize()} respecté pour l'ensemble des modules sélectionnés."
        return alignment

    ratio = matching / total if total else 0
    distribution_parts = ', '.join(
        f"{_LEVEL_LABELS.get(level, level)} × {count}" for level, count in counts.items()
    )

    if ratio >= 0.5:
        alignment['status'] = 'partial'
        alignment['message'] = (
            f"Majorité de modules au {expected_label}, mais vérifier la charge des autres niveaux ({distribution_parts})."
        )
    else:
        alignment['status'] = 'mismatch'
        alignment['message'] = (
            f"Le {expected_label} attendu n'est pas respecté : sélection actuelle {distribution_parts}."
        )

    return alignment


def _selected_modules(tools: Iterable[Tool], selected_ids: Iterable[str]) -> List[Tool]:
    index = {tool.id: tool for tool in tools}
    return [index[module_id] for module_id in selected_ids if module_id in index]


def _module_has_tags(module: Tool, tags: Iterable[str]) -> bool:
    tool_tags = {tag.lower() for tag in module.tags}
    for tag in tags:
        if tag.lower() in tool_tags:
            return True
    return False


def assess_library_coverage(artefacts: Dict[str, object], selected_ids: Iterable[str], tools: Iterable[Tool]) -> Dict[str, object]:
    """Calcule le score de couverture et détecte les manques."""

    tools = list(tools)
    selected = _selected_modules(tools, selected_ids)
    needs_report: List[Dict[str, object]] = []

    for need_id, need in _NEED_DEFINITIONS.items():
        triggered = False
        for field in need['triggers']:
            values = artefacts.get(field)
            if isinstance(values, list) and values:
                triggered = True
            elif isinstance(values, str) and values.strip():
                triggered = True
        if not triggered:
            continue
        covered = any(_module_has_tags(module, need['tags']) for module in selected)
        covering_modules = [module.id for module in selected if _module_has_tags(module, need['tags'])]
        needs_report.append(
            {
                'id': need_id,
                'label': need['label'],
                'triggered': True,
                'covered': covered,
                'modules': covering_modules,
            }
        )

    lens_needs = []
    for lens in artefacts.get('lenses_used') or []:
        if not isinstance(lens, str):
            continue
        key = lens.lower()
        definition = _LENS_TO_NEED.get(key)
        if definition:
            covered = any(_module_has_tags(module, definition['tags']) for module in selected)
            covering_modules = [module.id for module in selected if _module_has_tags(module, definition['tags'])]
            lens_needs.append(
                {
                    'id': definition['id'],
                    'label': definition['label'],
                    'triggered': True,
                    'covered': covered,
                    'modules': covering_modules,
                    'lens': lens,
                }
            )
    needs_report.extend(lens_needs)

    triggered_needs = [need for need in needs_report if need['triggered']]
    if triggered_needs:
        covered_count = sum(1 for need in triggered_needs if need['covered'])
        score = round((covered_count / len(triggered_needs)) * 100)
    else:
        score = 100

    level_alignment = _evaluate_level_alignment(selected, artefacts)
    if level_alignment['status'] == 'mismatch':
        score = max(0, score - 25)
    elif level_alignment['status'] == 'partial':
        score = max(0, score - 10)
    elif level_alignment['status'] == 'missing':
        score = max(0, score - 15)

    status = 'ok'
    if score < 60:
        status = 'alerte'
    elif score < 80:
        status = 'a_renforcer'

    missing: List[Dict[str, object]] = []
    repere_candidates = artefacts.get('reperes_candidates') or []
    for rep in repere_candidates:
        if not isinstance(rep, str):
            continue
        lower = rep.lower()
        if any(keyword in lower for keyword in _MICRO_PAUSE_KEYWORDS):
            # Vérifie si un module existant couvre ce besoin
            has_module = any('micro' in tag.lower() for module in tools for tag in module.tags)
            if not has_module:
                missing.append(
                    {
                        'id': 'micro_sensory_breaks',
                        'label': 'Pauses micro-sensorielles',
                        'reason': 'Repère candidat mentionne des micro-pauses sensorielles absentes de la bibliothèque.',
                        'recommended_tags': ['somatique', 'auto_soin', 'budget_faible'],
                    }
                )
                break

    coverage = {
        'score': score,
        'status': status,
        'needs': needs_report,
        'missing_modules': missing,
        'level_alignment': level_alignment,
    }
    return coverage
